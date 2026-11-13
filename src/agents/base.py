"""Base agent with provider access, artifact helpers, tool calling and events."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Iterable, Optional

from src.models.model_registry import ModelInfo, registry
from src.models.schemas import Act, AgentResult, AgentStatus, PipelineContext, Sequence, Shot
from src.utils.logger import get_logger


CATEGORY_MAP: dict[str, str] = {
    "script_agent": "llm",
    "storyboard_agent": "image",
    "character_agent": "llm",
    "voice_agent": "tts",
    "animation_agent": "video",
    "lipsync_agent": "lipsync",
    "render_agent": "video",
    "quality_agent": "llm",
}


class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name
        self.logger = get_logger(f"agent.{name}")
        self.model_category = CATEGORY_MAP.get(name, "llm")
        self.tools = [
            "screenplay_reader",
            "artifact_writer",
            "provider_router",
            "memory_write",
            "event_emit",
        ]

    # ── model selection ──────────────────────────────────────────────────
    def get_model(self, ctx: PipelineContext) -> Optional[ModelInfo]:
        model_id = ctx.model_selections.get(self.model_category)
        if model_id:
            return registry.get_model(model_id)
        default_id = registry.get_default_model_id(self.model_category)
        return registry.get_model(default_id) if default_id else None

    # ── runtime helpers ──────────────────────────────────────────────────
    @staticmethod
    def studio():
        from src.services import studio as _studio
        return _studio

    def run_dir(self, ctx: PipelineContext) -> str:
        return ctx.run_id or ctx.pipeline_id or "manual"

    def save_json(self, ctx: PipelineContext, filename: str, payload: Any) -> str:
        return self.studio().artifacts.save_json(f"{self.name}/{self.run_dir(ctx)}/{filename}", payload)

    def save_text(self, ctx: PipelineContext, filename: str, text: str) -> str:
        return self.studio().artifacts.save_text(f"{self.name}/{self.run_dir(ctx)}/{filename}", text)

    def artifact_url(self, path: str) -> str:
        try:
            return self.studio().artifacts.url(path)
        except ValueError:
            return ""

    def emit(self, ctx: PipelineContext, event: str, data: Optional[dict] = None) -> None:
        if not ctx.run_id:
            return
        try:
            self.studio().events.emit(ctx.run_id, event, {"agent": self.name, **(data or {})})
        except Exception:
            pass

    def llm(self, prompt: str, system: str = "", temperature: float = 0.35, max_tokens: int = 700) -> str:
        try:
            return self.studio().providers.llm.complete(prompt, system, temperature, max_tokens)
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.debug(f"LLM unavailable: {exc}")
            return ""

    def remember(self, text: str, key: str, tags: Optional[list[str]] = None, metadata: Optional[dict] = None) -> None:
        try:
            self.studio().memory.remember(
                text, scope="agent", key=key, tags=tags or [self.name], metadata=metadata or {}
            )
        except Exception:
            pass

    # ── shot iteration / scope ───────────────────────────────────────────
    def scoped_sequences(self, ctx: PipelineContext) -> list[tuple[Act, Sequence]]:
        if not ctx.film:
            return []
        sequences = [
            (act, seq)
            for act in ctx.film.acts
            for seq in act.sequences
        ]
        scope = ctx.scope
        if scope == "sample":
            limit = int(ctx.options.get("sample_sequences", 3))
            return sequences[:limit]
        if scope == "analysis":
            return sequences[: max(1, min(len(sequences), int(ctx.options.get("analysis_sequences", 2))))]
        return sequences

    def scoped_shots(self, ctx: PipelineContext) -> Iterable[tuple[Act, Sequence, Shot]]:
        for act, seq in self.scoped_sequences(ctx):
            for shot in seq.shots:
                yield act, seq, shot

    def all_shots(self, ctx: PipelineContext) -> list[tuple[Act, Sequence, Shot]]:
        if not ctx.film:
            return []
        return [
            (act, seq, shot)
            for act in ctx.film.acts
            for seq in act.sequences
            for shot in seq.shots
        ]

    def shot_limit(self, ctx: PipelineContext, total: int) -> int:
        if ctx.scope == "full":
            limit = int(ctx.options.get("max_shots", 0) or 0)
            return total if limit <= 0 else min(total, limit)
        if ctx.scope == "sample":
            return min(total, int(ctx.options.get("max_shots", 12) or 12))
        return min(total, int(ctx.options.get("max_shots", 6) or 6))

    # ── lifecycle ────────────────────────────────────────────────────────
    @abstractmethod
    def process(self, ctx: PipelineContext) -> AgentResult:
        ...

    def run(self, ctx: PipelineContext) -> AgentResult:
        model = self.get_model(ctx)
        model_str = f" using {model.name}" if model else ""
        self.logger.info(f"[{self.name}] Starting{model_str}")
        self.emit(ctx, "agent.log", {"message": f"starting{model_str}"})
        start = time.time()
        try:
            result = self.process(ctx)
            result.agent_name = self.name
            if result.status == AgentStatus.PENDING:
                result.status = AgentStatus.COMPLETED
            result.duration_sec = time.time() - start
            if result.status == AgentStatus.FAILED:
                ctx.errors.append(f"{self.name}: {result.error}")
                self.emit(ctx, "agent.error", {"error": result.error})
            else:
                self.emit(ctx, "agent.completed", {
                    "duration_sec": round(result.duration_sec, 3),
                    "model": model.name if model else "default",
                })
            self.logger.info(f"[{self.name}] {result.status.value} in {result.duration_sec:.2f}s")
            return result
        except Exception as exc:  # noqa: BLE001 - agent faults are isolated
            self.logger.exception(f"[{self.name}] Failed")
            ctx.errors.append(f"{self.name}: {exc}")
            self.emit(ctx, "agent.error", {"error": str(exc)})
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                error=str(exc),
                duration_sec=time.time() - start,
            )
