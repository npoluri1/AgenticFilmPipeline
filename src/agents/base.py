from abc import ABC, abstractmethod
from typing import Optional

from src.models.model_registry import ModelInfo, registry
from src.models.schemas import PipelineContext, AgentResult, AgentStatus
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

    def get_model(self, ctx: PipelineContext) -> Optional[ModelInfo]:
        model_id = ctx.model_selections.get(self.model_category)
        if model_id:
            return registry.get_model(model_id)
        default_id = registry.get_default_model_id(self.model_category)
        return registry.get_model(default_id) if default_id else None

    @abstractmethod
    def process(self, ctx: PipelineContext) -> AgentResult:
        ...

    def run(self, ctx: PipelineContext) -> AgentResult:
        import time
        model = self.get_model(ctx)
        model_str = f" using {model.name}" if model else ""
        self.logger.info(f"[{self.name}] Starting{model_str}")
        start = time.time()
        try:
            result = self.process(ctx)
            result.agent_name = self.name
            result.status = AgentStatus.COMPLETED
            result.duration_sec = time.time() - start
            self.logger.info(f"[{self.name}] Completed in {result.duration_sec:.2f}s")
            return result
        except Exception as e:
            self.logger.error(f"[{self.name}] Failed: {e}")
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                error=str(e),
                duration_sec=time.time() - start,
            )
