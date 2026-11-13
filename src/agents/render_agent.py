"""Render agent: EDL, reel assembly and delivery deliverables.

The agent builds a real edit decision list from the scoped shots, assembles the
best available clips (A/V-aligned > animatic > storyboard still) into a reel with
FFmpeg, and emits the delivery plan for theatrical, digital, social and DCP.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from src.agents.base import BaseAgent
from src.models.schemas import AgentResult, PipelineContext, RenderOutput


class RenderAgent(BaseAgent):
    def __init__(self):
        super().__init__("render_agent")

    def process(self, ctx: PipelineContext) -> AgentResult:
        if not ctx.film:
            return AgentResult(agent_name=self.name, output=[])

        run_dir = self.run_dir(ctx)
        shots = list(self.scoped_shots(ctx))
        limit = self.shot_limit(ctx, len(shots))
        shots = shots[:limit]

        synced = self._load(ctx, f"lipsync_agent/{run_dir}/lipsync_plan.json")
        animatic = self._load(ctx, f"animation_agent/{run_dir}/animation_plan.json")
        storyboard = self._load(ctx, f"storyboard_agent/{run_dir}/storyboard.json")

        synced_by_shot = {str(c["shot"]): c for c in synced.get("synced_clips", [])}
        clips_by_shot = {str(c["shot"]): c for c in animatic.get("clips", [])}
        frames_by_shot = {
            str(f.get("number", "")): f for f in storyboard.get("rendered", [])
        }

        renders: list[RenderOutput] = []
        edl: list[dict] = []
        timeline: list[Path] = []
        record = 0.0
        for act, seq, shot in shots:
            source_rel = ""
            source_kind = "planned"
            if str(shot.number) in synced_by_shot:
                source_rel = synced_by_shot[str(shot.number)]["relative"]
                source_kind = "av-aligned"
            elif str(shot.number) in clips_by_shot:
                source_rel = clips_by_shot[str(shot.number)]["relative"]
                source_kind = "animatic"
            elif str(shot.number) in frames_by_shot:
                source_rel = frames_by_shot[str(shot.number)].get("relative", "")
                source_kind = "still"

            source_path = None
            if source_rel:
                try:
                    candidate = self.studio().artifacts.path(source_rel)
                    if candidate.exists():
                        source_path = candidate
                except ValueError:
                    source_path = None

            if source_kind == "still" and source_path and ctx.media_enabled and ctx.video_enabled:
                # Promote a still into a clip so the reel has continuous motion.
                clip_rel = f"render_agent/{run_dir}/clips/seq{seq.number:02d}_shot{shot.number.replace('.', '-')}.mp4"
                try:
                    self.studio().providers.video.still_to_clip(
                        source_path,
                        self.studio().artifacts.path(clip_rel),
                        max(1.0, shot.duration_sec),
                        width=960, height=540, fps=24,
                    )
                    source_rel = clip_rel
                    source_path = self.studio().artifacts.path(clip_rel)
                    source_kind = "animatic"
                except Exception:
                    pass

            duration = max(1.0, float(shot.duration_sec))
            edl.append({
                "event": len(edl) + 1,
                "act": act.number,
                "sequence": seq.number,
                "shot": shot.number,
                "source": source_rel or "",
                "source_kind": source_kind,
                "record_in": round(record, 2),
                "record_out": round(record + duration, 2),
                "duration_sec": round(duration, 2),
                "lens": shot.lens,
                "camera": shot.camera_movement,
                "emotion": shot.emotion_context,
                "dialogue_lines": len(shot.dialog),
            })
            record += duration
            if source_kind != "planned" and source_path and source_path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}:
                timeline.append(source_path)

            renders.append(RenderOutput(
                sequence_num=seq.number,
                shot_number=shot.number,
                final_path=source_rel or f"(planned) render_agent/{run_dir}/final/seq{seq.number:02d}_{shot.number}.mp4",
                resolution="1920x1080",
                bitrate_mbps=24,
            ))

        reel = self._assemble(ctx, timeline, run_dir)
        subtitles = self.studio().artifacts.path(f"voice_agent/{run_dir}/subtitles.srt")

        editable = {
            "film": ctx.film.title,
            "scope": ctx.scope,
            "total_shots": len(renders),
            "record_duration_sec": round(record, 2),
            "edl": edl,
            "reel": reel,
            "subtitles": "/artifacts/voice_agent/%s/subtitles.srt" % run_dir if subtitles.exists() else None,
            "deliverables": self._deliverables(ctx),
            "colour_pipeline": {
                "working_space": "ACEScg",
                "display": "Rec.709 / DCI-P3",
                "lut": "ruthambhara_teal_amber_v3",
                "notes": "Emotion-driven grade: anger=amber/charcoal, grief=desaturated blue, joy=gold.",
            },
            "audio": {
                "dialogue_reel": ctx.artifacts.get("voice", {}).get("reel"),
                "stems": ["dialogue", "music", "ambience", "effects"],
                "loudness_target": "-23 LUFS (EBU R128)",
            },
        }
        self.save_json(ctx, "render_manifest.json", editable)
        self.save_text(ctx, "edl.csv", self._edl_csv(edl))
        self.save_text(ctx, "render_report.md", self._markdown(ctx, editable, reel))

        ctx.render_manifest = editable
        ctx.artifacts["render"] = {
            "shots": len(renders),
            "record_duration_sec": round(record, 2),
            "reel": reel.get("url") if reel else None,
            "editor": "ffmpeg" if self.studio().providers.video.available() else "manifest",
            "manifest": f"render_agent/{run_dir}/render_manifest.json",
            "edl": f"render_agent/{run_dir}/edl.csv",
        }

        self.remember(
            f"Render: {len(renders)} shots, {round(record, 1)}s timeline, "
            f"reel={'yes' if reel else 'planned'} for {ctx.film.title}.",
            key=f"render:{run_dir}",
            tags=["render", "edl", "delivery"],
            metadata={"reel": bool(reel)},
        )

        return AgentResult(agent_name=self.name, output=renders)

    # ── helpers ──────────────────────────────────────────────────────────
    def _load(self, ctx: PipelineContext, relative: str) -> dict:
        path = self.studio().artifacts.path(relative)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _assemble(self, ctx: PipelineContext, clips: list[Path], run_dir: str) -> dict | None:
        if not clips or not ctx.media_enabled or not ctx.video_enabled:
            return None
        if not self.studio().providers.video.available():
            return None
        target_rel = f"render_agent/{run_dir}/final/ruthambhara_reel.mp4"
        target = self.studio().artifacts.path(target_rel)
        try:
            self.studio().providers.video.concat(clips, target)
            if not target.exists():
                return None
            return {
                "relative": target_rel,
                "url": self.artifact_url(target_rel),
                "clips": len(clips),
                "bytes": target.stat().st_size,
            }
        except Exception as exc:  # pragma: no cover - ffmpeg optional
            self.logger.warning(f"reel assembly failed: {exc}")
            return None

    @staticmethod
    def _deliverables(ctx: PipelineContext) -> list[dict]:
        return [
            {"name": "Theatrical DCP", "resolution": "4096x1716", "aspect": "2.39:1",
             "codec": "JPEG2000", "audio": "5.1 / Atmos", "status": "planned"},
            {"name": "Digital master", "resolution": "3840x2160", "aspect": "1.90:1",
             "codec": "ProRes 4444", "audio": "5.1", "status": "planned"},
            {"name": "Streaming", "resolution": "1920x1080", "aspect": "16:9",
             "codec": "H.264 24 Mbps", "audio": "AAC 320k", "status": "planned"},
            {"name": "Social vertical", "resolution": "1080x1920", "aspect": "9:16",
             "codec": "H.264 12 Mbps", "audio": "AAC 192k", "status": "planned"},
            {"name": "Animatic reel", "resolution": "960x540", "aspect": "16:9",
             "codec": "H.264", "audio": "AAC", "status": "delivered" if ctx.render_manifest else "in-progress"},
        ]

    @staticmethod
    def _edl_csv(edl: list[dict]) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(edl[0].keys()) if edl else ["event"])
        writer.writeheader()
        for row in edl:
            writer.writerow(row)
        return buffer.getvalue()

    @staticmethod
    def _markdown(ctx: PipelineContext, manifest: dict, reel: dict | None) -> str:
        lines = [
            f"# {ctx.film.title} — Render Manifest",
            "",
            f"**Shots:** {manifest['total_shots']} · "
            f"**Timeline:** {manifest['record_duration_sec']}s · **Scope:** {manifest['scope']}",
            "",
        ]
        if reel:
            lines += ["## Animatic reel", "", f"[Open reel]({reel['url']})", ""]
        lines += [
            "## Deliverables",
            "",
            "| Deliverable | Resolution | Aspect | Codec | Audio | Status |",
            "|-------------|------------|--------|-------|-------|--------|",
        ]
        for item in manifest["deliverables"]:
            lines.append(
                f"| {item['name']} | {item['resolution']} | {item['aspect']} | "
                f"{item['codec']} | {item['audio']} | {item['status']} |"
            )
        lines += [
            "",
            "## Colour pipeline",
            "",
            f"- Working space: **{manifest['colour_pipeline']['working_space']}**",
            f"- Display: {manifest['colour_pipeline']['display']}",
            f"- LUT: `{manifest['colour_pipeline']['lut']}`",
            f"- {manifest['colour_pipeline']['notes']}",
            "",
            "## Audio",
            "",
            f"- Loudness target: {manifest['audio']['loudness_target']}",
            f"- Stems: {', '.join(manifest['audio']['stems'])}",
            "",
            "## Edit decision list",
            "",
            "| # | Seq | Shot | Kind | In | Out | Dur | Source |",
            "|---|-----|------|------|----|-----|-----|--------|",
        ]
        for row in manifest["edl"][:40]:
            lines.append(
                f"| {row['event']} | {row['sequence']} | {row['shot']} | {row['source_kind']} | "
                f"{row['record_in']} | {row['record_out']} | {row['duration_sec']} | "
                f"`{row['source'] or '—'}` |"
            )
        return "\n".join(lines) + "\n"
