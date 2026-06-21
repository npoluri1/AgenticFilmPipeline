import re
from pathlib import Path

from src.models.schemas import (
    FilmScript, Act, Sequence, Shot, CastMember, MusicTheme, MusicCue,
)
from src.utils.logger import get_logger

logger = get_logger("reader.ruthambhara")


class RuthambharaReader:
    def read(self, path: str) -> FilmScript:
        text = Path(path).read_text(encoding="utf-8")
        lines = text.split("\n")

        film = self._parse_header(lines)
        film.cast = self._parse_cast(lines)
        film.music_themes = self._parse_music_themes(lines)
        film.music_cues = self._parse_music_cues(lines)
        film.acts = self._parse_acts(lines)

        total_seq = sum(len(a.sequences) for a in film.acts)
        total_shots = sum(len(s.shots) for a in film.acts for s in a.sequences)
        logger.info(f"Parsed {len(film.acts)} acts, {total_seq} sequences, {total_shots} shots")
        return film

    def _parse_header(self, lines: list[str]) -> FilmScript:
        runtime_line = next((line for line in lines if "రన్టైమ్" in line or "Runtime" in line), "")
        lang_line = next((line for line in lines if "భాష" in line or "language" in line.lower()), "")
        aspect_line = next((line for line in lines if "ఆస్పెక్ట్" in line or "aspect" in line.lower()), "")

        runtime_match = re.search(r"(\d+)\s*(?:గంటల|hours?)\s*(?:\s+(\d+)\s*(?:నిమిషాలు|minutes?))?", runtime_line)
        hours = int(runtime_match.group(1)) if runtime_match else 3
        minutes = int(runtime_match.group(2)) if runtime_match and runtime_match.group(2) else 25
        total_minutes = hours * 60 + minutes

        langs = ["te"]
        lang_match = re.search(r"\((.+?)\)", lang_line)
        if lang_match:
            lang_str = lang_match.group(1)
            lang_map = {"తెలుగు": "te", "Tamil": "ta", "Hindi": "hi", "Malayalam": "ml", "Kannada": "kn"}
            langs = []
            for name, code in lang_map.items():
                if name in lang_str or code in lang_str.lower():
                    langs.append(code)
            if not langs:
                langs = ["te"]

        return FilmScript(
            title="RUTHAMBHARA",
            telugu_title="ఋతంభర",
            runtime_str=runtime_line.strip(),
            runtime_minutes=float(total_minutes),
            languages=langs,
            aspect_ratio=aspect_line.strip() if aspect_line else "2.39:1",
        )

    def _parse_cast(self, lines: list[str]) -> list[CastMember]:
        cast = []
        in_cast = False
        for line in lines:
            if "PAN-INDIA CAST" in line:
                in_cast = True
                continue
            if in_cast and line.strip().startswith("|") and "Role" not in line and "------" not in line and "--" not in line:
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) >= 3 and not parts[0].startswith("|"):
                    cast.append(CastMember(role=parts[0], actor=parts[1], function=parts[2]))
            if in_cast and line.strip().startswith("##") and "CAST" not in line:
                break
        return cast

    def _parse_music_themes(self, lines: list[str]) -> list[MusicTheme]:
        themes = []
        for line in lines:
            m = re.match(r"###\s*Theme\s+\d+\s*—\s*\"(.+?)\"\s*\((.+?)\)\s*—\s*(.+)", line)
            if m:
                themes.append(MusicTheme(
                    name=m.group(2).strip(),
                    telugu_name=m.group(1).strip(),
                    description=m.group(3).strip(),
                    instruments="",
                    inspiration="",
                    usage_rule="",
                ))
            elif themes:
                if "- **Instruments:**" in line:
                    themes[-1].instruments = line.split("**Instruments:**")[1].strip()
                elif "- **Inspired by:**" in line:
                    themes[-1].inspiration = line.split("**Inspired by:**")[1].strip()
                elif "- **Plays:**" in line:
                    themes[-1].usage_rule = line.split("**Plays:**")[1].strip()
        return themes

    def _parse_music_cues(self, lines: list[str]) -> list[MusicCue]:
        cues = []
        in_cues = False
        for line in lines:
            if "MUSIC CUE SHEET" in line:
                in_cues = True
                continue
            if in_cues and line.strip().startswith("##") and "CUE" not in line:
                break
            if in_cues and line.strip().startswith("|") and "Seq" not in line and "---" not in line and "--" not in line:
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) >= 6:
                    cues.append(MusicCue(
                        sequence_num=int(parts[0]) if parts[0].isdigit() else 0,
                        entry_time=parts[1],
                        duration=parts[2],
                        theme=parts[3],
                        instruments=parts[4],
                        scene_description=parts[5],
                    ))
        return cues

    def _parse_acts(self, lines: list[str]) -> list[Act]:
        acts = []
        current_act = None
        current_sequence = None

        i = 0
        while i < len(lines):
            line = lines[i]

            act_match = re.match(r"# ⚔️\s*ACT\s+([IVXLCDM]+)\s*—\s*\"(.+?)\"\s*\((.+?)\)", line)
            if act_match:
                if current_act and current_sequence:
                    current_act.sequences.append(current_sequence)
                if current_act:
                    acts.append(current_act)

                rt_match = re.search(r"(\d+:\d+)\s*—\s*(\d+:\d+)", line)
                current_act = Act(
                    number=self._roman_to_int(act_match.group(1)),
                    english_subtitle=act_match.group(2),
                    telugu_subtitle=act_match.group(3),
                    start_time=rt_match.group(1) if rt_match else "",
                    end_time=rt_match.group(2) if rt_match else "",
                )
                current_sequence = None
                i += 1
                continue

            seq_match = re.match(r"##\s*SEQUENCE\s+(\d+)\s*—\s*\"(.+?)\s*\"\s*\((.+?)\)", line)
            if not seq_match:
                seq_match = re.match(r"##\s*SEQUENCE\s+(\d+)\s*—\s*\"(.+?)\"", line)

            if seq_match:
                if current_act and current_sequence:
                    current_act.sequences.append(current_sequence)

                runtime = 5.0
                rt_match = re.search(r"(\d+)\s*నిమిషాలు", line)
                if rt_match:
                    runtime = float(rt_match.group(1))
                else:
                    if i + 1 < len(lines):
                        rt_match = re.search(r"(\d+)\s*నిమిషాలు", lines[i + 1])
                        if rt_match:
                            runtime = float(rt_match.group(1))

                seq_num = int(seq_match.group(1))
                telugu_name = seq_match.group(3).strip() if seq_match.lastindex >= 3 and " " not in seq_match.group(3) and len(seq_match.group(3)) < 50 else ""
                english_name = seq_match.group(2).strip()

                current_sequence = Sequence(
                    number=seq_num,
                    telugu_name=telugu_name,
                    english_name=english_name,
                    runtime_minutes=runtime,
                )

                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    if next_line.startswith("## SEQUENCE") or (next_line.startswith("# ") and "ACT" in next_line):
                        break

                    shot = self._parse_shot(next_line, seq_num)
                    if shot:
                        current_sequence.shots.append(shot)
                    j += 1

                i = j
                continue

            end_match = re.match(r"#\s*⏸️\s*END OF ACT", line)
            if end_match and current_act and current_sequence:
                current_act.sequences.append(current_sequence)
                acts.append(current_act)
                current_act = None
                current_sequence = None
                i += 1
                continue

            i += 1

        if current_act and current_sequence:
            current_act.sequences.append(current_sequence)
            acts.append(current_act)
        elif current_act:
            acts.append(current_act)

        return acts

    def _parse_shot(self, line: str, seq_num: int) -> Shot | None:
        m = re.match(r"\*\*\[(\d+\.\d+)\]\s*(.+?)\*\*\s*(?:\((\d+)s\))?", line)
        if not m:
            m = re.match(r"\[(\d+\.\d+)\]\s*(.+?)\s*(?:\((\d+)s\)|$)", line)
        if not m:
            return None

        setting = m.group(2).strip()
        duration = float(m.group(3)) if m.lastindex >= 3 and m.group(3) else 5.0

        lens = ""
        sound = ""

        return Shot(
            number=m.group(1),
            setting=setting,
            duration_sec=duration,
            lens=lens,
            camera_movement="",
            visual_description="",
            dialog=[],
            sound=sound,
            language="te",
        )

    def _roman_to_int(self, s: str) -> int:
        vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
        result = 0
        for i, c in enumerate(s):
            if i + 1 < len(s) and vals.get(s[i + 1], 0) > vals.get(c, 0):
                result -= vals.get(c, 0)
            else:
                result += vals.get(c, 0)
        return result
