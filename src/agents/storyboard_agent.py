from src.agents.base import BaseAgent
from src.models.schemas import PipelineContext, AgentResult, StoryboardOutput, StoryboardFrame


class StoryboardAgent(BaseAgent):
    def __init__(self):
        super().__init__("storyboard_agent")

    def process(self, ctx: PipelineContext) -> AgentResult:
        model = self.get_model(ctx)
        self.logger.info(f"Generating storyboard [{model.name if model else 'default'}]")

        frames = []
        if not ctx.film:
            return AgentResult(agent_name=self.name, output=StoryboardOutput(frames=[], total_shots=0))

        frame_num = 0
        for act in ctx.film.acts:
            for seq in act.sequences:
                for shot in seq.shots:
                    frame_num += 1
                    angle = self._detect_angle(shot.setting, shot.lens)
                    frames.append(StoryboardFrame(
                        sequence_num=seq.number,
                        shot_number=shot.number,
                        frame_number=frame_num,
                        description=shot.visual_description or shot.setting,
                        camera_angle=angle,
                        lens=shot.lens,
                        composition_notes=f"Duration: {shot.duration_sec}s, Sound: {shot.sound[:60] if shot.sound else 'dialog'}",
                        duration_sec=shot.duration_sec,
                    ))

        self.logger.info(f"Generated {len(frames)} storyboard frames")
        return AgentResult(
            agent_name=self.name,
            output=StoryboardOutput(frames=frames, total_shots=len(frames)),
        )

    def _detect_angle(self, setting: str, lens: str) -> str:
        if "EXTREME CLOSE-UP" in setting or "ECU" in setting:
            return "extreme close-up"
        if "CLOSE-UP" in setting or "CU" in setting:
            return "close-up"
        if "GOD-VIEW" in setting or "bird" in setting.lower():
            return "bird's eye"
        if "WIDE" in setting or "wide" in lens.lower():
            return "wide"
        if "DOLLY" in setting:
            return "dolly"
        if "CRANE" in setting:
            return "crane"
        return "medium"
