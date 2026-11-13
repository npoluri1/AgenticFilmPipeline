"""Agent memory: episodic run memory + persistent semantic notes.

Free-first: embeddings come from the deterministic hash embedder, so memory
works with zero external services. Swap in a stronger embedder transparently.
"""
from __future__ import annotations

import json
import math
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.config import MEMORY_DIR
from src.core.text import stable_hash, tokenize


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class _HashEmbedder:
    """Deterministic bag-of-features embedding (no model download required)."""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = tokenize(text)
        for token in tokens:
            idx = int(stable_hash(token)[:8], 16) % self.dim
            vec[idx] += 1.0
        # bigrams add a little phrase awareness
        for a, b in zip(tokens, tokens[1:]):
            idx = int(stable_hash(a + "_" + b)[:8], 16) % self.dim
            vec[idx] += 0.5
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class MemoryStore:
    def __init__(self, directory: Path = MEMORY_DIR, dim: int = 384):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "notes.jsonl"
        self.embedder = _HashEmbedder(dim)
        self._lock = threading.RLock()
        self._notes: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    self._notes.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass

    def remember(
        self,
        text: str,
        scope: str = "semantic",
        key: str = "",
        tags: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict:
        note = {
            "id": f"mem_{stable_hash(text + key + scope)[:12]}",
            "scope": scope,
            "key": key,
            "text": text,
            "tags": tags or [],
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "embedding": self.embedder.embed(text),
        }
        with self._lock:
            self._notes = [n for n in self._notes if n["id"] != note["id"]]
            self._notes.append(note)
            self._append(note)
        return {k: v for k, v in note.items() if k != "embedding"}

    def _append(self, note: dict) -> None:
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({k: v for k, v in note.items() if k != "embedding"}, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def recall(self, query: str, k: int = 5, scope: Optional[str] = None) -> list[dict]:
        q = self.embedder.embed(query)
        with self._lock:
            notes = [n for n in self._notes if not scope or n.get("scope") == scope]
        scored = []
        for note in notes:
            emb = note.get("embedding") or self.embedder.embed(note.get("text", ""))
            scored.append((_cosine(q, emb), note))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            {
                "id": n["id"],
                "scope": n["scope"],
                "key": n["key"],
                "text": n["text"],
                "tags": n.get("tags", []),
                "metadata": n.get("metadata", {}),
                "created_at": n["created_at"],
                "score": round(score, 4),
            }
            for score, n in scored[:k]
        ]

    def summarize_run(self, run_summary: dict) -> dict:
        text = (
            f"Run {run_summary.get('id')} finished with status "
            f"{run_summary.get('status')}. Stage summary: "
            f"{json.dumps(run_summary.get('result', {}), ensure_ascii=False)[:1200]}"
        )
        return self.remember(
            text,
            scope="episodic",
            key=str(run_summary.get("id", "")),
            tags=["pipeline", "run"],
            metadata={"status": run_summary.get("status")},
        )

    def list(self, limit: int = 100, scope: Optional[str] = None) -> list[dict]:
        with self._lock:
            notes = [n for n in self._notes if not scope or n.get("scope") == scope]
        notes = sorted(notes, key=lambda n: n["created_at"], reverse=True)[:limit]
        return [{k: v for k, v in n.items() if k != "embedding"} for n in notes]

    def stats(self) -> dict:
        with self._lock:
            scopes: dict[str, int] = {}
            for n in self._notes:
                scopes[n.get("scope", "semantic")] = scopes.get(n.get("scope", "semantic"), 0) + 1
        return {"total": len(self._notes), "scopes": scopes, "path": str(self.path)}
