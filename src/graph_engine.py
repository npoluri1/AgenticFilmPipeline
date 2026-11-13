"""LangGraph-native orchestration with a deterministic fallback.

The film pipeline is expressed as a state graph:

    script ─┬─> storyboard ─┐
            ├─> character ──┼─> animation -> lipsync -> render -> quality
            └─> voice ──────┘                                   │
                                                    repair <────┘ (bounded loop)

Quality drives a bounded repair loop.  When the optional ``langgraph`` package
is present the graph is compiled and executed by LangGraph; otherwise the same
node functions run through a small built-in superstep executor.
"""
from __future__ import annotations

import concurrent.futures
import threading
from dataclasses import dataclass
from typing import Annotated, Any, Callable, Optional, TypedDict

from src.agents.animation_agent import AnimationAgent
from src.agents.base import BaseAgent
from src.agents.character_agent import CharacterAgent
from src.agents.lipsync_agent import LipSyncAgent
from src.agents.quality_agent import QualityAgent
from src.agents.render_agent import RenderAgent
from src.agents.script_agent import ScriptAgent
from src.agents.storyboard_agent import StoryboardAgent
from src.agents.voice_agent import VoiceAgent
from src.models.schemas import AgentResult, AgentStatus, PipelineContext, PipelineMode
from src.utils.logger import get_logger

logger = get_logger("graph")

try:
    from langgraph.graph import END, StateGraph as LangStateGraph  # type: ignore
    LANGGRAPH_AVAILABLE = True
except Exception:  # pragma: no cover
    END = "__end__"
    LangStateGraph = None
    LANGGRAPH_AVAILABLE = False


AGENT_ORDER = [
    "script_agent",
    "storyboard_agent",
    "character_agent",
    "voice_agent",
    "animation_agent",
    "lipsync_agent",
    "render_agent",
    "quality_agent",
]

AGENT_LABELS = {
    "script_agent": ("Script", "Screenplay intelligence, parsing & structure"),
    "storyboard_agent": ("Storyboard", "Procedural keyframes & shot design"),
    "character_agent": ("Character", "Character bible, portraits & consistency"),
    "voice_agent": ("Voice", "Multilingual TTS & subtitle timing"),
    "animation_agent": ("Animation", "Animatics & free-video prompt plans"),
    "lipsync_agent": ("LipSync", "Audio/visual alignment & sync plan"),
    "render_agent": ("Render", "EDL, reel assembly & colour plan"),
    "quality_agent": ("Quality", "Rubric evaluation & governance gate"),
}


def _merge_dicts(left: Any, right: Any) -> dict:
    """LangGraph reducer used by parallel branches writing to the same channel."""
    return {**(left or {}), **(right or {})}


# Declared at module scope so LangGraph can resolve the ``Annotated`` reducers
# from this module's globals (``from __future__ import annotations`` stores the
# annotations lazily as strings).
class FilmState(TypedDict, total=False):
    agents: Annotated[dict, _merge_dicts]
    outputs: Annotated[dict, _merge_dicts]
    repair_loops: int
    status: str


def _agent_factory(name: str) -> BaseAgent:
    return {
        "script_agent": ScriptAgent,
        "storyboard_agent": StoryboardAgent,
        "character_agent": CharacterAgent,
        "voice_agent": VoiceAgent,
        "animation_agent": AnimationAgent,
        "lipsync_agent": LipSyncAgent,
        "render_agent": RenderAgent,
        "quality_agent": QualityAgent,
    }[name]()


@dataclass
class GraphRunResult:
    results: list[AgentResult]
    engine: str
    repair_loops: int = 0
    quality_passed: bool = False

    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "repair_loops": self.repair_loops,
            "quality_passed": self.quality_passed,
            "agents": [
                {
                    "name": r.agent_name,
                    "status": r.status.value,
                    "duration_sec": round(r.duration_sec, 3),
                    "error": r.error,
                }
                for r in self.results
            ],
        }


class FilmGraphRunner:
    """Executes the 8-agent film pipeline with LangGraph (or fallback)."""

    def __init__(self, on_event: Optional[Callable[[str, dict], None]] = None):
        self.agents: dict[str, BaseAgent] = {name: _agent_factory(name) for name in AGENT_ORDER}
        self.on_event = on_event
        self._lock = threading.Lock()

    # ── graph definition ─────────────────────────────────────────────────
    def edges(self, mode: PipelineMode) -> dict[str, list[str]]:
        if mode == PipelineMode.SEQUENTIAL:
            return {
                "script_agent": ["storyboard_agent"],
                "storyboard_agent": ["character_agent"],
                "character_agent": ["voice_agent"],
                "voice_agent": ["animation_agent"],
                "animation_agent": ["lipsync_agent"],
                "lipsync_agent": ["render_agent"],
                "render_agent": ["quality_agent"],
                "quality_agent": [],
            }
        return {
            "script_agent": ["storyboard_agent", "character_agent", "voice_agent"],
            "storyboard_agent": ["animation_agent"],
            "character_agent": ["animation_agent"],
            "voice_agent": ["animation_agent"],
            "animation_agent": ["lipsync_agent"],
            "lipsync_agent": ["render_agent"],
            "render_agent": ["quality_agent"],
            "quality_agent": [],
        }

    def spec(self, mode: PipelineMode = PipelineMode.HYBRID) -> dict:
        edges = self.edges(mode)
        nodes = [
            {
                "id": name,
                "label": AGENT_LABELS[name][0],
                "description": AGENT_LABELS[name][1],
                "category": "quality" if name == "quality_agent" else "production",
            }
            for name in AGENT_ORDER
        ]
        return {
            "engine": "langgraph" if LANGGRAPH_AVAILABLE else "builtin",
            "mode": mode.value,
            "entry": AGENT_ORDER[0],
            "nodes": nodes,
            "edges": [
                {"source": source, "target": target}
                for source, targets in edges.items()
                for target in targets
            ],
            "loop": {
                "from": "quality_agent",
                "to": "repair",
                "condition": "pass_rate < threshold and loops < max_loops",
            },
        }

    # ── execution ────────────────────────────────────────────────────────
    def run(self, ctx: PipelineContext, max_repair_loops: int = 2) -> GraphRunResult:
        if LANGGRAPH_AVAILABLE:
            try:
                return self._run_langgraph(ctx, max_repair_loops)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(f"LangGraph execution failed, using builtin engine: {exc}")
        return self._run_builtin(ctx, max_repair_loops)

    def _node(self, name: str, ctx: PipelineContext) -> dict:
        agent = self.agents[name]
        if self.on_event:
            self.on_event("agent.started", {"agent": name, "label": AGENT_LABELS[name][0]})
        result = agent.run(ctx)
        ctx.results[name] = result
        if self.on_event:
            self.on_event(
                "agent.finished",
                {
                    "agent": name,
                    "label": AGENT_LABELS[name][0],
                    "status": result.status.value,
                    "duration_sec": round(result.duration_sec, 3),
                    "error": result.error,
                },
            )
        return {
            "agents": {name: {
                "name": name,
                "status": result.status.value,
                "duration_sec": round(result.duration_sec, 3),
                "error": result.error,
            }},
            "outputs": {name: _summarize_output(result.output)},
        }

    def _quality_route(self, ctx: PipelineContext, max_repair_loops: int) -> str:
        if not ctx.quality_reports:
            return "done"
        threshold = float(ctx.options.get("quality_threshold", 0.80))
        pass_rate = sum(1 for r in ctx.quality_reports if r.passed) / len(ctx.quality_reports)
        if pass_rate < threshold and ctx.repair_loop < max_repair_loops:
            return "repair"
        return "done"

    def _repair(self, ctx: PipelineContext, state: dict) -> dict:
        ctx.repair_loop += 1
        if self.on_event:
            self.on_event("graph.repair", {"loop": ctx.repair_loop, "max": ctx.options.get("max_repair_loops", 2)})
        # The repair node advances the bounded loop; the quality node that
        # follows re-scores and applies any artifact repairs.
        return {
            "agents": {"quality_agent": {
                "name": "quality_agent",
                "status": AgentStatus.COMPLETED.value,
                "duration_sec": 0.0,
                "error": None,
            }},
            "repair_loops": ctx.repair_loop,
        }

    def _run_langgraph(self, ctx: PipelineContext, max_repair_loops: int) -> GraphRunResult:
        builder = LangStateGraph(FilmState)
        for name in AGENT_ORDER:
            builder.add_node(name, lambda state, n=name: self._node(n, ctx))
        builder.add_node("repair", lambda state: self._repair(ctx, state))

        edges = self.edges(ctx.mode)
        builder.set_entry_point("script_agent")
        # Group incoming edges so fan-in nodes wait for *all* parents.  LangGraph
        # otherwise executes a node once per incoming edge, duplicating work.
        parents: dict[str, list[str]] = {}
        for source, targets in edges.items():
            for target in targets:
                parents.setdefault(target, []).append(source)
        for target, sources in parents.items():
            if len(sources) > 1:
                builder.add_edge(sources, target)
            else:
                builder.add_edge(sources[0], target)
        # Quality drives the bounded repair loop.
        builder.add_conditional_edges(
            "quality_agent",
            lambda state: self._quality_route(ctx, max_repair_loops),
            {"repair": "repair", "done": END},
        )
        builder.add_edge("repair", "quality_agent")

        graph = builder.compile()
        try:
            graph.invoke({"agents": {}, "outputs": {}, "repair_loops": 0},
                         config={"recursion_limit": 40})
        except TypeError:
            # Older langgraph signature
            graph.invoke({"agents": {}, "outputs": {}, "repair_loops": 0})

        results = [ctx.results[name] for name in AGENT_ORDER if name in ctx.results]
        return GraphRunResult(
            results=results,
            engine="langgraph",
            repair_loops=ctx.repair_loop,
            quality_passed=bool(ctx.quality_reports) and all(r.passed for r in ctx.quality_reports),
        )

    def _run_builtin(self, ctx: PipelineContext, max_repair_loops: int) -> GraphRunResult:
        results: list[AgentResult] = []
        if ctx.mode == PipelineMode.SEQUENTIAL:
            for name in AGENT_ORDER:
                self._node(name, ctx)
                results.append(ctx.results[name])
                if ctx.results[name].status == AgentStatus.FAILED:
                    break
        else:
            edges = self.edges(ctx.mode)
            completed: set[str] = set()
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(AGENT_ORDER) // 2)) as pool:
                while len(completed) < len(AGENT_ORDER):
                    ready = [
                        name for name in AGENT_ORDER
                        if name not in completed
                        and all(dep in completed for dep in _deps(edges, name))
                    ]
                    if not ready:
                        break
                    future_map = {pool.submit(self._node, name, ctx): name for name in ready}
                    for future in concurrent.futures.as_completed(future_map):
                        name = future_map[future]
                        try:
                            future.result()
                        except Exception as exc:  # pragma: no cover
                            ctx.results[name] = AgentResult(name, AgentStatus.FAILED, error=str(exc))
                        completed.add(name)
                        results.append(ctx.results[name])
            results = [ctx.results[name] for name in AGENT_ORDER if name in ctx.results]

        # Complete missing agents (e.g. dependency failure)
        for name in AGENT_ORDER:
            if name not in ctx.results:
                ctx.results[name] = AgentResult(name, AgentStatus.SKIPPED, error="dependency failed")
        results = [ctx.results[name] for name in AGENT_ORDER]

        # Bounded quality repair loop
        while self._quality_route(ctx, max_repair_loops) == "repair":
            self._repair(ctx, {})
            self._node("quality_agent", ctx)
        results = [ctx.results[name] for name in AGENT_ORDER if name in ctx.results]
        return GraphRunResult(
            results=results,
            engine="builtin",
            repair_loops=ctx.repair_loop,
            quality_passed=bool(ctx.quality_reports) and all(r.passed for r in ctx.quality_reports),
        )


def _deps(edges: dict[str, list[str]], name: str) -> list[str]:
    return [source for source, targets in edges.items() if name in targets]


def _summarize_output(output: Any) -> dict:
    if output is None:
        return {}
    if isinstance(output, list):
        return {"items": len(output)}
    if hasattr(output, "__dict__"):
        payload = {
            k: v for k, v in vars(output).items()
            if not isinstance(v, (list, dict)) or len(str(v)) < 200
        }
        for key, value in vars(output).items():
            if isinstance(value, list):
                payload[f"{key}_count"] = len(value)
        return {k: (str(v)[:300] if not isinstance(v, (int, float, bool, type(None))) else v)
                for k, v in payload.items()}
    return {"value": str(output)[:300]}


film_graph_runner = FilmGraphRunner()
