"""Animation agent: animatic clips and a free-video generation plan.

If FFmpeg and keyframes are available the agent turns each storyboard frame into
a real animatic clip (with a subtle Ken-Burns-style push handled by FFmpeg).  It
always produces an engine-agnostic prompt plan so the same shots can be sent to
free text-to-video tools (Stable Video Diffusion, Runway, Pika, Kling, Luma).
"""
from __future__ import annotations

from pathlib import Path

from src.agents.base import BaseAgent
from src.models.schemas import AgentResult, AnimationOutput, PipelineContext

_FREE_VIDEO_ENGINES = [
    {"name": "stable-video-diffusion", "tier": "free", "local": True,
     "note": "Open-source SVD; runs on a consumer GPU via diffusers."},
    {"name": "animatediff", "tier": "free", "local": True,
     "note": "Open-source motion adapter for SD pipelines."},
    {"name": "runway-gen4", "tier": "freemium", "local": False,
     "note": "Free credits; strong cinematic motion."},
    {"name": "pika-2", "tier": "freemium", "local": False,
     "note": "Free tier; fast iteration on short shots."},
    {"name": "kling-1.6", "tier": "freemium", "local": False,
     "note": "Free daily credits; good human motion."},
    {"name": "luma-dream-machine", "tier": "freemium", "local": False,
     "note": "Free tier; good camera-move adherence."},
]


class AnimationAgent(BaseAgent):
    def __init__(self):
        super().__init__("animation_agent")

    def process(self, ctx: PipelineContext) -> AgentResult:
        if not ctx.film:
            return AgentResult(agent_name=self.name, output=[])

        run_dir = self.run_dir(ctx)
        shots = list(self.scoped_shots(ctx))
        limit = self.shot_limit(ctx, len(shots))
        shots = shots[:limit]

        frame_by_shot = {}
        for frame in ctx.storyboard_frames:
            data = frame if isinstance(frame, dict) else getattr(frame, "__dict__", {})
            shot_key = str(data.get("number") or data.get("shot_number") or "")
            if shot_key:
                frame_by_shot[shot_key] = data

        animations: list[AnimationOutput] = []
        clips: list[dict] = []
        prompts: list[dict] = []
        available = ctx.media_enabled and ctx.video_enabled and self.studio().providers.video.available()

        for act, seq, shot in shots:
            frame = frame_by_shot.get(str(shot.number), {})
            source_rel = frame.get("relative") or ""
            source = self.studio().artifacts.path(source_rel) if source_rel else None
            clip_rel = f"animation_agent/{run_dir}/clips/seq{seq.number:02d}_shot{shot.number.replace('.', '-')}.mp4"
            rendered = False
            duration = max(1.0, min(float(shot.duration_sec), 12.0))

            if available and source and Path(source).exists():
                try:
                    self.studio().providers.video.still_to_clip(
                        Path(source),
                        self.studio().artifacts.path(clip_rel),
                        duration,
                        width=960,
                        height=540,
                        fps=24,
                    )
                    rendered = True
                    clips.append({
                        "relative": clip_rel,
                        "url": self.artifact_url(clip_rel),
                        "sequence": seq.number,
                        "shot": shot.number,
                        "duration_sec": duration,
                    })
                    self.emit(ctx, "animation.clip", {
                        "sequence": seq.number,
                        "shot": shot.number,
                        "url": self.artifact_url(clip_rel),
                    })
                except Exception as exc:  # pragma: no cover - ffmpeg optional
                    self.logger.warning(f"animatic clip failed for shot {shot.number}: {exc}")

            animations.append(AnimationOutput(
                sequence_num=seq.number,
                shot_number=shot.number,
                video_path=clip_rel if rendered else f"(planned) {clip_rel}",
                frame_count=int(duration * 24),
                fps=24,
                duration_sec=round(duration, 2),
            ))
            prompts.append(self._prompt(act, seq, shot, frame))

        plan = {
            "film": ctx.film.title,
            "scope": ctx.scope,
            "aspect_ratio": ctx.film.aspect_ratio,
            "engines": _FREE_VIDEO_ENGINES,
            "clips": clips,
            "rendered": len(clips),
            "planned": len(animations),
            "shots": prompts,
            "renderer": self.studio().providers.video.info(),
        }
        self.save_json(ctx, "animation_plan.json", plan)
        self.save_text(ctx, "animation_plan.md", self._markdown(ctx, animations, clips, prompts))
        self.save_json(ctx, "video_prompts.json", [p["prompt"] for p in prompts])

        ctx.artifacts["animation"] = {
            "shots": len(animations),
            "clips": len(clips),
            "engine": self.studio().providers.video.info()["backend"],
            "plan": f"animation_agent/{run_dir}/animation_plan.json",
            "prompts": f"animation_agent/{run_dir}/video_prompts.json",
            "clip_urls": [c["url"] for c in clips],
        }

        self.remember(
            f"Animatics: {len(clips)}/{len(animations)} clips rendered for {ctx.film.title} "
            f"using {self.studio().providers.video.info()['backend']}.",
            key=f"animation:{run_dir}",
            tags=["animation", "video"],
            metadata={"clips": len(clips)},
        )

        return AgentResult(agent_name=self.name, output=animations)

    @staticmethod
    def _prompt(act, seq, shot, frame: dict) -> dict:
        visual = shot.visual_description or shot.setting
        prompt = (
            f"Cinematic film still in motion, {shot.setting}. {visual}. "
            f"{shot.lens or '35mm'} lens, {shot.camera_movement or 'slow push in'}, "
            f"{shot.emotion_context.replace('_', ' ')} mood, {shot.duration_sec}s shot, "
            f"Telugu epic feature film, anamorphic 2.39:1, volumetric light, film grain, "
            "natural motion, no text, no watermark"
        )
        return {
            "act": act.number,
            "sequence": seq.number,
            "shot": shot.number,
            "setting": shot.setting,
            "duration_sec": shot.duration_sec,
            "emotion": shot.emotion_context,
            "prompt": prompt,
            "negative_prompt": "text, subtitles, watermark, morphing faces, extra limbs, cartoon",
            "reference_frame": frame.get("url"),
        }

    @staticmethod
    def _markdown(ctx: PipelineContext, animations, clips, prompts) -> str:
        lines = [
            f"# {ctx.film.title} — Animation Plan",
            "",
            f"**Shots:** {len(animations)} · **Animatic clips:** {len(clips)} · **Aspect:** {ctx.film.aspect_ratio}",
            "",
            "## Free video engines",
            "",
        ]
        for engine in _FREE_VIDEO_ENGINES:
            lines.append(f"- **{engine['name']}** ({engine['tier']}) — {engine['note']}")
        lines += ["", "## Shot prompts", ""]
        for item in prompts[:24]:
            lines += [
                f"### Seq {item['sequence']} · Shot {item['shot']} — {item['setting'][:60]}",
                "",
                f"> {item['prompt']}",
                "",
                f"- Negative: `{item['negative_prompt']}`",
                f"- Duration: {item['duration_sec']}s · Emotion: {item['emotion']}",
                "",
            ]
        if clips:
            lines += ["## Rendered animatics", ""]
            for clip in clips:
                lines.append(f"- [Seq {clip['sequence']} shot {clip['shot']}]({clip['url']})")
            lines.append("")
        return "\n".join(lines)
