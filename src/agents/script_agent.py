"""Script agent: screenplay intelligence, coverage analysis and structured breakdown."""
from __future__ import annotations

import csv
import io
from collections import Counter
from pathlib import Path

from src.agents.base import BaseAgent
from src.models.schemas import AgentResult, PipelineContext, ScriptOutput


class ScriptAgent(BaseAgent):
    def __init__(self):
        super().__init__("script_agent")

    def process(self, ctx: PipelineContext) -> AgentResult:
        self.emit(ctx, "agent.stage", {"stage": "reading screenplay"})
        film = self.studio().script.load(path=ctx.source_script_path)
        ctx.film = film

        total_seq = sum(len(a.sequences) for a in film.acts)
        total_shots = sum(len(s.shots) for a in film.acts for s in a.sequences)
        dialog_lines = [d for a in film.acts for s in a.sequences for shot in s.shots for d in shot.dialog]
        dialog_characters = Counter(d.get("character", "Unknown") for d in dialog_lines)
        emotion_counts = Counter(
            shot.emotion_context for a in film.acts for s in a.sequences for shot in s.shots
        )
        lens_counts = Counter(
            (shot.lens.split(",")[0].strip() or "standard")
            for a in film.acts for s in a.sequences for shot in s.shots
        )
        avg_shot = (
            sum(s.duration_sec for a in film.acts for s in a.sequences for s in s.shots) / total_shots
            if total_shots else 0
        )
        acts_summary = [
            {
                "number": act.number,
                "title": act.english_subtitle,
                "telugu_title": act.telugu_subtitle,
                "runtime": f"{act.start_time}–{act.end_time}",
                "sequences": len(act.sequences),
                "shots": sum(len(s.shots) for s in act.sequences),
                "runtime_minutes": round(sum(s.runtime_minutes for s in act.sequences), 1),
            }
            for act in film.acts
        ]
        sequence_summary = [
            {
                "number": seq.number,
                "act": act.number,
                "title": seq.english_name,
                "telugu_title": seq.telugu_name,
                "runtime_minutes": seq.runtime_minutes,
                "shots": len(seq.shots),
                "estimated_seconds": round(sum(s.duration_sec for s in seq.shots), 1),
                "emotions": sorted({s.emotion_context for s in seq.shots}),
            }
            for act in film.acts
            for seq in act.sequences
        ]

        coverage_prompt = (
            "TASK: screenplay coverage. Summarise the production risks and strengths of this "
            f"feature film in 4 bullet points. Title: {film.title}. Runtime: {film.runtime_minutes} min. "
            f"Acts: {len(film.acts)}, sequences: {total_seq}, shots: {total_shots}. "
            f"Top speaking roles: {dialog_characters.most_common(6)}. "
            f"Emotion distribution: {emotion_counts.most_common(6)}."
        )
        llm_note = self.llm(coverage_prompt, system="You are a film script analyst.", max_tokens=350)

        analysis = {
            "title": film.title,
            "telugu_title": film.telugu_title,
            "runtime_minutes": film.runtime_minutes,
            "languages": film.languages,
            "aspect_ratio": film.aspect_ratio,
            "acts": len(film.acts),
            "sequences": total_seq,
            "shots": total_shots,
            "cast": len(film.cast),
            "speaking_roles": len(dialog_characters),
            "dialog_lines": len(dialog_lines),
            "music_themes": len(film.music_themes),
            "music_cues": len(film.music_cues),
            "avg_shot_duration_sec": round(avg_shot, 2),
            "shots_per_minute": round(total_shots / max(1, film.runtime_minutes), 2),
            "dialog_per_minute": round(len(dialog_lines) / max(1, film.runtime_minutes), 2),
            "emotion_distribution": dict(emotion_counts.most_common()),
            "lens_distribution": dict(lens_counts.most_common(10)),
            "top_speaking_roles": dict(dialog_characters.most_common(10)),
            "act_summary": acts_summary,
            "sequence_summary": sequence_summary,
            "coverage_note": llm_note,
            "production_complexity": self._complexity(total_shots, total_seq, len(film.cast)),
        }
        ctx.analysis = analysis
        ctx.artifacts["script"] = {
            "analysis": f"script_agent/{self.run_dir(ctx)}/script_analysis.json",
            "coverage_report": f"script_agent/{self.run_dir(ctx)}/coverage_report.md",
            "shot_breakdown": f"script_agent/{self.run_dir(ctx)}/shot_breakdown.csv",
        }

        self.save_json(ctx, "script_analysis.json", analysis)
        self.save_text(ctx, "coverage_report.md", self._coverage_markdown(analysis))
        self.save_text(ctx, "shot_breakdown.csv", self._shot_csv(ctx))

        self.remember(
            f"{film.title}: {len(film.acts)} acts, {total_seq} sequences, {total_shots} shots, "
            f"{len(film.cast)} cast. Runtime {film.runtime_minutes} minutes. "
            f"Top roles: {', '.join(list(dialog_characters)[:5])}.",
            key=f"film:{film.title}",
            tags=["screenplay", "script", "coverage"],
        )

        return AgentResult(
            agent_name=self.name,
            output=ScriptOutput(
                film=film,
                total_acts=len(film.acts),
                total_sequences=total_seq,
                language=ctx.language,
            ),
        )

    @staticmethod
    def _complexity(shots: int, sequences: int, cast: int) -> dict:
        score = min(100, round(shots * 0.35 + sequences * 1.4 + cast * 1.8))
        tier = "high" if score >= 75 else "medium" if score >= 45 else "low"
        return {"score": score, "tier": tier}

    @staticmethod
    def _coverage_markdown(analysis: dict) -> str:
        lines = [
            f"# {analysis['title']} — Script Coverage",
            "",
            f"**Runtime:** {analysis['runtime_minutes']} minutes · **Aspect:** {analysis['aspect_ratio']}",
            f"**Languages:** {', '.join(analysis['languages'])}",
            "",
            "## Structure",
            "",
            f"- Acts: **{analysis['acts']}**",
            f"- Sequences: **{analysis['sequences']}**",
            f"- Shots: **{analysis['shots']}**",
            f"- Average shot length: **{analysis['avg_shot_duration_sec']}s**",
            f"- Shots / minute: **{analysis['shots_per_minute']}**",
            "",
            "## Cast & Dialogue",
            "",
            f"- Cast members: **{analysis['cast']}**",
            f"- Speaking roles: **{analysis['speaking_roles']}**",
            f"- Dialogue lines: **{analysis['dialog_lines']}**",
            "",
            "### Top speaking roles",
            "",
        ]
        for role, count in analysis["top_speaking_roles"].items():
            lines.append(f"- {role}: {count} lines")
        lines += ["", "## Emotional Palette", ""]
        for emotion, count in analysis["emotion_distribution"].items():
            lines.append(f"- {emotion.replace('_', ' ')}: {count} shots")
        lines += ["", "## Production Complexity", "",
                  f"Score **{analysis['production_complexity']['score']}/100** ({analysis['production_complexity']['tier']}).", ""]
        if analysis.get("coverage_note"):
            lines += ["## Analyst Note", "", analysis["coverage_note"], ""]
        return "\n".join(lines)

    def _shot_csv(self, ctx: PipelineContext) -> str:
        if not ctx.film:
            return ""
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            "act", "sequence", "sequence_title", "shot", "setting", "duration_sec",
            "lens", "camera_movement", "emotion", "dialog_lines", "sound",
        ])
        for act, seq, shot in self.all_shots(ctx):
            writer.writerow([
                act.number, seq.number, seq.english_name, shot.number, shot.setting,
                shot.duration_sec, shot.lens, shot.camera_movement, shot.emotion_context,
                len(shot.dialog), shot.sound,
            ])
        return buffer.getvalue()
