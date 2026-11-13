"""Observability: spans, structured events, metrics and log buffering."""
from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from src.config import RUNS_DIR
from src.core.events import RunStore, new_id, utcnow


class Tracer:
    """Lightweight OpenTelemetry-compatible trace recorder.

    Spans are attached to a run and persisted as part of the run JSON so they
    can be inspected in the dashboard with no external collector required.
    """

    def __init__(self, run_store: RunStore):
        self.run_store = run_store
        self._lock = threading.Lock()

    @contextmanager
    def span(
        self,
        name: str,
        run_id: Optional[str] = None,
        attributes: Optional[dict] = None,
    ) -> Iterator[dict]:
        span = {
            "id": new_id("span"),
            "name": name,
            "started_at": utcnow(),
            "started_monotonic": time.perf_counter(),
            "attributes": attributes or {},
            "status": "ok",
            "error": None,
            "duration_ms": 0.0,
        }
        try:
            yield span
        except Exception as exc:  # noqa: BLE001 - recorded and re-raised
            span["status"] = "error"
            span["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            span["duration_ms"] = round(
                (time.perf_counter() - span["started_monotonic"]) * 1000, 2
            )
            span.pop("started_monotonic", None)
            span["ended_at"] = utcnow()
            if run_id:
                try:
                    record = self.run_store.get(run_id) or {}
                    spans = record.get("spans", [])
                    spans.append(span)
                    with self._lock:
                        self.run_store.update(run_id, spans=spans)
                    self.run_store.add_event(
                        run_id,
                        "trace.span",
                        {
                            "span": span["name"],
                            "duration_ms": span["duration_ms"],
                            "status": span["status"],
                        },
                        level="error" if span["status"] == "error" else "debug",
                    )
                except KeyError:
                    pass


class MetricsRegistry:
    """Prometheus-style counters, gauges and histograms."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple], float] = {}
        self._histograms: dict[tuple[str, tuple], list[float]] = defaultdict(list)

    @staticmethod
    def _key(name: str, labels: Optional[dict]) -> tuple[str, tuple]:
        return name, tuple(sorted((labels or {}).items()))

    def inc(self, name: str, value: float = 1.0, labels: Optional[dict] = None) -> None:
        with self._lock:
            self._counters[self._key(name, labels)] += value

    def gauge(self, name: str, value: float, labels: Optional[dict] = None) -> None:
        with self._lock:
            self._gauges[self._key(name, labels)] = value

    def observe(self, name: str, value: float, labels: Optional[dict] = None) -> None:
        with self._lock:
            values = self._histograms[self._key(name, labels)]
            values.append(value)
            if len(values) > 5000:
                del values[:1000]

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for (name, labels), value in sorted(self._counters.items()):
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{name}{self._fmt_labels(labels)} {value:g}")
            for (name, labels), value in sorted(self._gauges.items()):
                lines.append(f"# TYPE {name} gauge")
                lines.append(f"{name}{self._fmt_labels(labels)} {value:g}")
            for (name, labels), values in sorted(self._histograms.items()):
                if not values:
                    continue
                sorted_values = sorted(values)
                lines.append(f"# TYPE {name} histogram")
                for q, label in ((0.5, "0.5"), (0.9, "0.9"), (0.99, "0.99")):
                    idx = min(len(sorted_values) - 1, int(q * len(sorted_values)))
                    lines.append(
                        f'{name}{self._fmt_labels(labels, {"quantile": label})} {sorted_values[idx]:g}'
                    )
                lines.append(
                    f'{name}_count{self._fmt_labels(labels)} {len(sorted_values)}'
                )
                lines.append(
                    f'{name}_sum{self._fmt_labels(labels)} {sum(sorted_values):g}'
                )
        return "\n".join(lines) + ("\n" if lines else "")

    @staticmethod
    def _fmt_labels(labels: tuple, extra: Optional[dict] = None) -> str:
        items = dict(labels)
        if extra:
            items.update(extra)
        if not items:
            return ""
        body = ",".join(f'{k}="{v}"' for k, v in sorted(items.items()))
        return "{" + body + "}"

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "counters": {
                    f"{name}{self._fmt_labels(labels)}": value
                    for (name, labels), value in self._counters.items()
                },
                "gauges": {
                    f"{name}{self._fmt_labels(labels)}": value
                    for (name, labels), value in self._gauges.items()
                },
                "histograms": {
                    f"{name}{self._fmt_labels(labels)}": {
                        "count": len(values),
                        "avg": round(sum(values) / len(values), 3) if values else 0,
                        "max": max(values) if values else 0,
                    }
                    for (name, labels), values in self._histograms.items()
                },
            }


class LogBuffer:
    """Bounded structured log buffer exposed through the dashboard."""

    def __init__(self, capacity: int = 2000):
        self._entries: list[dict] = []
        self._capacity = capacity
        self._lock = threading.Lock()

    def add(self, level: str, message: str, **context: Any) -> dict:
        entry = {
            "timestamp": utcnow(),
            "level": level.lower(),
            "message": message,
            "context": context,
        }
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self._capacity:
                del self._entries[: len(self._entries) - self._capacity]
        return entry

    def list(self, level: str = "", limit: int = 200) -> list[dict]:
        with self._lock:
            entries = list(reversed(self._entries))
        if level:
            entries = [e for e in entries if e["level"] == level]
        return entries[:limit]


class JsonlExporter:
    """Append-only JSONL exporter for runs and traces (MLOps friendly)."""

    def __init__(self, directory: Path = RUNS_DIR):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def export(self, name: str, payload: dict) -> None:
        path = self.directory / f"{name}.jsonl"
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with self._lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
