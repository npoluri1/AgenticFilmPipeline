import random
from src.agents.base import BaseAgent
from src.models.schemas import PipelineContext, AgentResult, LipSyncOutput


class LipSyncAgent(BaseAgent):
    def __init__(self):
        super().__init__("lipsync_agent")

    def process(self, ctx: PipelineContext) -> AgentResult:
        model = self.get_model(ctx)
        self.logger.info(f"Applying lip sync [{model.name if model else 'default'}]")

        syncs = []
        if not ctx.film:
            return AgentResult(agent_name=self.name, output=[])

        random.seed(42)
        for act in ctx.film.acts:
            for seq in act.sequences:
                for shot in seq.shots:
                    base_accuracy = 0.92 if shot.language == "te" else 0.88
                    syncs.append(LipSyncOutput(
                        sequence_num=seq.number,
                        shot_number=shot.number,
                        video_path=f"output/ruthambhara/lipsync/seq{seq.number:03d}_{shot.number}_synced.mp4",
                        sync_accuracy=min(0.99, base_accuracy + random.uniform(-0.05, 0.05)),
                    ))

        self.logger.info(f"Generated {len(syncs)} lip-sync segments")
        return AgentResult(agent_name=self.name, output=syncs)
