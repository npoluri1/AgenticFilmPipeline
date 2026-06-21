from src.agents.base import BaseAgent
from src.models.schemas import PipelineContext, AgentResult, RenderOutput


class RenderAgent(BaseAgent):
    def __init__(self):
        super().__init__("render_agent")

    def process(self, ctx: PipelineContext) -> AgentResult:
        model = self.get_model(ctx)
        self.logger.info(f"Rendering final output [{model.name if model else 'default'}]")

        renders = []
        if not ctx.film:
            return AgentResult(agent_name=self.name, output=[])

        resolutions = {
            "theatrical": "4096x1716",
            "digital": "1920x1080",
        }

        for act in ctx.film.acts:
            for seq in act.sequences:
                for shot in seq.shots:
                    renders.append(RenderOutput(
                        sequence_num=seq.number,
                        shot_number=shot.number,
                        final_path=f"output/ruthambhara/final/seq{seq.number:03d}_{shot.number}_final.mp4",
                        resolution=resolutions["theatrical"],
                        bitrate_mbps=24,
                    ))

        self.logger.info(f"Generated {len(renders)} render outputs")
        return AgentResult(agent_name=self.name, output=renders)
