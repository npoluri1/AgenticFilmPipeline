from src.agents.base import BaseAgent
from src.models.schemas import PipelineContext, AgentResult, CharacterProfile, CharacterOutput


class CharacterAgent(BaseAgent):
    def __init__(self):
        super().__init__("character_agent")

    def process(self, ctx: PipelineContext) -> AgentResult:
        model = self.get_model(ctx)
        self.logger.info(f"Building character profiles [{model.name if model else 'default'}]")

        profiles = []
        if not ctx.film:
            return AgentResult(agent_name=self.name, output=CharacterOutput(characters=[]))

        for member in ctx.film.cast:
            name = member.role.split("(")[0].strip()
            profiles.append(CharacterProfile(
                name=name,
                actor=member.actor,
                function=member.function,
                voice_id=f"voice_{name.lower().replace(' ', '_')}",
                face_embedding_path=f"models/ruthambhara/faces/{name.lower().replace(' ', '_')}.bin",
                emotion_palette={
                    "anger": f"ruthambhara/{name.lower().replace(' ', '_')}_anger.png",
                    "sadness": f"ruthambhara/{name.lower().replace(' ', '_')}_sad.png",
                    "joy": f"ruthambhara/{name.lower().replace(' ', '_')}_joy.png",
                    "fear": f"ruthambhara/{name.lower().replace(' ', '_')}_fear.png",
                    "neutral": f"ruthambhara/{name.lower().replace(' ', '_')}_neutral.png",
                },
                languages=ctx.film.languages,
            ))

        self.logger.info(f"Built {len(profiles)} character profiles for {ctx.film.title}")
        return AgentResult(
            agent_name=self.name,
            output=CharacterOutput(characters=profiles),
        )
