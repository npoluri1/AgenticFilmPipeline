
from src.models.schemas import FilmScript, Act, Sequence, Shot
from src.utils.logger import get_logger

logger = get_logger("script.enhancer")


class ScriptEnhancer:
    def enhance_for_human_clarity(self, film: FilmScript) -> FilmScript:
        logger.info("Enhancing script for human-like clarity...")
        for act in film.acts:
            for seq in act.sequences:
                seq.shots = [self._enhance_shot(s, seq, act) for s in seq.shots]
        return film

    def _enhance_shot(self, shot: Shot, seq: Sequence, act: Act) -> Shot:
        if not shot.visual_description:
            shot.visual_description = self._generate_visual(shot, seq)
        if not shot.dialog:
            shot.dialog = self._infer_dialog(shot, seq)
        if not shot.emotion_context:
            shot.emotion_context = self._infer_emotion(shot, seq, act)
        if not shot.camera_movement:
            shot.camera_movement = self._infer_camera(shot)
        return shot

    def _generate_visual(self, shot: Shot, seq: Sequence) -> str:
        descs = {
            "BLACK": "Complete darkness. Theatrical silence builds anticipation.",
            "CLOSE-UP": f"Intimate close-up revealing micro-expressions. Every subtle muscle movement tells the story of {seq.english_name.lower()}.",
            "WIDE": f" expansive wide frame captures the full scope. Characters exist within a vast {shot.setting.lower().replace('ext', 'exterior').replace('int', 'interior')}.",
            "DOLLY": "Camera glides smoothly through the space, pulling the audience deeper into the emotional landscape.",
            "CRANE": "God-view perspective. The camera ascends, revealing the cosmic scale of the moment.",
            "EXTREME": "Extreme close-up. Detail so fine you can see the character's soul through their eyes.",
        }
        for key, desc in descs.items():
            if key in shot.setting.upper():
                return desc
        return f"The camera captures {shot.setting.lower()} — a moment that feels both intimate and eternal."

    def _infer_dialog(self, shot: Shot, seq: Sequence) -> list[dict[str, str]]:
        if not shot.sound or "dialog" not in shot.sound.lower():
            return []
        return [{
            "character": "Narrator",
            "telugu": f"సన్నివేశం {seq.number} — {seq.english_name}",
            "english": f"Scene {seq.number} — {seq.english_name}",
            "emotion": "neutral",
        }]

    def _infer_emotion(self, shot: Shot, seq: Sequence, act: Act) -> str:
        text = f"{shot.setting} {shot.sound}".lower()
        if any(w in text for w in ["gunshot", "explosion", "shout", "anger", "war", "battle"]):
            return "intense_anger"
        if any(w in text for w in ["cry", "sad", "weep", "funeral", "death", "loss"]):
            return "deep_sadness"
        if any(w in text for w in ["laugh", "joy", "celebration", "love", "romance"]):
            return "pure_joy"
        if any(w in text for w in ["silence", "calm", "peace", "quiet", "still"]):
            return "serene_calm"
        if any(w in text for w in ["fear", "scared", "terrified", "horror"]):
            return "paralyzing_fear"
        return "contemplative_neutral"

    def _infer_camera(self, shot: Shot) -> str:
        setting = shot.setting.upper()
        if "CLOSE-UP" in setting or "ECU" in setting:
            return "Static camera. Shallow depth of field. Focus on eyes."
        if "WIDE" in setting or "GOD-VIEW" in setting:
            return "Slow pull-back. Deep focus. Symmetrical composition."
        if "DOLLY" in setting:
            return "Glacial dolly push. 10-second move. Unblinking."
        if "CRANE" in setting:
            return "Spiral crane ascent. 360-degree rotation. 50ft high."
        if "POV" in setting:
            return f"First-person POV. Slight handheld wobble. {shot.lens or '50mm'}."
        return "Medium shot. Slight tilt. Naturalistic blocking."


class Humanizer:
    def __init__(self):
        self.enhancer = ScriptEnhancer()

    def render_script_as_story(self, film: FilmScript) -> str:
        film = self.enhancer.enhance_for_human_clarity(film)
        lines = []
        lines.append(f"# {film.telugu_title} — {film.title}")
        lines.append(f"*{film.runtime_str}*")
        lines.append(f"**Languages:** {', '.join(film.languages)}")
        lines.append("")
        lines.append("---")

        total_shots = sum(len(s.shots) for a in film.acts for s in a.sequences)
        lines.append(f"**Total:** {len(film.acts)} Acts | {sum(len(a.sequences) for a in film.acts)} Sequences | {total_shots} Shots")
        lines.append("")

        for act in film.acts:
            lines.append("")
            lines.append(f"# ⚔️ ACT {self._to_roman(act.number)} — \"{act.english_subtitle}\"")
            lines.append("")
            for seq in act.sequences:
                lines.append(f"## 🎬 Sequence {seq.number}: {seq.english_name}")
                lines.append(f"**({seq.runtime_minutes} min)**")
                lines.append("")
                for shot in seq.shots:
                    emotion_icon = {
                        "intense_anger": "🔥", "deep_sadness": "💧", "pure_joy": "✨",
                        "serene_calm": "🌊", "paralyzing_fear": "😨", "contemplative_neutral": "🎭",
                    }.get(getattr(shot, 'emotion_context', ''), "🎬")
                    lines.append(f"### [{shot.number}] {emotion_icon} {shot.setting}")
                    if hasattr(shot, 'camera_movement') and shot.camera_movement:
                        lines.append(f"  *Camera:* {shot.camera_movement}")
                    if hasattr(shot, 'lens') and shot.lens:
                        lines.append(f"  *Lens:* {shot.lens}")
                    if shot.visual_description:
                        lines.append(f"  {shot.visual_description}")
                    if shot.sound:
                        lines.append(f"  🔊 *{shot.sound}*")
                    for d in shot.dialog:
                        lines.append(f"  **{d.get('character', 'Voice')}:** \"{d.get('telugu', '')}\"")
                        if d.get('english'):
                            lines.append(f"  *({d.get('english')})*")
                    lines.append(f"  ⏱ {shot.duration_sec}s")
                    lines.append("")
                lines.append("---")
                lines.append("")

        return "\n".join(lines)

    def _to_roman(self, n: int) -> str:
        vals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"),
                (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"),
                (5, "V"), (4, "IV"), (1, "I")]
        result = ""
        for value, symbol in vals:
            while n >= value:
                result += symbol
                n -= value
        return result
