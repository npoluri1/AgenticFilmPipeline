import concurrent.futures

from src.agents.base import BaseAgent
from src.agents.script_agent import ScriptAgent
from src.agents.storyboard_agent import StoryboardAgent
from src.agents.character_agent import CharacterAgent
from src.agents.voice_agent import VoiceAgent
from src.agents.animation_agent import AnimationAgent
from src.agents.lipsync_agent import LipSyncAgent
from src.agents.render_agent import RenderAgent
from src.agents.quality_agent import QualityAgent
from src.models.schemas import (
    PipelineContext, PipelineMode, AgentResult, AgentStatus,
)
from src.utils.logger import get_logger


class AgentSupervisor:
    def __init__(self):
        self.logger = get_logger("supervisor")
        self.agents: dict[str, BaseAgent] = {
            "script_agent": ScriptAgent(),
            "storyboard_agent": StoryboardAgent(),
            "character_agent": CharacterAgent(),
            "voice_agent": VoiceAgent(),
            "animation_agent": AnimationAgent(),
            "lipsync_agent": LipSyncAgent(),
            "render_agent": RenderAgent(),
            "quality_agent": QualityAgent(),
        }
        self.dag: dict[str, list[str]] = {
            "script_agent": [],
            "storyboard_agent": ["script_agent"],
            "character_agent": ["script_agent"],
            "voice_agent": ["script_agent"],
            "animation_agent": ["character_agent", "storyboard_agent"],
            "lipsync_agent": ["voice_agent", "animation_agent"],
            "render_agent": ["lipsync_agent"],
            "quality_agent": ["render_agent"],
        }

    def run(self, ctx: PipelineContext) -> list[AgentResult]:
        results = []
        if ctx.mode == PipelineMode.SEQUENTIAL:
            results = self._run_sequential(ctx)
        elif ctx.mode == PipelineMode.PARALLEL:
            results = self._run_parallel(ctx)
        elif ctx.mode == PipelineMode.HYBRID:
            results = self._run_hybrid(ctx)
        return results

    def _run_sequential(self, ctx: PipelineContext) -> list[AgentResult]:
        self.logger.info("Mode: SEQUENTIAL")
        results = []
        for name in self.dag:
            agent = self.agents[name]
            result = agent.run(ctx)
            ctx.results[name] = result
            results.append(result)
            if result.status == AgentStatus.FAILED:
                self.logger.error(f"Pipeline halted at {name}")
                break
        return results

    def _run_parallel(self, ctx: PipelineContext) -> list[AgentResult]:
        self.logger.info("Mode: PARALLEL (topological)")
        results = []
        completed: set[str] = set()

        while len(completed) < len(self.dag):
            ready = [
                name for name, deps in self.dag.items()
                if name not in completed and all(d in completed for d in deps)
            ]
            if not ready:
                self.logger.error("Deadlock detected in DAG")
                break

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(ready)) as pool:
                future_map = {pool.submit(self.agents[name].run, ctx): name for name in ready}
                for future in concurrent.futures.as_completed(future_map):
                    name = future_map[future]
                    result = future.result()
                    ctx.results[name] = result
                    results.append(result)
                    completed.add(name)
                    if result.status == AgentStatus.FAILED:
                        self.logger.error(f"Agent {name} failed")
        return results

    def _run_hybrid(self, ctx: PipelineContext) -> list[AgentResult]:
        self.logger.info("Mode: HYBRID (sequential groups, parallel within)")
        results = []

        def run_group(names: list[str]) -> list[AgentResult]:
            group_results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(names)) as pool:
                future_map = {pool.submit(self.agents[n].run, ctx): n for n in names}
                for future in concurrent.futures.as_completed(future_map):
                    r = future.result()
                    ctx.results[r.agent_name] = r
                    group_results.append(r)
            return group_results

        group1 = ["script_agent"]
        group2 = ["storyboard_agent", "character_agent", "voice_agent"]
        group3 = ["animation_agent"]
        group4 = ["lipsync_agent"]
        group5 = ["render_agent"]
        group6 = ["quality_agent"]

        for group in [group1, group2, group3, group4, group5, group6]:
            results.extend(run_group(group))

        return results

    def get_pipeline_summary(self, results: list[AgentResult], ctx: PipelineContext) -> str:
        lines = ["", "=" * 60,
                 "  RUTHAMBHARA — Agentic Film Pipeline Report",
                 "=" * 60]
        if ctx.film:
            lines.append(f"  Film: {ctx.film.title} ({ctx.film.telugu_title})")
            total_seq = sum(len(a.sequences) for a in ctx.film.acts)
            total_shots = sum(len(s.shots) for a in ctx.film.acts for s in a.sequences)
            lines.append(f"  Runtime: {ctx.film.runtime_str}")
            lines.append(f"  Languages: {', '.join(ctx.film.languages)}")
            lines.append(f"  Cast: {len(ctx.film.cast)} members")
            lines.append(f"  Acts: {len(ctx.film.acts)}")
            lines.append(f"  Sequences: {total_seq}")
            lines.append(f"  Shots: {total_shots}")
            lines.append(f"  Music Themes: {len(ctx.film.music_themes)}")
            lines.append("=" * 60)

        lines.append(f"\n  {'Agent':<22} {'Status':<10} {'Time':<8}")
        lines.append("  " + "-" * 42)
        for r in results:
            icon = {AgentStatus.COMPLETED: "OK", AgentStatus.FAILED: "FAIL",
                    AgentStatus.RUNNING: "...", AgentStatus.PENDING: "WAIT",
                    AgentStatus.SKIPPED: "SKIP"}.get(r.status, "?")
            lines.append(f"  [{icon:4s}] {r.agent_name:<20s} {r.duration_sec:7.2f}s")
        total = sum(r.duration_sec for r in results)
        lines.append(f"\n  Pipeline compute time: {total:.2f}s")

        if ctx.quality_reports:
            passed = sum(1 for r in ctx.quality_reports if r.passed)
            lines.append(f"\n  Quality: {passed}/{len(ctx.quality_reports)} sequences passed")
            for r in ctx.quality_reports:
                if not r.passed:
                    for issue in r.issues:
                        lines.append(f"    ! Seq {r.sequence_num:02d}: {issue}")

        return "\n".join(lines)
