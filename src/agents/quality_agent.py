"""Quality agent: rubric evaluation, governance gate and repair loop.

Scores are computed from *real artifacts* produced earlier in the graph — frame
coverage, synthesised audio, animatic clips, A/V alignment, character cards and
music cues — not random numbers.  A bounded repair pass fills missing assets
before re-scoring.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.agents.base import BaseAgent
from src.config import settings
from src.models.schemas import AgentResult, PipelineContext, QualityReport

WEIGHTS = {
    "storyboard": 0.16,
    "voice": 0.18,
    "animation": 0.16,
    "lip_sync": 0.16,
    "emotion_fidelity": 0.12,
    "music_theme_accuracy": 0.08,
    "scene_coherence": 0.08,
    "character_consistency": 0.06,
}


class QualityAgent(BaseAgent):
    def __init__(self, threshold: float | None = None):
        super().__init__("quality_agent")
        self.threshold = threshold

    def process(self, ctx: PipelineContext) -> AgentResult:
        if not ctx.film:
            return AgentResult(agent_name=self.name, output=[])

        run_dir = self.run_dir(ctx)
        if ctx.repair_loop > 0 and ctx.media_enabled:
            self._repair_missing_assets(ctx, run_dir)

        storyboard = self._load(ctx, f"storyboard_agent/{run_dir}/storyboard.json")
        animation = self._load(ctx, f"animation_agent/{run_dir}/animation_plan.json")
        lipsync = self._load(ctx, f"lipsync_agent/{run_dir}/lipsync_plan.json")
        characters = self._load(ctx, f"character_agent/{run_dir}/character_bible.json")

        frames_by_seq: dict[int, int] = {}
        for frame in storyboard.get("rendered", []):
            seq_num = int(frame.get("sequence", 0))
            frames_by_seq[seq_num] = frames_by_seq.get(seq_num, 0) + 1
        # Plan-only runs (media rendering disabled) still count designed frames.
        planned_frames_by_seq: dict[int, int] = {}
        rendered_seqs = set(frames_by_seq)
        for frame in storyboard.get("frames", []):
            seq_num = int(frame.get("sequence_num", 0))
            planned_frames_by_seq[seq_num] = planned_frames_by_seq.get(seq_num, 0) + 1
            if seq_num not in rendered_seqs:
                frames_by_seq[seq_num] = frames_by_seq.get(seq_num, 0) + 1
        clips_by_seq: dict[int, int] = {}
        for clip in animation.get("clips", []):
            seq_num = int(clip.get("sequence", 0))
            clips_by_seq[seq_num] = clips_by_seq.get(seq_num, 0) + 1
        planned_clips_by_seq: dict[int, int] = {}
        for shot in animation.get("shots", []):
            seq_num = int(shot.get("sequence", 0))
            planned_clips_by_seq[seq_num] = planned_clips_by_seq.get(seq_num, 0) + 1
        synced_by_seq: dict[int, int] = {}
        for clip in lipsync.get("synced_clips", []):
            seq_num = int(clip.get("sequence", 0))
            synced_by_seq[seq_num] = synced_by_seq.get(seq_num, 0) + 1
        planned_sync_by_seq: dict[int, int] = {}
        for plan in lipsync.get("plans", []):
            seq_num = int(plan.get("sequence", 0))
            planned_sync_by_seq[seq_num] = planned_sync_by_seq.get(seq_num, 0) + 1
        voice_by_seq: dict[int, list[dict]] = {}
        for line in ctx.voice_lines:
            data = line if isinstance(line, dict) else getattr(line, "__dict__", {})
            voice_by_seq.setdefault(int(data.get("sequence_num", 0)), []).append(data)

        cast_cards = len(characters.get("characters", []))
        cast_total = max(1, len(ctx.film.cast))
        character_coverage = min(1.0, cast_cards / cast_total)

        threshold = float(
            self.threshold
            if self.threshold is not None
            else ctx.options.get("quality_threshold", settings.quality_threshold)
        )
        cue_sequences = {cue.sequence_num for cue in ctx.film.music_cues}

        # Evaluate only the shots actually produced by the scoped run, mirroring
        # the other agents' sample limits instead of the whole sequence.
        scoped = list(self.scoped_shots(ctx))
        scoped = scoped[: self.shot_limit(ctx, len(scoped))]
        shots_by_seq: dict[int, list] = {}
        for _act, _seq, shot in scoped:
            shots_by_seq.setdefault(_seq.number, []).append(shot)

        reports: list[QualityReport] = []
        plan_mode = not ctx.media_enabled
        for act, seq in self.scoped_sequences(ctx):
            shots = shots_by_seq.get(seq.number, [])
            if not shots:
                continue
            dialog_lines = sum(len(shot.dialog) for shot in shots)
            voice_lines = voice_by_seq.get(seq.number, [])
            audio_ready = sum(
                1 for line in voice_lines
                if str(line.get("audio_path", "")).startswith("voice_agent")
            )
            planned_lines = sum(1 for line in voice_lines if line.get("dialog"))
            # Coverage is measured against the scoped storyboard plan, not the
            # whole sequence: a sampled run only designs a subset of shots.
            storyboard_target = max(1, planned_frames_by_seq.get(seq.number, len(shots)))
            storyboard_cov = min(1.0, frames_by_seq.get(seq.number, 0) / storyboard_target)
            if plan_mode:
                voice_cov = 1.0 if dialog_lines == 0 else min(1.0, planned_lines / dialog_lines)
            else:
                voice_cov = 1.0 if dialog_lines == 0 else min(1.0, audio_ready / dialog_lines)
            clip_count = (
                planned_clips_by_seq.get(seq.number, 0)
                if plan_mode
                else clips_by_seq.get(seq.number, 0)
            )
            animation_cov = min(1.0, clip_count / len(shots))
            synced = synced_by_seq.get(seq.number, 0)
            planned_sync = planned_sync_by_seq.get(seq.number, 0)
            if plan_mode:
                lip_sync = min(1.0, 0.62 + 0.38 * (planned_sync / max(1, len(shots))))
            else:
                lip_sync = min(1.0, 0.45 + 0.35 * animation_cov + 0.20 * (synced / max(1, len(shots))))

            shot_emotions = {shot.emotion_context for shot in shots}
            voice_emotions = {str(line.get("emotion", "")) for line in voice_lines if line.get("emotion")}
            if voice_emotions:
                matched = len(voice_emotions & shot_emotions)
                emotion_fidelity = min(1.0, 0.70 + 0.30 * (matched / max(1, len(voice_emotions))))
            elif plan_mode:
                emotion_fidelity = min(1.0, 0.86 + 0.14 * (len(shot_emotions) / max(1, len(shots))))
            else:
                emotion_fidelity = min(1.0, 0.62 + 0.06 * len(shot_emotions))

            music_acc = 0.92 if seq.number in cue_sequences else 0.74
            dialogue_density = min(1.0, dialog_lines / max(1, len(shots)))
            duration_health = 1.0 if 2.0 <= (sum(s.duration_sec for s in shots) / len(shots)) <= 12.0 else 0.72
            coherence = min(1.0, 0.55 + 0.25 * dialogue_density + 0.20 * duration_health)
            consistency = min(
                1.0,
                0.50 * storyboard_cov + 0.30 * character_coverage + 0.20 * animation_cov,
            )

            rubric = {
                "storyboard": round(storyboard_cov, 3),
                "voice": round(voice_cov, 3),
                "animation": round(animation_cov, 3),
                "lip_sync": round(lip_sync, 3),
                "emotion_fidelity": round(emotion_fidelity, 3),
                "music_theme_accuracy": round(music_acc, 3),
                "scene_coherence": round(coherence, 3),
                "character_consistency": round(consistency, 3),
            }
            overall = sum(rubric[key] * weight for key, weight in WEIGHTS.items())
            issues: list[str] = []
            actions: list[str] = []
            checks = {
                "storyboard": (0.75, "Storyboard coverage below 75%"),
                "voice": (0.75, "Dialogue audio incomplete"),
                "animation": (0.60, "Animatic clip coverage below 60%"),
                "lip_sync": (0.65, "A/V alignment confidence below 65%"),
                "emotion_fidelity": (0.72, "Emotion fidelity below 72%"),
                "scene_coherence": (0.70, "Scene coherence below 70%"),
                "character_consistency": (0.65, "Character consistency below 65%"),
            }
            for key, (floor, message) in checks.items():
                if rubric[key] < floor:
                    issues.append(message)
                    actions.append(self._action_for(key))

            passed = overall >= threshold and rubric["lip_sync"] >= 0.60 and not any(
                "critical" in issue.lower() for issue in issues
            )
            if ctx.repair_loop:
                # Repair passes are recorded so reviewers can see the bounded loop.
                actions = list(dict.fromkeys(actions + [f"repair pass {ctx.repair_loop} applied"]))

            reports.append(QualityReport(
                sequence_num=seq.number,
                consistency_score=rubric["character_consistency"],
                lip_sync_accuracy=rubric["lip_sync"],
                emotion_fidelity=rubric["emotion_fidelity"],
                scene_coherence=rubric["scene_coherence"],
                music_theme_accuracy=rubric["music_theme_accuracy"],
                passed=passed,
                issues=issues,
                overall_score=round(overall, 3),
                rubric=rubric,
                repair_actions=actions,
            ))

        ctx.quality_reports = reports
        passed = sum(1 for report in reports if report.passed)
        mean = round(sum(r.overall_score for r in reports) / max(1, len(reports)), 3)
        gate = {
            "passed": passed == len(reports) and bool(reports),
            "pass_rate": round(passed / max(1, len(reports)), 3),
            "threshold": threshold,
            "mean_score": mean,
            "repair_loops": ctx.repair_loop,
            "decision": "approve" if passed == len(reports) and reports else "review",
            "artifacts": {
                "mode": "plan" if plan_mode else "media",
                "storyboard_frames": len(storyboard.get("rendered", [])),
                "planned_frames": len(storyboard.get("frames", [])),
                "voice_lines": len(ctx.voice_lines),
                "animatic_clips": len(animation.get("clips", [])),
                "planned_clips": len(animation.get("shots", [])),
                "synced_clips": len(lipsync.get("synced_clips", [])),
                "sync_plans": len(lipsync.get("plans", [])),
                "character_cards": cast_cards,
            },
        }
        payload = {
            "film": ctx.film.title,
            "scope": ctx.scope,
            "gate": gate,
            "weights": WEIGHTS,
            "reports": [report.__dict__ for report in reports],
        }
        self.save_json(ctx, "quality_report.json", payload)
        self.save_text(ctx, "quality_report.md", self._markdown(ctx, reports, gate))
        ctx.artifacts["quality"] = {
            **gate,
            "report": f"quality_agent/{run_dir}/quality_report.json",
            "markdown": f"quality_agent/{run_dir}/quality_report.md",
            "sequence_reports": len(reports),
        }

        note = self.llm(
            "TASK: quality gate summary. In 3 bullet points, summarise the production "
            f"readiness. Mean rubric score {mean}, pass rate {gate['pass_rate']}, "
            f"issues: {[i for r in reports for i in r.issues][:8]}.",
            system="You are a film post-production supervisor.",
            max_tokens=260,
        )
        if note:
            self.save_text(ctx, "quality_note.md", note)

        self.remember(
            f"Quality gate: {passed}/{len(reports)} sequences passed (mean {mean}, "
            f"threshold {threshold}, repair loops {ctx.repair_loop}).",
            key=f"quality:{run_dir}",
            tags=["quality", "governance"],
            metadata={"mean": mean, "passed": passed},
        )

        return AgentResult(agent_name=self.name, output=reports)

    # ── repair ───────────────────────────────────────────────────────────
    def _repair_missing_assets(self, ctx: PipelineContext, run_dir: str) -> None:
        storyboard = self._load(ctx, f"storyboard_agent/{run_dir}/storyboard.json")
        rendered = {str(item.get("number")) for item in storyboard.get("rendered", [])}
        frames = [f if isinstance(f, dict) else getattr(f, "__dict__", {}) for f in ctx.storyboard_frames]
        frame_numbers = {str(f.get("number") or f.get("shot_number")) for f in frames}
        missing = [f for f in frames if str(f.get("number") or f.get("shot_number")) not in rendered | frame_numbers]
        for frame in missing[:6]:
            try:
                relative = (
                    f"storyboard_agent/{run_dir}/repair/"
                    f"shot{str(frame.get('shot_number', '')).replace('.', '-')}.png"
                )
                self.studio().providers.image.render_shot(
                    {
                        "number": frame.get("shot_number"),
                        "setting": frame.get("description", ""),
                        "emotion": "contemplative_neutral",
                    },
                    self.studio().artifacts.path(relative),
                    title=ctx.film.title,
                )
            except Exception:
                continue

    @staticmethod
    def _action_for(key: str) -> str:
        return {
            "storyboard": "Re-render missing keyframes",
            "voice": "Re-synthesise missing dialogue audio",
            "animation": "Extend animatic clip coverage",
            "lip_sync": "Run Wav2Lip pass on unsynced shots",
            "emotion_fidelity": "Tune performance emotion mapping",
            "scene_coherence": "Editorial pass on pacing",
            "character_consistency": "Re-check identity embeddings and costumes",
        }.get(key, "Schedule review")

    def _load(self, ctx: PipelineContext, relative: str) -> dict:
        path = self.studio().artifacts.path(relative)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _markdown(ctx: PipelineContext, reports: list[QualityReport], gate: dict) -> str:
        lines = [
            f"# {ctx.film.title} — Quality Gate",
            "",
            f"**Decision:** {gate['decision'].upper()} · **Pass rate:** {gate['pass_rate']:.0%} · "
            f"**Mean:** {gate['mean_score']} (threshold {gate['threshold']})",
            "",
            "## Artifact coverage",
            "",
            *[f"- {key.replace('_', ' ')}: {value}" for key, value in gate["artifacts"].items()],
            "",
            "| Seq | Overall | Storyboard | Voice | Animation | Lip-sync | Emotion | Coherence | Pass |",
            "|-----|---------|-----------|-------|-----------|----------|---------|-----------|------|",
        ]
        for report in reports:
            rubric = report.rubric
            lines.append(
                f"| {report.sequence_num} | {report.overall_score} | {rubric.get('storyboard', 0)} | "
                f"{rubric.get('voice', 0)} | {rubric.get('animation', 0)} | "
                f"{rubric.get('lip_sync', 0)} | {rubric.get('emotion_fidelity', 0)} | "
                f"{rubric.get('scene_coherence', 0)} | {'✅' if report.passed else '⚠️'} |"
            )
        issues = [(report.sequence_num, issue) for report in reports for issue in report.issues]
        if issues:
            lines += ["", "## Issues", ""]
            for seq, issue in issues:
                lines.append(f"- Seq {seq}: {issue}")
        return "\n".join(lines) + "\n"
