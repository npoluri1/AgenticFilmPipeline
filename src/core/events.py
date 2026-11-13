"""Runtime state: event-sourced runs, background jobs and artifact storage."""
from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from src.config import ARTIFACTS_DIR, RUNS_DIR


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_id(prefix: str = "run") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class RunStore:
    """In-memory run registry with JSON persistence and an append-only event log."""

    def __init__(self, directory: Path = RUNS_DIR):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._runs: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def create(self, kind: str, meta: Optional[dict] = None, run_id: str | None = None) -> dict:
        run_id = run_id or new_id(kind)
        record = {
            "id": run_id,
            "kind": kind,
            "status": "queued",
            "created_at": utcnow(),
            "updated_at": utcnow(),
            "started_at": None,
            "finished_at": None,
            "progress": 0.0,
            "stage": "queued",
            "meta": meta or {},
            "events": [],
            "result": None,
            "error": None,
        }
        with self._lock:
            self._runs[run_id] = record
        self.add_event(run_id, "run.created", {"kind": kind})
        self._persist(run_id)
        return record

    def update(self, run_id: str, **fields: Any) -> dict:
        with self._lock:
            record = self._runs.get(run_id)
            if not record:
                raise KeyError(f"run not found: {run_id}")
            record.update(fields)
            record["updated_at"] = utcnow()
        self._persist(run_id)
        return record

    def add_event(
        self,
        run_id: str,
        event_type: str,
        data: Optional[dict] = None,
        level: str = "info",
    ) -> dict:
        with self._lock:
            record = self._runs.get(run_id)
            if not record:
                raise KeyError(f"run not found: {run_id}")
            event = {
                "seq": len(record["events"]),
                "type": event_type,
                "level": level,
                "timestamp": utcnow(),
                "data": data or {},
            }
            record["events"].append(event)
            if event_type == "run.stage":
                record["stage"] = (data or {}).get("stage", record.get("stage"))
                record["progress"] = max(
                    record.get("progress", 0.0), float((data or {}).get("progress", 0.0))
                )
            record["updated_at"] = utcnow()
        self._persist(run_id)
        return event

    def events_since(self, run_id: str, index: int = 0) -> list[dict]:
        with self._lock:
            record = self._runs.get(run_id)
            if not record:
                return []
            return list(record["events"][index:])

    def get(self, run_id: str) -> Optional[dict]:
        with self._lock:
            record = self._runs.get(run_id)
            if record:
                return json.loads(json.dumps(record, ensure_ascii=False))
        path = self.directory / f"{run_id}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
        return None

    def list(self, limit: int = 20, kind: Optional[str] = None) -> list[dict]:
        records = list(self._runs.values())
        if kind:
            records = [r for r in records if r.get("kind") == kind]
        records.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return [
            {
                k: r.get(k)
                for k in (
                    "id", "kind", "status", "progress", "stage", "created_at",
                    "updated_at", "started_at", "finished_at", "error", "meta",
                )
            }
            for r in records[:limit]
        ]

    def count(self) -> int:
        with self._lock:
            return len(self._runs)

    def _persist(self, run_id: str) -> None:
        with self._lock:
            record = self._runs.get(run_id)
            if not record:
                return
            payload = json.dumps(record, ensure_ascii=False, indent=2)
        try:
            (self.directory / f"{run_id}.json").write_text(payload, encoding="utf-8")
        except OSError:
            pass


class EventBus:
    """Thin convenience wrapper over a RunStore event log."""

    def __init__(self, store: RunStore):
        self.store = store

    def emit(self, run_id: str, event_type: str, data: Optional[dict] = None, level: str = "info") -> dict:
        return self.store.add_event(run_id, event_type, data, level)

    def stage(self, run_id: str, stage: str, progress: float, **data: Any) -> dict:
        return self.store.add_event(
            run_id,
            "run.stage",
            {"stage": stage, "progress": round(progress, 4), **data},
        )


class JobManager:
    """Background execution for long-running pipeline and evaluation jobs."""

    def __init__(self, max_workers: int = 4):
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="afp-job")
        self._futures: dict[str, Future] = {}
        self._lock = threading.Lock()

    def submit(self, job_id: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
        future = self._pool.submit(fn, *args, **kwargs)
        with self._lock:
            self._futures[job_id] = future
        future.add_done_callback(lambda _f: self._cleanup(job_id))
        return future

    def _cleanup(self, job_id: str) -> None:
        with self._lock:
            self._futures.pop(job_id, None)

    def running(self) -> int:
        with self._lock:
            return sum(1 for f in self._futures.values() if not f.done())

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


class ArtifactStore:
    """Durable artifact storage rooted at ``output/artifacts``."""

    def __init__(self, root: Path = ARTIFACTS_DIR):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def path(self, relative: str) -> Path:
        safe = Path(str(relative).replace("\\", "/"))
        if safe.is_absolute() or ".." in safe.parts:
            raise ValueError(f"invalid artifact path: {relative}")
        full = (self.root / safe).resolve()
        if self.root.resolve() not in full.parents and full != self.root.resolve():
            raise ValueError(f"artifact escapes root: {relative}")
        return full

    def save_bytes(self, relative: str, data: bytes) -> str:
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            target.write_bytes(data)
        return str(target)

    def save_text(self, relative: str, text: str, encoding: str = "utf-8") -> str:
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            target.write_text(text, encoding=encoding)
        return str(target)

    def save_json(self, relative: str, payload: Any) -> str:
        return self.save_text(
            relative, json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        )

    def exists(self, relative: str) -> bool:
        try:
            return self.path(relative).exists()
        except ValueError:
            return False

    def url(self, relative: str) -> str:
        return "/artifacts/" + str(relative).replace("\\", "/").lstrip("/")

    def list(self, prefix: str = "", limit: int = 500) -> list[dict]:
        base = self.path(prefix) if prefix else self.root
        if not base.exists():
            return []
        results: list[dict] = []
        files = [base] if base.is_file() else sorted(base.rglob("*"))
        for file in files:
            if not file.is_file():
                continue
            rel = file.relative_to(self.root).as_posix()
            try:
                stat = file.stat()
            except OSError:
                continue
            results.append({
                "path": rel,
                "url": self.url(rel),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "type": file.suffix.lstrip(".").lower() or "file",
            })
            if len(results) >= limit:
                break
        return results

    def manifest(self, prefix: str = "") -> dict:
        files = self.list(prefix)
        by_type: dict[str, int] = {}
        for f in files:
            by_type[f["type"]] = by_type.get(f["type"], 0) + 1
        return {
            "root": str(self.root),
            "total_files": len(files),
            "total_bytes": sum(f["size"] for f in files),
            "by_type": by_type,
        }
