from src.agents.base import BaseAgent
from src.models.schemas import PipelineContext, AgentResult, VoiceLine, VoiceOutput


class VoiceAgent(BaseAgent):
    def __init__(self):
        super().__init__("voice_agent")

    def process(self, ctx: PipelineContext) -> AgentResult:
        model = self.get_model(ctx)
        self.logger.info(f"Generating voice lines [{model.name if model else 'default'}]")

        lines = []
        if not ctx.film:
            return AgentResult(agent_name=self.name, output=VoiceOutput(lines=[], total_lines=0))

        character_names = {m.role.split("(")[0].strip(): m.actor for m in ctx.film.cast}

        for act in ctx.film.acts:
            for seq in act.sequences:
                for shot in seq.shots:
                    for dialog in shot.dialog:
                        char_name = dialog.get("character", "Narrator")
                        lines.append(VoiceLine(
                            character=char_name,
                            actor=character_names.get(char_name, "Unknown"),
                            dialog=dialog.get("telugu", ""),
                            dialog_english=dialog.get("english", ""),
                            emotion=self._detect_emotion(shot.sound, dialog.get("telugu", "")),
                            language=shot.language,
                            shot_number=shot.number,
                            sequence_num=seq.number,
                            audio_path=f"output/ruthambhara/audio/seq{seq.number:03d}_{shot.number}_{char_name}.wav",
                            duration_sec=shot.duration_sec * 0.6,
                        ))

        self.logger.info(f"Generated {len(lines)} voice lines")
        return AgentResult(
            agent_name=self.name,
            output=VoiceOutput(lines=lines, total_lines=len(lines)),
        )

    def _detect_emotion(self, sound: str, dialog: str) -> str:
        text = (sound + " " + dialog).lower()
        if any(w in text for w in ["shout", "yell", "furious", "anger", "angry", "కోపం"]):
            return "anger"
        if any(w in text for w in ["cry", "sad", "weep", "mourn", "sorrow", "విచారం"]):
            return "sadness"
        if any(w in text for w in ["laugh", "smile", "happy", "celebrate", "joy", "ఆనందం"]):
            return "joy"
        if any(w in text for w in ["scared", "fear", "terrified", "panic", "భయం"]):
            return "fear"
        if any(w in text for w in ["whisper", "calm", "steady", "gentle", "soft"]):
            return "calm"
        return "neutral"
