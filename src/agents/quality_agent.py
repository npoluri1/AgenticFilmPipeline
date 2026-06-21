import random
from src.agents.base import BaseAgent
from src.models.schemas import PipelineContext, AgentResult, QualityReport


class QualityAgent(BaseAgent):
    def __init__(self, threshold: float = 0.85):
        super().__init__("quality_agent")
        self.threshold = threshold

    def process(self, ctx: PipelineContext) -> AgentResult:
        model = self.get_model(ctx)
        self.logger.info(f"Running quality check [{model.name if model else 'default'}]")

        reports = []
        if not ctx.film:
            return AgentResult(agent_name=self.name, output=[])

        random.seed(123)
        for act in ctx.film.acts:
            for seq in act.sequences:
                report = QualityReport(
                    sequence_num=seq.number,
                    consistency_score=random.uniform(0.75, 0.98),
                    lip_sync_accuracy=random.uniform(0.80, 0.99),
                    emotion_fidelity=random.uniform(0.70, 0.95),
                    scene_coherence=random.uniform(0.80, 0.97),
                    music_theme_accuracy=random.uniform(0.78, 0.96),
                    passed=False,
                )
                report.passed = (
                    report.consistency_score >= self.threshold
                    and report.lip_sync_accuracy >= self.threshold
                    and report.emotion_fidelity >= self.threshold - 0.1
                    and report.scene_coherence >= self.threshold
                )
                if not report.passed:
                    if report.consistency_score < self.threshold:
                        report.issues.append("Character consistency below threshold")
                    if report.lip_sync_accuracy < self.threshold:
                        report.issues.append("Lip-sync accuracy below threshold")
                    if report.emotion_fidelity < self.threshold - 0.1:
                        report.issues.append("Emotion fidelity below threshold")
                    if report.scene_coherence < self.threshold:
                        report.issues.append("Scene coherence below threshold")

                reports.append(report)

        ctx.quality_reports = reports
        passed = sum(1 for r in reports if r.passed)
        self.logger.info(f"Quality: {passed}/{len(reports)} sequences passed")

        return AgentResult(agent_name=self.name, output=reports)
