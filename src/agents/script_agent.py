from src.agents.base import BaseAgent
from src.models.schemas import PipelineContext, AgentResult, ScriptOutput
from src.readers.ruthambhara_reader import RuthambharaReader


class ScriptAgent(BaseAgent):
    def __init__(self):
        super().__init__("script_agent")

    def process(self, ctx: PipelineContext) -> AgentResult:
        model = self.get_model(ctx)
        self.logger.info(f"Reading script [{model.name if model else 'default'}]: {ctx.source_script_path}")

        reader = RuthambharaReader()
        film = reader.read(ctx.source_script_path)

        ctx.film = film

        total_seq = sum(len(a.sequences) for a in film.acts)

        return AgentResult(
            agent_name=self.name,
            output=ScriptOutput(
                film=film,
                total_acts=len(film.acts),
                total_sequences=total_seq,
                language=ctx.language,
            ),
        )
