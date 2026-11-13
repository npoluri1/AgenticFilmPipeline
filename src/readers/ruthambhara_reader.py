"""Screenplay reader for the RUTHAMBHARA Markdown format + generic fallback.

The reader extracts a fully structured ``FilmScript``: acts, sequences, shots,
lens, camera movement, visual description, sound design, dialogue (Telugu +
English), music cues, cast and themes.
"""
from __future__ import annotations

import re
from pathlib import Path

from src.models.schemas import (
    Act,
    CastMember,
    FilmScript,
    MusicCue,
    MusicTheme,
    Sequence,
    Shot,
)
from src.utils.logger import get_logger

logger = get_logger("reader.ruthambhara")

_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_LANG_MAP = {
    "తెలుగు": "te", "telugu": "te",
    "Tamil": "ta", "తమిళం": "ta",
    "Hindi": "hi", "హిందీ": "hi",
    "Malayalam": "ml", "మలయాళం": "ml",
    "Kannada": "kn", "కన్నడ": "kn",
    "English": "en",
}

_EMOTION_RULES = [
    (("gunshot", "explosion", "shout", "yell", "furious", "anger", "war", "battle", "blood", "kill", "burn"), "intense_anger"),
    (("cry", "sad", "weep", "mourn", "sorrow", "death", "loss", "funeral", "tears"), "deep_sadness"),
    (("laugh", "smile", "happy", "celebrate", "joy", "festival", "wedding", "dance"), "pure_joy"),
    (("scared", "fear", "terrified", "panic", "horror", "nightmare"), "paralyzing_fear"),
    (("silence", "calm", "peace", "quiet", "still", "meditat", "temple", "prayer"), "serene_calm"),
    (("mystery", "shadow", "whisper", "secret", "hidden", "suspense"), "suspense"),
]


def _roman_to_int(s: str) -> int:
    result = 0
    for i, c in enumerate(s.upper()):
        value = _ROMAN.get(c, 0)
        if i + 1 < len(s) and _ROMAN.get(s[i + 1].upper(), 0) > value:
            result -= value
        else:
            result += value
    return result


def _detect_emotion(*parts: str) -> str:
    text = " ".join(parts).lower()
    for keywords, emotion in _EMOTION_RULES:
        if any(k in text for k in keywords):
            return emotion
    return "contemplative_neutral"


def _detect_camera(setting: str, lens: str, description: str = "") -> str:
    text = f"{setting} {description}".upper()
    if "ECU" in text or "EXTREME CLOSE" in text:
        return "Static. Shallow depth of field. Micro-expression focus."
    if "CLOSE-UP" in text or "CLOSE UP" in text:
        return "Slow push-in. Shallow depth of field."
    if "GOD-VIEW" in text or "AERIAL" in text or "DRONE" in text:
        return "Aerial spiral / god-view. 360° reveal."
    if "CRANE" in text:
        return "Crane ascent. Vertical reveal."
    if "DOLLY" in text or "PULL-BACK" in text or "PULL BACK" in text:
        return "Dolly move. Glacial parallax."
    if "WIDE" in text:
        return "Wide establishing frame. Deep focus."
    if "POV" in text:
        return "First-person POV. Slight handheld movement."
    if "HANDHELD" in text:
        return "Handheld. Controlled instability."
    return "Medium shot. Naturalistic blocking."


class RuthambharaReader:
    """Parses the feature screenplay into structured production data."""

    def read(self, path: str) -> FilmScript:
        text = Path(path).read_text(encoding="utf-8")
        lines = text.splitlines()

        film = self._parse_header(lines)
        film.cast = self._parse_cast(lines)
        film.music_themes = self._parse_music_themes(lines)
        film.music_cues = self._parse_music_cues(lines)
        film.acts = self._parse_acts(lines)

        if not film.acts:
            # Generic screenplay fallback (SCENE 1 — INT. … format)
            film.acts = self._parse_generic(lines)

        total_seq = sum(len(a.sequences) for a in film.acts)
        total_shots = sum(len(s.shots) for a in film.acts for s in a.sequences)
        logger.info(
            f"Parsed {len(film.acts)} acts, {total_seq} sequences, {total_shots} shots, "
            f"{len(film.cast)} cast, {len(film.music_themes)} themes"
        )
        return film

    # ── header ───────────────────────────────────────────────────────────
    def _parse_header(self, lines: list[str]) -> FilmScript:
        runtime_line = next((line for line in lines if "రన్‌టైమ్" in line or "Runtime" in line), "")
        lang_line = next((line for line in lines if "భాష" in line or "language" in line.lower()), "")
        aspect_line = next((line for line in lines if "ఆస్పెక్ట్" in line or "aspect" in line.lower()), "")

        runtime_match = re.search(
            r"(\d+)\s*(?:గంటల|hours?)\s*(?:\s+(\d+)\s*(?:నిమిషాలు|minutes?))?", runtime_line
        )
        hours = int(runtime_match.group(1)) if runtime_match else 3
        minutes = int(runtime_match.group(2)) if runtime_match and runtime_match.group(2) else 25
        total_minutes = hours * 60 + minutes

        langs: list[str] = []
        search_area = lang_line or " ".join(lines[:12])
        for name, code in _LANG_MAP.items():
            if name in search_area and code not in langs:
                langs.append(code)
        if not langs:
            langs = ["te"]

        title = "RUTHAMBHARA"
        telugu_title = "ఋతంభర"
        for line in lines[:8]:
            if "RUTHAMBHARA" in line.upper():
                title = "RUTHAMBHARA"
                if "—" in line:
                    telugu_title = line.split("—")[0].strip("# ").strip()
                break

        aspect = "2.39:1"
        aspect_match = re.search(r"(\d+\.\d+:\d+)", aspect_line)
        if aspect_match:
            aspect = aspect_match.group(1)

        return FilmScript(
            title=title,
            telugu_title=telugu_title,
            runtime_str=runtime_line.strip() or f"{hours} hours {minutes} minutes",
            runtime_minutes=float(total_minutes),
            languages=langs,
            aspect_ratio=aspect,
        )

    # ── cast ─────────────────────────────────────────────────────────────
    def _parse_cast(self, lines: list[str]) -> list[CastMember]:
        cast: list[CastMember] = []
        in_cast = False
        for line in lines:
            stripped = line.strip()
            if "PAN-INDIA CAST" in line or stripped.upper() == "## CAST":
                in_cast = True
                continue
            if in_cast and stripped.startswith("##") and "CAST" not in stripped.upper():
                break
            if not in_cast or not stripped.startswith("|"):
                continue
            if "Role" in stripped or set(stripped.replace("|", "").strip()) <= {"-", ":", " "}:
                continue
            parts = [p.strip() for p in stripped.split("|")[1:-1]]
            if len(parts) >= 3:
                role = re.sub(r"\*\*(.+?)\*\*", r"\1", parts[0]).strip()
                actor = re.sub(r"\*\*(.+?)\*\*", r"\1", parts[1]).strip()
                if role and actor and role.lower() != "role":
                    cast.append(CastMember(role=role, actor=actor, function=parts[2]))
        return cast

    # ── music ────────────────────────────────────────────────────────────
    def _parse_music_themes(self, lines: list[str]) -> list[MusicTheme]:
        themes: list[MusicTheme] = []
        for line in lines:
            match = re.match(
                r"###\s*Theme\s+\d+\s*[—–-]\s*\"?([^\"]+?)\"?\s*\(([^)]+)\)\s*[—–-]\s*(.+)",
                line,
            )
            if match:
                themes.append(MusicTheme(
                    telugu_name=match.group(1).strip(),
                    name=match.group(2).strip(),
                    description=match.group(3).strip(),
                    instruments="",
                    inspiration="",
                    usage_rule="",
                ))
                continue
            if not themes:
                continue
            if "Instruments:" in line:
                themes[-1].instruments = line.split("Instruments:", 1)[1].strip()
            elif "Inspired by:" in line:
                themes[-1].inspiration = line.split("Inspired by:", 1)[1].strip()
            elif "Plays:" in line or "Usage:" in line:
                themes[-1].usage_rule = line.split(":", 1)[1].strip()
        return themes

    def _parse_music_cues(self, lines: list[str]) -> list[MusicCue]:
        cues: list[MusicCue] = []
        in_cues = False
        for line in lines:
            stripped = line.strip()
            if "MUSIC CUE SHEET" in line.upper():
                in_cues = True
                continue
            if in_cues and stripped.startswith("##") and "CUE" not in stripped.upper():
                break
            if not in_cues or not stripped.startswith("|"):
                continue
            if "Seq" in stripped or set(stripped.replace("|", "").strip()) <= {"-", ":", " "}:
                continue
            parts = [p.strip() for p in stripped.split("|")[1:-1]]
            if len(parts) >= 4:
                seq_match = re.search(r"\d+", parts[0])
                cues.append(MusicCue(
                    sequence_num=int(seq_match.group()) if seq_match else 0,
                    entry_time=parts[1] if len(parts) > 1 else "",
                    duration=parts[2] if len(parts) > 2 else "",
                    theme=parts[3] if len(parts) > 3 else "",
                    instruments=parts[4] if len(parts) > 4 else "",
                    scene_description=parts[5] if len(parts) > 5 else "",
                ))
        return cues

    # ── acts / sequences / shots ─────────────────────────────────────────
    def _parse_acts(self, lines: list[str]) -> list[Act]:
        acts: list[Act] = []
        current_act: Act | None = None
        current_sequence: Sequence | None = None
        i = 0

        while i < len(lines):
            line = lines[i]

            act_match = re.match(r"#\s*[^\w\s]*\s*ACT\s+([IVXLCDM]+)\s*[—–-]\s*\"(.+?)\"\s*\((.+?)\)", line)
            if act_match:
                if current_act is not None:
                    if current_sequence is not None:
                        current_act.sequences.append(current_sequence)
                    acts.append(current_act)
                runtime = re.search(r"(\d+:\d+)\s*[—–-]\s*(\d+:\d+)", line)
                current_act = Act(
                    number=_roman_to_int(act_match.group(1)),
                    english_subtitle=act_match.group(2).strip(),
                    telugu_subtitle=act_match.group(3).strip(),
                    start_time=runtime.group(1) if runtime else "",
                    end_time=runtime.group(2) if runtime else "",
                )
                current_sequence = None
                i += 1
                continue

            seq_match = re.match(r"##\s*SEQUENCE\s+(\d+)\s*[—–-]\s*\"(.+?)\"", line)
            if seq_match and current_act is not None:
                if current_sequence is not None:
                    current_act.sequences.append(current_sequence)

                runtime = 5.0
                runtime_match = re.search(r"(\d+)\s*నిమిషాలు", line)
                if not runtime_match and i + 1 < len(lines):
                    runtime_match = re.search(r"(\d+)\s*నిమిషాలు", lines[i + 1])
                if runtime_match:
                    runtime = float(runtime_match.group(1))

                english_name = seq_match.group(2).strip()
                telugu_name = ""
                # Some sequence headers are `SEQUENCE 1 — "తెలుగు" (ENGLISH TITLE)`.
                paren_match = re.search(r"\(([^)]+)\)", line)
                if paren_match:
                    candidate = paren_match.group(1).strip()
                    if re.search(r"[\u0C00-\u0C7F]", english_name) and not re.search(r"[\u0C00-\u0C7F]", candidate):
                        telugu_name = english_name
                        english_name = candidate

                current_sequence = Sequence(
                    number=int(seq_match.group(1)),
                    telugu_name=telugu_name,
                    english_name=english_name,
                    runtime_minutes=runtime,
                )

                j = i + 1
                block: list[str] = []
                while j < len(lines):
                    nxt = lines[j]
                    if re.match(r"##\s*SEQUENCE\s+\d+", nxt) or re.match(r"#\s*[^\w\s]*\s*ACT\s+", nxt):
                        break
                    block.append(nxt)
                    j += 1
                current_sequence.shots = self._parse_shot_block(block, current_sequence.number)
                i = j
                continue

            end_match = re.match(r"#\s*[^\w\s]*\s*END OF ACT", line)
            if end_match and current_act is not None:
                if current_sequence is not None:
                    current_act.sequences.append(current_sequence)
                acts.append(current_act)
                current_act = None
                current_sequence = None
            i += 1

        if current_act is not None:
            if current_sequence is not None:
                current_act.sequences.append(current_sequence)
            acts.append(current_act)

        # De-duplicate acts that were appended twice by END OF ACT + EOF.
        deduped: list[Act] = []
        seen: set[int] = set()
        for act in acts:
            if act.number in seen:
                continue
            seen.add(act.number)
            deduped.append(act)
        return deduped

    _SHOT_HEADER = re.compile(
        r"^\s*\*{0,2}\[(\d+(?:\.\d+)?)\]\s*(.+?)\*{0,2}\s*(?:\((\d+(?:\.\d+)?)\s*s\))?\s*$"
    )
    _CHARACTER_LINE = re.compile(r"^\s*\*{1,2}([A-Z][A-Z0-9 .'’\-]{2,40})\*{1,2}\s*(?:\(([^)]*)\))?\s*$")
    _INLINE_DIALOG = re.compile(r"^\s*\*{1,2}([A-Z][A-Z0-9 .'’\-]{1,40}):\*{1,2}\s*(.+)$")
    _LENS_LINE = re.compile(r"^\s*\*{0,2}Lens:?\*{0,2}\s*(.+)$", re.IGNORECASE)
    _SOUND_LINE = re.compile(
        r"^\s*\*{1,2}(SOUND ONLY|SOUND DESIGN|SOUND|MUSIC)\*{0,2}:?\*{0,2}\s*(.*)$",
        re.IGNORECASE,
    )

    def _parse_shot_block(self, lines: list[str], seq_num: int) -> list[Shot]:
        shots: list[Shot] = []
        current: Shot | None = None
        last_dialog: dict | None = None

        for raw in lines:
            line = raw.rstrip()
            stripped = line.strip()
            if not stripped or stripped == "---":
                continue

            header = self._SHOT_HEADER.match(stripped)
            if header:
                if current is not None:
                    shots.append(current)
                setting = re.sub(r"\*+", "", header.group(2)).strip()
                duration = float(header.group(3)) if header.group(3) else 5.0
                current = Shot(
                    number=header.group(1),
                    setting=setting,
                    duration_sec=duration,
                    lens="",
                    camera_movement="",
                    visual_description="",
                    dialog=[],
                    sound="",
                    language="te",
                    emotion_context=_detect_emotion(setting),
                )
                last_dialog = None
                continue
            if current is None:
                continue

            lens_match = self._LENS_LINE.match(stripped)
            if lens_match:
                current.lens = lens_match.group(1).strip()
                continue

            sound_match = self._SOUND_LINE.match(stripped)
            if sound_match:
                kind = sound_match.group(1).upper()
                sound_text = sound_match.group(2).strip().strip("*").strip()
                current.sound = (current.sound + " " + sound_text).strip()
                if kind == "MUSIC":
                    current.music_cue = sound_text
                last_dialog = None
                continue

            inline = self._INLINE_DIALOG.match(stripped)
            if inline and not stripped.startswith(("**Camera", "**MUSIC", "**SOUND", "**Lens", "**Runtime")):
                character = inline.group(1).strip()
                remainder = inline.group(2).strip().strip("*").strip()
                telugu, english = "", ""
                quotes = re.findall(r'"([^"]*)"', remainder)
                if quotes:
                    telugu = quotes[0]
                    english = quotes[1] if len(quotes) > 1 else ""
                else:
                    telugu = remainder
                last_dialog = {"character": character, "direction": "", "telugu": telugu, "english": english, "emotion": ""}
                current.dialog.append(last_dialog)
                continue

            char_match = self._CHARACTER_LINE.match(stripped)
            if char_match and not stripped.startswith(("**Camera", "**MUSIC", "**SOUND", "**Lens", "**Runtime")):
                character = char_match.group(1).strip()
                direction = (char_match.group(2) or "").strip()
                last_dialog = {"character": character, "direction": direction, "telugu": "", "english": "", "emotion": ""}
                current.dialog.append(last_dialog)
                continue

            if stripped.startswith('"'):
                quoted = self._extract_quote(stripped)
                if last_dialog is not None:
                    if last_dialog.get("telugu"):
                        last_dialog["english"] = quoted
                    else:
                        last_dialog["telugu"] = quoted
                else:
                    current.sound = (current.sound + " " + quoted).strip()
                continue
            if stripped.startswith("(") and stripped.endswith(")") and last_dialog is not None:
                last_dialog["english"] = stripped.strip("()\" ")
                continue

            # Everything else is visual description / blocking.
            clean = re.sub(r"\*+", "", stripped)
            if clean.lower().startswith(("camera holds", "the camera")):
                current.camera_movement = (current.camera_movement + " " + clean).strip()
            else:
                current.visual_description = (current.visual_description + " " + clean).strip()

        if current is not None:
            shots.append(current)

        for shot in shots:
            shot.visual_description = shot.visual_description.strip()
            if not shot.camera_movement:
                shot.camera_movement = _detect_camera(shot.setting, shot.lens, shot.visual_description)
            shot.emotion_context = _detect_emotion(
                shot.setting, shot.sound, shot.visual_description,
                " ".join(d.get("telugu", "") + " " + d.get("english", "") for d in shot.dialog),
            )
            shot.composition_notes = (
                f"Lens: {shot.lens or 'standard'} · Camera: {shot.camera_movement or 'static'} · "
                f"Duration: {shot.duration_sec}s"
            )
            shot.color_palette = shot.emotion_context
            for dialog in shot.dialog:
                dialog["emotion"] = shot.emotion_context
        return shots

    @staticmethod
    def _extract_quote(text: str) -> str:
        text = text.strip()
        if text.startswith("(") and text.endswith(")"):
            text = text.strip("()")
        return text.strip().strip('"').strip("“”").strip()

    # ── generic screenplay fallback ─────────────────────────────────────
    def _parse_generic(self, lines: list[str]) -> list[Act]:
        scenes: list[tuple[str, str, list[tuple[str, str]], str]] = []
        setting = ""
        background = ""
        dialogue: list[tuple[str, str]] = []
        for line in lines:
            stripped = line.strip()
            scene_match = re.match(r"^SCENE\s+(\d+)\s*[-–—]\s*(.+)$", stripped, re.IGNORECASE)
            if scene_match:
                if setting:
                    scenes.append((setting, background, dialogue, ""))
                setting = scene_match.group(2).strip()
                background = ""
                dialogue = []
                continue
            if stripped.upper().startswith("BACKGROUND:"):
                background = stripped.split(":", 1)[1].strip()
                continue
            dialog_match = re.match(r"^([A-Z][A-Z .'\-]{1,30}):\s*(.+)$", stripped)
            if dialog_match:
                dialogue.append((dialog_match.group(1).title(), dialog_match.group(2).strip()))
        if setting:
            scenes.append((setting, background, dialogue, ""))

        if not scenes:
            return []

        act = Act(number=1, english_subtitle="The Story", telugu_subtitle="కథ", start_time="0:00", end_time="3:25")
        for idx, (scene_setting, background, dialogue, _) in enumerate(scenes, start=1):
            seq = Sequence(
                number=idx,
                english_name=f"Scene {idx}",
                telugu_name="",
                runtime_minutes=2.0,
                language="te",
            )
            shot_dialog = [
                {
                    "character": character,
                    "telugu": text,
                    "english": text,
                    "direction": "",
                    "emotion": _detect_emotion(text),
                }
                for character, text in dialogue
            ]
            shot = Shot(
                number=f"{idx}.1",
                setting=scene_setting,
                duration_sec=max(3.0, float(len(dialogue) * 4)),
                lens="35mm",
                camera_movement="Medium shot. Naturalistic blocking.",
                visual_description=background or scene_setting,
                dialog=shot_dialog,
                sound="Room tone",
                language="te",
                emotion_context=_detect_emotion(scene_setting, background, " ".join(d[1] for d in dialogue)),
            )
            shot.composition_notes = f"Lens: {shot.lens} · Camera: {shot.camera_movement} · Duration: {shot.duration_sec}s"
            shot.color_palette = shot.emotion_context
            seq.shots.append(shot)
            act.sequences.append(seq)
        return [act]
