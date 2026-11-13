"""LLM/pipeline evaluation, rubric scoring and fine-tuning data export.

Evaluations are recorded as append-only JSONL so they can feed MLOps dashboards,
regression gates and LoRA/QLoRA fine-tuning datasets without extra services.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.config import EVALS_DIR

RUBRIC = {
    "artifact_completeness": "Every stage produced its promised artifact",
    "quality_score": "Mean production rubric score from the quality gate",
    "agent_reliability": "Share of agents that completed without error",
    "structural_fidelity": "Parsed acts/sequences/shots match the screenplay",
    "guardrail_safety": "Guardrail score for the supplied inputs",
    "latency_efficiency": "Wall-clock efficiency against a 300s MVP budget",
}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class EvalStore:
    def __init__(self, directory: Path = EVALS_DIR):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "evals.jsonl"
        self._lock = threading.Lock()

    def record(self, name: str, payload: dict[str, Any], tags: Optional[list[str]] = None) -> dict:
        entry = {
            "id": f"eval_{int(datetime.now().timestamp() * 1000)}_{abs(hash(name)) % 10000}",
            "name": name,
            "created_at": _ts(),
            "tags": tags or [],
            "payload": payload,
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        return entry

    def list(self, limit: int = 50) -> list[dict]:
        if not self.path.exists():
            return []
        entries: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(entries))[-limit:][::-1]

    def summary(self) -> dict:
        entries = self.list(1000)
        by_name: dict[str, int] = {}
        scores: list[float] = []
        for entry in entries:
            by_name[entry["name"]] = by_name.get(entry["name"], 0) + 1
            score = (entry.get("payload") or {}).get("scores", {}).get("overall")
            if isinstance(score, (int, float)):
                scores.append(float(score))
        return {
            "total": len(entries),
            "by_name": by_name,
            "mean_overall": round(sum(scores) / len(scores), 3) if scores else 0.0,
            "path": str(self.path),
        }

    def export_finetune(self, name: str = "ruthambhara_finetune.jsonl") -> dict:
        """Export instruction/response pairs suitable for LoRA/QLoRA training."""
        target = self.directory / name
        count = 0
        with self._lock, target.open("w", encoding="utf-8") as handle:
            for entry in self.list(1000):
                payload = entry.get("payload") or {}
                conversation = payload.get("finetune")
                if not conversation:
                    continue
                handle.write(json.dumps(conversation, ensure_ascii=False, default=str) + "\n")
                count += 1
        return {"path": str(target), "pairs": count, "format": "jsonl"}


class PipelineEvaluator:
    """Deterministic evaluator for an end-to-end pipeline run."""

    def __init__(self, store: Optional[EvalStore] = None):
        self.store = store or EvalStore()

    def evaluate(self, ctx, graph_result=None) -> dict:
        film = ctx.film
        results = list((graph_result.results if graph_result else ctx.results.values()) or [])
        completed = sum(1 for r in results if getattr(r.status, "value", r.status) == "completed")
        reliability = completed / max(1, len(results))

        expected = ["script", "storyboard", "characters", "voice", "animation", "lipsync", "render", "quality"]
        present = [key for key in expected if ctx.artifacts.get(key)]
        completeness = len(present) / len(expected)

        reports = ctx.quality_reports or []
        quality = round(sum(r.overall_score for r in reports) / max(1, len(reports)), 3)

        structural = 1.0
        if film:
            checks = [
                len(film.acts) >= 1,
                sum(len(a.sequences) for a in film.acts) >= 1,
                sum(len(s.shots) for a in film.acts for s in a.sequences) >= 1,
                bool(film.cast),
            ]
            structural = sum(1 for c in checks if c) / len(checks)

        elapsed = sum(getattr(r, "duration_sec", 0) for r in results)
        latency = max(0.0, min(1.0, 1.0 - elapsed / 300.0)) if elapsed else 0.0
        guardrail = float(ctx.options.get("guardrail_score", 1.0) or 1.0)

        scores = {
            "artifact_completeness": round(completeness, 3),
            "quality_score": quality,
            "agent_reliability": round(reliability, 3),
            "structural_fidelity": round(structural, 3),
            "guardrail_safety": round(guardrail, 3),
            "latency_efficiency": round(latency, 3),
        }
        weights = {
            "artifact_completeness": 0.22,
            "quality_score": 0.24,
            "agent_reliability": 0.18,
            "structural_fidelity": 0.14,
            "guardrail_safety": 0.10,
            "latency_efficiency": 0.12,
        }
        overall = round(sum(scores[key] * weights[key] for key in scores), 3)
        passed = overall >= 0.75 and reliability >= 0.875 and completeness >= 0.75

        payload = {
            "run_id": ctx.run_id,
            "film": film.title if film else "",
            "scope": ctx.scope,
            "scores": scores,
            "weights": weights,
            "overall": overall,
            "passed": passed,
            "rubric": RUBRIC,
            "finetune": {
                "messages": [
                    {"role": "system", "content": "You are the RUTHAMBHARA agentic film-production planner."},
                    {
                        "role": "user",
                        "content": (
                            f"Plan the production pipeline for {film.title if film else 'a feature film'} "
                            f"at scope={ctx.scope}, language={ctx.language}."
                        ),
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "agents": [getattr(r, "agent_name", "unknown") for r in results],
                                "artifacts": {k: v for k, v in ctx.artifacts.items()},
                                "quality": {"mean": quality, "passed": passed},
                            },
                            ensure_ascii=False,
                        ),
                    },
                ]
            },
        }
        payload["eval_id"] = self.store.record("pipeline_run", payload, tags=["pipeline", ctx.scope])["id"]
        return payload
