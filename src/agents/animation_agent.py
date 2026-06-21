from src.agents.base import BaseAgent
from src.models.schemas import PipelineContext, AgentResult, AnimationOutput


class AnimationAgent(BaseAgent):
    def __init__(self):
        super().__init__("animation_agent")

    def process(self, ctx: PipelineContext) -> AgentResult:
        model = self.get_model(ctx)
        self.logger.info(f"Generating animations [{model.name if model else 'default'}]")

        animations = []
        if not ctx.film:
            return AgentResult(agent_name=self.name, output=[])

        for act in ctx.film.acts:
            for seq in act.sequences:
                for shot in seq.shots:
                    animations.append(AnimationOutput(
                        sequence_num=seq.number,
                        shot_number=shot.number,
                        video_path=f"output/ruthambhara/animation/seq{seq.number:03d}_{shot.number}.mp4",
                        frame_count=int(shot.duration_sec * 24),
                        fps=24,
                        duration_sec=shot.duration_sec,
                    ))

        self.logger.info(f"Generated {len(animations)} animation segments")
        return AgentResult(agent_name=self.name, output=animations)
