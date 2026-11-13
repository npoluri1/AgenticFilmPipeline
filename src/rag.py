"""Retrieval layer: screenplay chunking, vector search and GraphRAG.

* Deterministic hash embeddings by default (offline, free)
* Optional FAISS acceleration
* Persistent index under ``output/index``
* A screenplay knowledge graph (Acts -> Sequences -> Shots -> Characters/Themes)
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from src.config import INDEX_DIR
from src.core.text import stable_hash, tokenize, truncate
from src.models.schemas import FilmScript
from src.providers import registry as provider_registry

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except Exception:  # pragma: no cover
    NUMPY_AVAILABLE = False

try:
    import faiss  # type: ignore
    FAISS_AVAILABLE = True
except Exception:  # pragma: no cover
    FAISS_AVAILABLE = False


@dataclass
class Chunk:
    id: str
    kind: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: Optional[list[float]] = None

    def public(self, score: Optional[float] = None) -> dict:
        payload = {
            "id": self.id,
            "kind": self.kind,
            "text": self.text,
            "metadata": self.metadata,
        }
        if score is not None:
            payload["score"] = round(float(score), 4)
        return payload


def _fingerprint(film: FilmScript, script_path: str = "") -> str:
    raw = "|".join([
        film.title,
        film.telugu_title,
        str(film.runtime_minutes),
        str(len(film.acts)),
        script_path,
        str(len(film.cast)),
        str(len(film.music_themes)),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class ScreenplayGraph:
    """Lightweight heterogeneous knowledge graph for GraphRAG."""

    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self._adj: dict[str, set[str]] = {}

    def add_node(self, node_id: str, kind: str, label: str, metadata: Optional[dict] = None) -> None:
        self.nodes[node_id] = {
            "id": node_id,
            "kind": kind,
            "label": truncate(label, 120),
            "metadata": metadata or {},
        }

    def add_edge(self, source: str, target: str, relation: str) -> None:
        if source not in self.nodes or target not in self.nodes:
            return
        key = (source, target, relation)
        if any(e["source"] == source and e["target"] == target and e["relation"] == relation for e in self.edges):
            return
        self.edges.append({"source": source, "target": target, "relation": relation})
        self._adj.setdefault(source, set()).add(target)
        self._adj.setdefault(target, set()).add(source)

    def neighbors(self, node_id: str, hops: int = 1) -> set[str]:
        frontier = {node_id}
        visited = {node_id}
        for _ in range(max(0, hops)):
            nxt: set[str] = set()
            for node in frontier:
                for neighbor in self._adj.get(node, set()):
                    if neighbor not in visited:
                        nxt.add(neighbor)
                        visited.add(neighbor)
            frontier = nxt
            if not frontier:
                break
        visited.discard(node_id)
        return visited

    def summary(self) -> dict:
        by_kind: dict[str, int] = {}
        for node in self.nodes.values():
            by_kind[node["kind"]] = by_kind.get(node["kind"], 0) + 1
        by_relation: dict[str, int] = {}
        for edge in self.edges:
            by_relation[edge["relation"]] = by_relation.get(edge["relation"], 0) + 1
        degree = sorted(
            ({"id": n, "degree": len(self._adj.get(n, set())), **self.nodes[n]} for n in self.nodes),
            key=lambda n: n["degree"],
            reverse=True,
        )[:10]
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "node_kinds": by_kind,
            "relations": by_relation,
            "top_nodes": degree,
        }

    def to_dict(self) -> dict:
        return {
            "nodes": list(self.nodes.values()),
            "edges": self.edges,
            "summary": self.summary(),
        }


class RAGEngine:
    def __init__(self, directory: Path = INDEX_DIR):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.chunks: list[Chunk] = []
        self.graph = ScreenplayGraph()
        self.fingerprint = ""
        self._matrix: Any = None
        self._faiss_index: Any = None
        self._lock = threading.RLock()
        self.embedder = provider_registry.embeddings
        self.meta: dict[str, Any] = {}

    # ── build / load ─────────────────────────────────────────────────────
    def build(self, film: FilmScript, script_path: str = "") -> dict:
        with self._lock:
            self.fingerprint = _fingerprint(film, script_path)
            self.chunks = []
            self.graph = ScreenplayGraph()
            self._build_from_film(film)
            texts = [c.text for c in self.chunks]
            vectors = self.embedder.embed_many(texts) if texts else []
            for chunk, vector in zip(self.chunks, vectors):
                chunk.embedding = vector
            self._matrix = np.asarray(vectors, dtype="float32") if NUMPY_AVAILABLE and vectors else None
            self._build_faiss()
            self.meta = {
                "fingerprint": self.fingerprint,
                "script_path": script_path,
                "title": film.title,
                "chunks": len(self.chunks),
                "embedding_backend": self.embedder.info()["backend"],
                "dimension": self.embedder.info()["dimension"],
                "faiss": FAISS_AVAILABLE,
                "built_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            }
            self._persist()
            return self.stats()

    def _build_from_film(self, film: FilmScript) -> None:
        film_id = "film:root"
        self.graph.add_node(film_id, "film", film.title, {
            "telugu_title": film.telugu_title,
            "runtime_minutes": film.runtime_minutes,
            "languages": film.languages,
        })
        self._add_chunk(
            "film", f"{film.title} ({film.telugu_title}). {film.runtime_str}. "
            f"Languages: {', '.join(film.languages)}. Aspect ratio {film.aspect_ratio}. "
            f"{len(film.acts)} acts, {sum(len(a.sequences) for a in film.acts)} sequences.",
            {"film": film.title, "runtime_minutes": film.runtime_minutes, "node": film_id},
        )

        # Characters
        character_nodes: dict[str, str] = {}
        for member in film.cast:
            name = member.role.split("(")[0].strip()
            node_id = f"character:{name}"
            character_nodes[name.lower()] = node_id
            self.graph.add_node(node_id, "character", name, {"actor": member.actor, "function": member.function})
            self.graph.add_edge(film_id, node_id, "features")
            self._add_chunk("character", f"{name} — played by {member.actor}. {member.function}", {
                "character": name, "actor": member.actor, "node": node_id,
            })

        # Music themes
        theme_nodes: dict[str, str] = {}
        for theme in film.music_themes:
            node_id = f"theme:{theme.name}"
            theme_nodes[theme.name.lower()] = node_id
            self.graph.add_node(node_id, "theme", theme.name, {
                "telugu_name": theme.telugu_name, "instruments": theme.instruments,
                "inspiration": theme.inspiration, "usage_rule": theme.usage_rule,
            })
            self.graph.add_edge(film_id, node_id, "has_theme")
            self._add_chunk("theme", (
                f"{theme.name} ({theme.telugu_name}): {theme.description}. "
                f"Instruments: {theme.instruments}. Inspired by: {theme.inspiration}. "
                f"Usage: {theme.usage_rule}"
            ), {"theme": theme.name, "node": node_id})

        # Acts / sequences / shots
        for act in film.acts:
            act_id = f"act:{act.number}"
            self.graph.add_node(act_id, "act", f"Act {act.number}: {act.english_subtitle}", {
                "telugu_subtitle": act.telugu_subtitle, "start_time": act.start_time, "end_time": act.end_time,
            })
            self.graph.add_edge(film_id, act_id, "contains")
            act_shots = sum(len(s.shots) for s in act.sequences)
            self._add_chunk("act", (
                f"Act {act.number} — {act.english_subtitle} ({act.telugu_subtitle}). "
                f"Runtime {act.start_time}–{act.end_time}. {len(act.sequences)} sequences, {act_shots} shots."
            ), {"act": act.number, "node": act_id})

            for seq in act.sequences:
                seq_id = f"sequence:{seq.number}"
                self.graph.add_node(seq_id, "sequence", f"Sequence {seq.number}: {seq.english_name}", {
                    "act": act.number, "telugu_name": seq.telugu_name, "runtime_minutes": seq.runtime_minutes,
                })
                self.graph.add_edge(act_id, seq_id, "contains")
                shot_summaries = "; ".join(
                    f"[{s.number}] {s.setting} ({s.duration_sec}s)"
                    for s in seq.shots[:12]
                )
                self._add_chunk("sequence", (
                    f"Sequence {seq.number} — {seq.english_name} ({seq.telugu_name}). "
                    f"Act {act.number}. Runtime {seq.runtime_minutes} minutes. "
                    f"Shots: {shot_summaries}"
                ), {"act": act.number, "sequence": seq.number, "node": seq_id})

                for shot in seq.shots:
                    shot_id = f"shot:{shot.number}"
                    dialog_text = " ".join(
                        f"{d.get('character', '')}: {d.get('telugu', '')} ({d.get('english', '')})"
                        for d in shot.dialog
                    )
                    text = (
                        f"Shot {shot.number} in sequence {seq.number} ({seq.english_name}). "
                        f"{shot.setting}. Lens {shot.lens or 'standard'}, camera {shot.camera_movement or 'static'}, "
                        f"duration {shot.duration_sec}s. {shot.visual_description} "
                        f"Sound: {shot.sound}. Emotion: {shot.emotion_context}. {dialog_text}"
                    ).strip()
                    self.graph.add_node(shot_id, "shot", f"Shot {shot.number}: {shot.setting}", {
                        "act": act.number, "sequence": seq.number, "duration_sec": shot.duration_sec,
                        "emotion": shot.emotion_context, "lens": shot.lens,
                    })
                    self.graph.add_edge(seq_id, shot_id, "contains")
                    self._add_chunk("shot", text, {
                        "act": act.number,
                        "sequence": seq.number,
                        "shot": shot.number,
                        "emotion": shot.emotion_context,
                        "lens": shot.lens,
                        "node": shot_id,
                        "characters": [d.get("character", "") for d in shot.dialog],
                    })
                    for dialog in shot.dialog:
                        char_name = (dialog.get("character") or "").strip()
                        if char_name and char_name.lower() in character_nodes:
                            self.graph.add_edge(shot_id, character_nodes[char_name.lower()], "features")
                    if shot.music_cue:
                        for theme_name, theme_node in theme_nodes.items():
                            if theme_name and theme_name in shot.music_cue.lower():
                                self.graph.add_edge(shot_id, theme_node, "scored_by")

        # Music cues attach sequences to themes
        for cue in film.music_cues:
            seq_id = f"sequence:{cue.sequence_num}"
            for theme_name, theme_node in theme_nodes.items():
                if theme_name and theme_name in (cue.theme or "").lower():
                    self.graph.add_edge(seq_id, theme_node, "scored_by")

    def _add_chunk(self, kind: str, text: str, metadata: dict) -> None:
        node_id = metadata.get("node", "")
        chunk_id = f"{kind}:{stable_hash(text + node_id)[:12]}"
        self.chunks.append(Chunk(id=chunk_id, kind=kind, text=text, metadata=metadata))

    def _build_faiss(self) -> None:
        self._faiss_index = None
        if not FAISS_AVAILABLE or self._matrix is None or len(self.chunks) == 0:
            return
        try:
            index = faiss.IndexFlatIP(self._matrix.shape[1])
            index.add(self._matrix)
            self._faiss_index = index
        except Exception:
            self._faiss_index = None

    # ── persistence ──────────────────────────────────────────────────────
    def _persist(self) -> None:
        try:
            payload = [asdict(c) for c in self.chunks]
            (self.directory / "chunks.json").write_text(
                json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8"
            )
            (self.directory / "graph.json").write_text(
                json.dumps(self.graph.to_dict(), ensure_ascii=False, default=str), encoding="utf-8"
            )
            (self.directory / "meta.json").write_text(
                json.dumps(self.meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if NUMPY_AVAILABLE and self._matrix is not None:
                np.savez_compressed(self.directory / "vectors.npz", vectors=self._matrix)
        except Exception:
            pass

    def load(self, film: FilmScript, script_path: str = "") -> bool:
        fingerprint = _fingerprint(film, script_path)
        meta_file = self.directory / "meta.json"
        chunks_file = self.directory / "chunks.json"
        graph_file = self.directory / "graph.json"
        if not (meta_file.exists() and chunks_file.exists() and graph_file.exists()):
            return False
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            if meta.get("fingerprint") != fingerprint:
                return False
            raw_chunks = json.loads(chunks_file.read_text(encoding="utf-8"))
            self.chunks = [Chunk(**c) for c in raw_chunks]
            graph = json.loads(graph_file.read_text(encoding="utf-8"))
            self.graph = ScreenplayGraph()
            for node in graph.get("nodes", []):
                self.graph.nodes[node["id"]] = node
            for edge in graph.get("edges", []):
                self.graph.add_edge(edge["source"], edge["target"], edge["relation"])
            if NUMPY_AVAILABLE and (self.directory / "vectors.npz").exists():
                with np.load(self.directory / "vectors.npz") as data:
                    self._matrix = data["vectors"].astype("float32")
                self._build_faiss()
            self.fingerprint = fingerprint
            self.meta = meta
            return True
        except Exception:
            return False

    def ensure(self, film: FilmScript, script_path: str = "", force: bool = False) -> dict:
        with self._lock:
            if force or not self.load(film, script_path):
                return self.build(film, script_path)
            return self.stats()

    # ── search ───────────────────────────────────────────────────────────
    def search(
        self,
        query: str,
        k: int = 6,
        kind: Optional[str] = None,
        mode: str = "hybrid",
        expand_graph: bool = True,
    ) -> list[dict]:
        if not self.chunks:
            return []
        query_vec = self.embedder.embed(query)
        candidate_idx: list[int] = list(range(len(self.chunks)))
        if kind:
            candidate_idx = [i for i, c in enumerate(self.chunks) if c.kind == kind]
        if not candidate_idx:
            return []

        scores: dict[int, float] = {}
        if FAISS_AVAILABLE and self._faiss_index is not None and self._matrix is not None:
            kk = min(len(self.chunks), max(k * 4, 20))
            distances, indices = self._faiss_index.search(np.asarray([query_vec], dtype="float32"), kk)
            for score, idx in zip(distances[0], indices[0]):
                if idx >= 0 and (not kind or self.chunks[idx].kind == kind):
                    scores[int(idx)] = float(score)
            if not scores:
                scores = {i: self._cosine(query_vec, self.chunks[i].embedding or []) for i in candidate_idx}
        else:
            scores = {i: self._cosine(query_vec, self.chunks[i].embedding or []) for i in candidate_idx}

        ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)[: max(k * 2, k)]
        results = [
            (self.chunks[i].public(score), self.chunks[i]) for i, score in ranked
        ]

        if mode in {"graph", "hybrid"} and expand_graph and results:
            seed_nodes = {
                chunk.metadata.get("node"): score
                for pub, chunk in results
                if chunk.metadata.get("node")
            }
            for node_id, score in list(seed_nodes.items()):
                if not node_id:
                    continue
                for neighbor in self.graph.neighbors(node_id, hops=1):
                    for i, chunk in enumerate(self.chunks):
                        if chunk.metadata.get("node") == neighbor and not any(r[1].id == chunk.id for r in results):
                            results.append((chunk.public(score * 0.55), chunk))
                            scores[i] = score * 0.55
            if mode == "graph":
                # Graph-only retrieval keeps the neighbourhood and re-ranks by score
                results.sort(key=lambda pair: pair[0].get("score", 0), reverse=True)

        dedup: dict[str, dict] = {}
        for pub, _chunk in results:
            dedup.setdefault(pub["id"], pub)
        ordered = sorted(dedup.values(), key=lambda p: p.get("score", 0), reverse=True)[:k]
        return ordered

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if not a or not b:
            return 0.0
        return sum(x * y for x, y in zip(a, b))

    def ask(self, query: str, k: int = 6) -> dict:
        results = self.search(query, k=k, mode="hybrid")
        context = "\n\n".join(
            f"[{i + 1}] ({r['kind']}) {r['text']}" for i, r in enumerate(results)
        )
        prompt = (
            "You are a film-production research assistant. Answer the question using ONLY the "
            "screenplay context below. Cite sources as [n]. If the answer is not present, say so.\n\n"
            f"CONTEXT:\n{context}\n\nQUESTION: {query}\n\nANSWER:"
        )
        answer = provider_registry.llm.complete(
            prompt,
            system="You are precise, cite evidence, and never invent screenplay facts.",
            temperature=0.2,
            max_tokens=600,
        )
        return {
            "query": query,
            "answer": answer,
            "citations": results,
            "mode": "graphrag",
            "provider": provider_registry.llm.last_provider,
        }

    def stats(self) -> dict:
        kinds: dict[str, int] = {}
        for chunk in self.chunks:
            kinds[chunk.kind] = kinds.get(chunk.kind, 0) + 1
        return {
            **self.meta,
            "chunks": len(self.chunks),
            "kinds": kinds,
            "graph": self.graph.summary(),
            "embedding_backend": self.embedder.info()["backend"],
            "faiss": FAISS_AVAILABLE,
            "index_dir": str(self.directory),
        }

    def graph_payload(self, limit: int = 160) -> dict:
        nodes = list(self.graph.nodes.values())
        node_ids = {n["id"] for n in nodes[:limit]}
        edges = [e for e in self.graph.edges if e["source"] in node_ids and e["target"] in node_ids]
        return {"nodes": nodes[:limit], "edges": edges[: limit * 3], "summary": self.graph.summary()}


rag_engine = RAGEngine()
