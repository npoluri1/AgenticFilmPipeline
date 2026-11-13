"""Storyboard agent: shot design plus real, offline pre-visualisation frames.

Every scoped shot becomes a :class:`StoryboardFrame`.  When media rendering is
enabled the free procedural renderer paints a graded PNG keyframe for each frame
and assembles a contact sheet, so the dashboard has genuine visual artifacts.
"""
from __future__ import annotations

from src.agents.base import BaseAgent
from src.models.schemas import (
    AgentResult,
    PipelineContext,
    StoryboardFrame,
    StoryboardOutput,
)


def detect_angle(setting: str, lens: str = "") -> str:
    text = f"{setting} {lens}".upper()
    if "EXTREME CLOSE" in text or "ECU" in text:
        return "extreme close-up"
    if "CLOSE-UP" in text or "CLOSE UP" in text or " CU" in text:
        return "close-up"
    if "GOD-VIEW" in text or "AERIAL" in text or "DRONE" in text:
        return "bird's eye"
    if "CRANE" in text:
        return "crane"
    if "DOLLY" in text or "PULL-BACK" in text or "PULL BACK" in text:
        return "dolly"
    if "POV" in text:
        return "point of view"
    if "WIDE" in text:
        return "wide"
    return "medium"


class StoryboardAgent(BaseAgent):
    def __init__(self):
        super().__init__("storyboard_agent")

    def process(self, ctx: PipelineContext) -> AgentResult:
        if not ctx.film:
            return AgentResult(
                agent_name=self.name,
                output=StoryboardOutput(frames=[], total_shots=0),
            )

        shots = list(self.scoped_shots(ctx))
        limit = self.shot_limit(ctx, len(shots))
        shots = shots[:limit]
        self.emit(ctx, "agent.stage", {"stage": "designing shots", "shots": len(shots)})

        frames: list[StoryboardFrame] = []
        rendered: list[dict] = []
        run_dir = self.run_dir(ctx)
        for index, (act, seq, shot) in enumerate(shots, start=1):
            angle = detect_angle(shot.setting, shot.lens)
            frame = StoryboardFrame(
                sequence_num=seq.number,
                shot_number=shot.number,
                frame_number=index,
                description=shot.visual_description or shot.setting,
                camera_angle=angle,
                lens=shot.lens,
                composition_notes=shot.composition_notes
                or f"{angle} · {shot.camera_movement or 'static'} · {shot.duration_sec}s",
                duration_sec=shot.duration_sec,
            )
            frames.append(frame)

            if not ctx.media_enabled:
                continue
            relative = (
                f"storyboard_agent/{run_dir}/frames/"
                f"seq{seq.number:02d}_shot{shot.number.replace('.', '-')}.png"
            )
            payload = {
                "act": act.number,
                "sequence": seq.number,
                "number": shot.number,
                "setting": shot.setting,
                "lens": shot.lens,
                "camera_movement": shot.camera_movement,
                "duration_sec": shot.duration_sec,
                "emotion": shot.emotion_context,
                "visual_description": shot.visual_description,
            }
            try:
                result = self.studio().providers.image.render_shot(
                    payload, self.studio().artifacts.path(relative), title=ctx.film.title
                )
                rendered.append({
                    **result,
                    "relative": relative,
                    "url": self.artifact_url(relative),
                    "number": shot.number,
                    "setting": shot.setting,
                    "sequence": seq.number,
                    "act": act.number,
                    "emotion": shot.emotion_context,
                })
                self.emit(ctx, "storyboard.frame", {
                    "shot": shot.number,
                    "url": self.artifact_url(relative),
                    "renderer": result.get("renderer"),
                })
            except Exception as exc:  # pragma: no cover - renderer optional
                self.logger.warning(f"frame render failed for {shot.number}: {exc}")

        contact = None
        if rendered:
            try:
                contact_rel = f"storyboard_agent/{run_dir}/contact_sheet.png"
                contact = self.studio().providers.image.procedural.render_contact_sheet(
                    rendered, self.studio().artifacts.path(contact_rel),
                    title=f"{ctx.film.title} — {len(rendered)} keyframes",
                )
                contact["url"] = self.artifact_url(contact_rel)
                contact["relative"] = contact_rel
            except Exception as exc:  # pragma: no cover
                self.logger.warning(f"contact sheet failed: {exc}")

        ctx.storyboard_frames = rendered or [f.__dict__ for f in frames]
        ctx.artifacts["storyboard"] = {
            "frames": len(frames),
            "rendered": len(rendered),
            "contact_sheet": contact["relative"] if contact else None,
            "contact_sheet_url": contact["url"] if contact else None,
            "manifest": f"storyboard_agent/{run_dir}/storyboard.json",
            "sheet_markdown": f"storyboard_agent/{run_dir}/storyboard.md",
        }

        manifest = {
            "film": ctx.film.title,
            "scope": ctx.scope,
            "frames": [f.__dict__ for f in frames],
            "rendered": rendered,
            "contact_sheet": contact,
            "renderer": self.studio().providers.image.info(),
        }
        self.save_json(ctx, "storyboard.json", manifest)
        self.save_text(ctx, "storyboard.md", self._markdown(ctx, frames, contact))

        self.remember(
            f"Storyboard: {len(frames)} planned frames, {len(rendered)} painted keyframes "
            f"for {ctx.film.title} (scope={ctx.scope}).",
            key=f"storyboard:{run_dir}",
            tags=["storyboard", "visual"],
            metadata={"frames": len(frames), "rendered": len(rendered)},
        )
        self.emit(ctx, "agent.stage", {"stage": "storyboard ready", "frames": len(frames)})

        return AgentResult(
            agent_name=self.name,
            output=StoryboardOutput(frames=frames, total_shots=len(frames)),
        )

    @staticmethod
    def _markdown(ctx: PipelineContext, frames: list[StoryboardFrame], contact: dict | None) -> str:
        lines = [f"# {ctx.film.title} — Storyboard", ""]
        if contact:
            lines += [f"![Contact sheet]({contact['url']})", ""]
        lines += [
            f"**Frames:** {len(frames)} · **Scope:** {ctx.scope}",
            "",
            "| # | Act | Seq | Shot | Angle | Lens | Duration | Emotion |",
            "|---|-----|-----|------|-------|------|----------|---------|",
        ]
        for i, frame in enumerate(frames, start=1):
            lines.append(
                f"| {i} | – | {frame.sequence_num} | {frame.shot_number} | "
                f"{frame.camera_angle} | {frame.lens or 'standard'} | "
                f"{frame.duration_sec}s | – |"
            )
        lines += [
            "",
            "## Shot descriptions",
            "",
        ]
        for frame in frames:
            lines += [
                f"### Seq {frame.sequence_num} · Shot {frame.shot_number}",
                f"- **Angle:** {frame.camera_angle}",
                f"- **Lens:** {frame.lens or 'standard'}",
                f"- **Composition:** {frame.composition_notes}",
                f"- {frame.description}",
                "",
            ]
        return "\n".join(lines)
