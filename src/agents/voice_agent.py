"""Voice agent: multilingual dialogue synthesis, casting and subtitles.

Free-first TTS produces real, playable WAV files (offline synthesiser by
default; ``AFP_TTS_BACKEND=edge`` switches to free neural voices).  The agent
also emits a broadcast-ready SRT, a casting sheet and a combined dialogue reel.
"""
from __future__ import annotations

import wave
from pathlib import Path

from src.agents.base import BaseAgent
from src.core.text import slugify
from src.models.schemas import AgentResult, PipelineContext, VoiceLine, VoiceOutput

_EMOTION_KEYWORDS = [
    (("shout", "yell", "furious", "anger", "angry", "war", "battle", "కోపం"), "intense_anger"),
    (("cry", "sad", "weep", "mourn", "sorrow", "death", "విచారం"), "deep_sadness"),
    (("laugh", "smile", "happy", "celebrate", "joy", "ఆనందం"), "pure_joy"),
    (("scared", "fear", "terrified", "panic", "భయం"), "paralyzing_fear"),
    (("whisper", "calm", "steady", "gentle", "soft", "silence"), "serene_calm"),
    (("shadow", "secret", "suspense", "mystery", "hidden"), "suspense"),
]

_LANGUAGE_VOICES = {
    "te": {"female": "te-IN-ShrutiNeural", "male": "te-IN-MohanNeural"},
    "ta": {"female": "ta-IN-PallaviNeural", "male": "ta-IN-ValluvarNeural"},
    "hi": {"female": "hi-IN-SwaraNeural", "male": "hi-IN-MadhurNeural"},
    "ml": {"female": "ml-IN-SobhanaNeural", "male": "ml-IN-MidhunNeural"},
    "kn": {"female": "kn-IN-SapnaNeural", "male": "kn-IN-GaganNeural"},
    "en": {"female": "en-IN-NeerjaNeural", "male": "en-IN-PrabhatNeural"},
}

_FEMALE_HINTS = ("mother", "woman", "priestess", "princess", "wife", "parvathi", "yashasvi", "sai pallavi", "revathi", "samantha", "ramya")
_MALE_HINTS = ("hero", "villain", "father", "warden", "strategist", "politician", "cop", "chieftain", "dealer", "prabhas", "vijay", "mohanlal", "jagapathi", "madan", "bobby", "arjun", "rajinikanth", "kher")


def detect_emotion(shot_emotion: str, *parts: str) -> str:
    if shot_emotion:
        return shot_emotion
    text = " ".join(parts).lower()
    for keywords, emotion in _EMOTION_KEYWORDS:
        if any(k in text for k in keywords):
            return emotion
    return "contemplative_neutral"


def infer_gender(name: str, function: str = "") -> str:
    blob = f"{name} {function}".lower()
    if any(h in blob for h in _FEMALE_HINTS):
        return "female"
    if any(h in blob for h in _MALE_HINTS):
        return "male"
    # Heuristic: Telugu female names often end in i/aa, but stay conservative.
    return "male" if len(name.split()) > 1 else "female"


class VoiceAgent(BaseAgent):
    def __init__(self):
        super().__init__("voice_agent")

    def process(self, ctx: PipelineContext) -> AgentResult:
        if not ctx.film:
            return AgentResult(agent_name=self.name, output=VoiceOutput(lines=[], total_lines=0))

        run_dir = self.run_dir(ctx)
        cast = {member.role.split("(")[0].strip(): member for member in ctx.film.cast}
        cast_by_upper = {name.upper(): member for name, member in cast.items()}

        shots = list(self.scoped_shots(ctx))
        limit = self.shot_limit(ctx, len(shots))
        shots = shots[:limit]

        lines: list[VoiceLine] = []
        cue_index = 0
        tts_backends: set[str] = set()
        for act, seq, shot in shots:
            for dialog in shot.dialog:
                character = (dialog.get("character") or "Narrator").strip()
                member = cast_by_upper.get(character.upper())
                actor = member.actor if member else "Uncredited"
                function = member.function if member else ""
                gender = infer_gender(character, function)
                language = shot.language or ctx.language or "te"
                voice = _LANGUAGE_VOICES.get(language, _LANGUAGE_VOICES["te"])[gender]
                emotion = detect_emotion(
                    shot.emotion_context, shot.sound, dialog.get("telugu", ""), dialog.get("english", "")
                )
                text = dialog.get("telugu") or dialog.get("english") or ""
                cue_index += 1
                stem = f"seq{seq.number:02d}_shot{shot.number.replace('.', '-')}_{slugify(character)}_{cue_index:03d}"
                planned_rel = f"voice_agent/{run_dir}/audio/{stem}.wav"
                audio_rel = ""
                duration = max(1.2, min(9.0, len(text) / 14.0))

                if ctx.media_enabled and text:
                    try:
                        result = self.studio().providers.tts.synthesize(
                            text,
                            Path(self.studio().artifacts.root) / planned_rel,
                            voice=voice,
                            emotion=emotion,
                        )
                        audio_path = Path(result["path"]).resolve()
                        try:
                            audio_rel = audio_path.relative_to(
                                self.studio().artifacts.root.resolve()
                            ).as_posix()
                        except ValueError:
                            audio_rel = planned_rel
                        duration = float(result.get("duration_sec", duration))
                        tts_backends.add(str(result.get("backend", "wav")))
                        self.emit(ctx, "voice.line", {
                            "character": character,
                            "sequence": seq.number,
                            "shot": shot.number,
                            "duration_sec": duration,
                            "backend": result.get("backend"),
                        })
                    except Exception as exc:  # pragma: no cover - TTS optional
                        self.logger.warning(f"TTS failed for {stem}: {exc}")

                lines.append(VoiceLine(
                    character=character,
                    actor=actor,
                    dialog=text,
                    dialog_english=dialog.get("english", ""),
                    emotion=emotion,
                    language=language,
                    shot_number=shot.number,
                    sequence_num=seq.number,
                    audio_path=audio_rel or planned_rel,
                    duration_sec=round(duration, 2),
                ))

        reel = self._concat_reel(ctx, lines, run_dir)
        srt = self._srt(lines)
        srt_rel = f"voice_agent/{run_dir}/subtitles.srt"
        self.save_text(ctx, "subtitles.srt", srt)

        manifest = {
            "film": ctx.film.title,
            "scope": ctx.scope,
            "language": ctx.language,
            "total_lines": len(lines),
            "rendered_audio": sum(1 for line in lines if line.audio_path.startswith("voice_agent")),
            "backends": sorted(tts_backends) or ["planned"],
            "tts": self.studio().providers.tts.info(),
            "lines": [line.__dict__ for line in lines],
            "dialogue_reel": reel,
        }
        self.save_json(ctx, "voice_manifest.json", manifest)
        self.save_text(ctx, "voice_report.md", self._markdown(ctx, lines, reel, tts_backends))

        ctx.voice_lines = [line.__dict__ for line in lines]
        ctx.artifacts["voice"] = {
            "lines": len(lines),
            "audio_files": sum(1 for line in lines if line.audio_path.startswith("voice_agent")),
            "subtitles": srt_rel,
            "manifest": f"voice_agent/{run_dir}/voice_manifest.json",
            "reel": reel.get("url") if reel else None,
            "backends": sorted(tts_backends) or ["planned"],
        }

        self.remember(
            f"Voice: {len(lines)} dialogue lines synthesised for {ctx.film.title} "
            f"({', '.join(sorted(tts_backends)) or 'planned only'}).",
            key=f"voice:{run_dir}",
            tags=["voice", "tts", "subtitles"],
            metadata={"lines": len(lines)},
        )

        return AgentResult(
            agent_name=self.name,
            output=VoiceOutput(lines=lines, total_lines=len(lines)),
        )

    # ── audio utilities ──────────────────────────────────────────────────
    def _concat_reel(self, ctx: PipelineContext, lines: list[VoiceLine], run_dir: str) -> dict | None:
        wav_paths: list[Path] = []
        for line in lines:
            if not line.audio_path.startswith("voice_agent"):
                continue
            path = self.studio().artifacts.path(line.audio_path)
            if path.exists():
                wav_paths.append(path)
        if not wav_paths:
            return None
        target_rel = f"voice_agent/{run_dir}/dialogue_reel.wav"
        target = self.studio().artifacts.path(target_rel)
        try:
            with wave.open(str(target), "wb") as out:
                params = None
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(22050)
                for path in wav_paths:
                    try:
                        with wave.open(str(path), "rb") as source:
                            if params is None:
                                params = source.getparams()
                                out.setnchannels(params.nchannels)
                                out.setsampwidth(params.sampwidth)
                                out.setframerate(params.framerate)
                            if (
                                source.getnchannels() != out.getnchannels()
                                or source.getframerate() != out.getframerate()
                            ):
                                continue
                            out.writeframes(source.readframes(source.getnframes()))
                    except wave.Error:
                        continue
            return {
                "relative": target_rel,
                "url": self.artifact_url(target_rel),
                "clips": len(wav_paths),
                "bytes": target.stat().st_size,
            }
        except Exception as exc:  # pragma: no cover
            self.logger.warning(f"dialogue reel failed: {exc}")
            return None

    @staticmethod
    def _srt(lines: list[VoiceLine]) -> str:
        def stamp(seconds: float) -> str:
            ms = int(round(seconds * 1000))
            h, ms = divmod(ms, 3_600_000)
            m, ms = divmod(ms, 60_000)
            s, ms = divmod(ms, 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        blocks: list[str] = []
        cursor = 0.0
        for index, line in enumerate(lines, start=1):
            start = cursor + 0.15
            end = start + max(1.0, line.duration_sec)
            cursor = end + 0.25
            text = line.dialog or line.dialog_english
            if line.dialog and line.dialog_english and line.dialog != line.dialog_english:
                text = f"{line.dialog}\n<i>{line.dialog_english}</i>"
            blocks.append(
                f"{index}\n{stamp(start)} --> {stamp(end)}\n{line.character.upper()}: {text}\n"
            )
        return "\n".join(blocks)

    @staticmethod
    def _markdown(ctx: PipelineContext, lines: list[VoiceLine], reel: dict | None, backends: set[str]) -> str:
        by_language: dict[str, int] = {}
        by_emotion: dict[str, int] = {}
        for line in lines:
            by_language[line.language] = by_language.get(line.language, 0) + 1
            by_emotion[line.emotion] = by_emotion.get(line.emotion, 0) + 1
        out = [
            f"# {ctx.film.title} — Voice & Subtitles",
            "",
            f"**Lines:** {len(lines)} · **Backends:** {', '.join(sorted(backends)) or 'planned'}",
            f"**Scope:** {ctx.scope}",
            "",
            "## Language mix",
            "",
            *[f"- {lang}: {count} lines" for lang, count in sorted(by_language.items())],
            "",
            "## Emotional performance",
            "",
            *[f"- {emotion.replace('_', ' ')}: {count}" for emotion, count in sorted(by_emotion.items())],
            "",
        ]
        if reel:
            out += ["## Dialogue reel", "", f"[Download WAV]({reel['url']})", ""]
        out += [
            "## Line list",
            "",
            "| # | Character | Lang | Emotion | Duration | Audio |",
            "|---|-----------|------|---------|----------|-------|",
        ]
        for i, line in enumerate(lines, start=1):
            audio = f"[wav]({line.audio_path})" if line.audio_path.startswith("voice_agent") else "planned"
            out.append(
                f"| {i} | {line.character} | {line.language} | {line.emotion.replace('_', ' ')} | "
                f"{line.duration_sec}s | {audio} |"
            )
        return "\n".join(out) + "\n"
