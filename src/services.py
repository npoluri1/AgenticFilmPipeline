"""Application services: the studio runtime, pipeline runner and script cache.

``studio`` is the single composition root used by agents, the REST API, the MCP
server and the CLI.  Everything is process-local and free-first, with graceful
degradation when optional providers are missing.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Optional

from src.config import resolve_script_path, settings
from src.core.events import ArtifactStore, EventBus, JobManager, RunStore, new_id, utcnow
from src.evals import EvalStore, PipelineEvaluator
from src.guardrails import ApprovalGate, AuditLog, GuardrailEngine
from src.memory import MemoryStore
from src.models.model_registry import registry as model_registry
from src.models.schemas import PipelineContext, PipelineMode
from src.observability import JsonlExporter, LogBuffer, MetricsRegistry, Tracer
from src.providers import registry as provider_registry
from src.rag import rag_engine
from src.utils.logger import get_logger

logger = get_logger("services")

STAGE_PROGRESS = {
    "script_agent": ("screenplay intelligence", 8),
    "storyboard_agent": ("storyboard keyframes", 22),
    "character_agent": ("character bible", 34),
    "voice_agent": ("voice & subtitles", 48),
    "animation_agent": ("animatics", 62),
    "lipsync_agent": ("A/V alignment", 72),
    "render_agent": ("reel assembly", 86),
    "quality_agent": ("quality gate", 96),
}


class ScriptService:
    """Parses and caches the screenplay; exposes a structured catalog."""

    def __init__(self, guardrails: GuardrailEngine):
        self.guardrails = guardrails
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[float, Any]] = {}

    def load(self, path: Optional[str] = None):
        from src.readers.ruthambhara_reader import RuthambharaReader

        resolved = resolve_script_path(path)
        if not resolved.exists():
            raise FileNotFoundError(f"screenplay not found: {resolved}")
        key = str(resolved.resolve())
        mtime = resolved.stat().st_mtime
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] == mtime:
                return cached[1]
        text = resolved.read_text(encoding="utf-8")
        self.guardrails.check_script(text)
        film = RuthambharaReader().read(str(resolved))
        with self._lock:
            self._cache[key] = (mtime, film)
        return film

    def path(self, path: Optional[str] = None) -> Path:
        return resolve_script_path(path)

    def catalog(self, path: Optional[str] = None) -> dict:
        film = self.load(path)
        return {
            "title": film.title,
            "telugu_title": film.telugu_title,
            "runtime": film.runtime_str,
            "runtime_minutes": film.runtime_minutes,
            "languages": film.languages,
            "aspect_ratio": film.aspect_ratio,
            "cast": [
                {"role": member.role, "actor": member.actor, "function": member.function}
                for member in film.cast
            ],
            "music_themes": [
                {
                    "name": theme.name,
                    "telugu_name": theme.telugu_name,
                    "description": theme.description,
                    "instruments": theme.instruments,
                    "usage_rule": theme.usage_rule,
                }
                for theme in film.music_themes
            ],
            "acts": [
                {
                    "number": act.number,
                    "english_subtitle": act.english_subtitle,
                    "telugu_subtitle": act.telugu_subtitle,
                    "start_time": act.start_time,
                    "end_time": act.end_time,
                    "sequences": [
                        {
                            "number": seq.number,
                            "english_name": seq.english_name,
                            "telugu_name": seq.telugu_name,
                            "runtime_minutes": seq.runtime_minutes,
                            "shots": [shot.__dict__ for shot in seq.shots],
                        }
                        for seq in act.sequences
                    ],
                }
                for act in film.acts
            ],
            "total_acts": len(film.acts),
            "total_sequences": sum(len(act.sequences) for act in film.acts),
            "total_shots": sum(len(seq.shots) for act in film.acts for seq in act.sequences),
        }


class PipelineService:
    """Owns run lifecycle: context construction, execution, events and evals."""

    def __init__(self, studio: "StudioService"):
        self.studio = studio
        self._lock = threading.Lock()

    # ── option handling ──────────────────────────────────────────────────
    def default_options(self, overrides: Optional[dict] = None) -> dict:
        options = {
            "mode": settings.default_mode,
            "language": "te",
            "scope": settings.default_scope,
            "render_media": settings.render_media,
            "render_video": settings.render_video,
            "sample_sequences": settings.sample_sequences,
            "max_shots": settings.sample_max_shots,
            "quality_threshold": settings.quality_threshold,
            "max_repair_loops": settings.max_repair_loops,
            "tier": settings.default_tier,
            "require_approval": settings.require_approval,
            "index_rag": True,
            "eval": True,
        }
        for key, value in (overrides or {}).items():
            if value is not None:
                options[key] = value
        if options["scope"] == "full":
            options.setdefault("max_shots", settings.max_render_shots or 0)
        return options

    def _context(self, run_id: str, options: dict, script_path: str) -> PipelineContext:
        return PipelineContext(
            pipeline_id=run_id,
            mode=PipelineMode(str(options.get("mode", "hybrid"))),
            source_script_path=script_path,
            language=str(options.get("language", "te")),
            total_duration_minutes=205.0,
            model_selections=dict(options.get("model_selections") or {}),
            tier=str(options.get("tier", "free")),
            run_id=run_id,
            options=options,
        )

    # ── public API ───────────────────────────────────────────────────────
    def submit(self, overrides: Optional[dict] = None) -> dict:
        options = self.default_options(overrides)
        script_path = str(self.studio.script.path(options.get("script_path")))
        run = self.studio.runs.create(
            kind="pipeline",
            meta={
                "script_path": script_path,
                "mode": options["mode"],
                "scope": options["scope"],
                "language": options["language"],
                "render_media": options["render_media"],
                "render_video": options["render_video"],
            },
        )
        run_id = run["id"]
        self.studio.jobs.submit(run_id, self._execute, run_id, options, script_path)
        return run

    def run(self, overrides: Optional[dict] = None) -> dict:
        options = self.default_options(overrides)
        script_path = str(self.studio.script.path(options.get("script_path")))
        run = self.studio.runs.create(
            kind="pipeline",
            meta={
                "script_path": script_path,
                "mode": options["mode"],
                "scope": options["scope"],
                "language": options["language"],
                "render_media": options["render_media"],
                "render_video": options["render_video"],
            },
        )
        return self._execute(run["id"], options, script_path)

    def _execute(self, run_id: str, options: dict, script_path: str) -> dict:
        from src.graph_engine import FilmGraphRunner

        started = time.time()
        self.studio.runs.update(
            run_id, status="running", started_at=utcnow(), stage="starting", progress=0.02
        )
        self.studio.events.stage(run_id, "starting", 0.02)
        self.studio.metrics.inc("afp_pipeline_runs_total", labels={"scope": str(options["scope"])})

        try:
            text = Path(script_path).read_text(encoding="utf-8")
            guard = self.studio.guardrails.check_script(text)
            self.studio.audit.record(
                "pipeline.start", "agent", run_id, f"scope={options['scope']}", outcome="ok"
            )
            options = {**options, "guardrail_score": guard.score}

            ctx = self._context(run_id, options, script_path)
            runner = FilmGraphRunner(on_event=lambda name, data: self._bridge(run_id, name, data))
            with self.studio.tracer.span("pipeline.run", run_id, {"scope": options["scope"]}):
                graph_result = runner.run(
                    ctx, max_repair_loops=int(options.get("max_repair_loops", 2))
                )

            self.studio.events.stage(run_id, "finalising", 0.98)
            film = ctx.film
            if film and options.get("index_rag", True):
                try:
                    self.studio.rag.ensure(film, script_path)
                except Exception as exc:  # pragma: no cover - index optional
                    logger.warning(f"RAG index failed: {exc}")

            evaluation = None
            if options.get("eval", True):
                try:
                    evaluation = self.studio.evaluator.evaluate(ctx, graph_result)
                except Exception as exc:  # pragma: no cover
                    logger.warning(f"evaluation failed: {exc}")

            result = {
                "run_id": run_id,
                "status": "completed",
                "film": self._film_payload(film),
                "analysis": ctx.analysis,
                "artifacts": ctx.artifacts,
                "quality": ctx.artifacts.get("quality", {}),
                "evaluation": evaluation,
                "graph": graph_result.to_dict(),
                "agents": [
                    {
                        "name": r.agent_name,
                        "status": r.status.value,
                        "duration_sec": round(r.duration_sec, 3),
                        "error": r.error,
                    }
                    for r in graph_result.results
                ],
                "providers": self.studio.providers.status(),
                "errors": ctx.errors,
                "elapsed_sec": round(time.time() - started, 2),
                "options": {k: v for k, v in options.items() if k != "guardrail_score"},
                "guardrail": guard.to_dict(),
            }

            approval = None
            status = "completed"
            if options.get("require_approval"):
                approval = self.studio.approvals.request(
                    run_id,
                    "quality_gate",
                    f"Quality mean {result['quality'].get('mean_score', 0)} — approve delivery?",
                    {"quality": result["quality"]},
                )
                status = "awaiting_approval"

            self.studio.runs.update(
                run_id,
                status=status,
                progress=1.0,
                stage="completed",
                finished_at=utcnow(),
                result=result,
            )
            self.studio.events.stage(run_id, "completed", 1.0, status=status)
            self.studio.memory.summarize_run({
                "id": run_id,
                "status": status,
                "result": {
                    "film": result["film"].get("title"),
                    "quality": result["quality"].get("mean_score"),
                    "artifacts": list(ctx.artifacts.keys()),
                },
            })
            self.studio.metrics.observe(
                "afp_pipeline_duration_seconds", time.time() - started,
                labels={"scope": str(options["scope"])},
            )
            self.studio.metrics.gauge(
                "afp_quality_mean",
                float(result["quality"].get("mean_score", 0) or 0),
                labels={"scan": "latest"},
            )
            self.studio.exporter.export("runs", {
                "run_id": run_id,
                "scope": options["scope"],
                "elapsed_sec": result["elapsed_sec"],
                "quality": result["quality"].get("mean_score"),
                "evaluation": (evaluation or {}).get("overall"),
                "status": status,
            })
            self.studio.logs.add("info", "pipeline completed", run_id=run_id, status=status)
            return {
                **result,
                "status": status,
                "approval": approval,
            }
        except Exception as exc:  # noqa: BLE001 - surface failure to the run store
            logger.exception("pipeline failed")
            self.studio.runs.update(
                run_id,
                status="failed",
                stage="failed",
                error=str(exc),
                finished_at=utcnow(),
                progress=1.0,
            )
            self.studio.events.emit(run_id, "run.failed", {"error": str(exc)}, level="error")
            self.studio.metrics.inc("afp_pipeline_failures_total")
            self.studio.logs.add("error", "pipeline failed", run_id=run_id, error=str(exc))
            self.studio.audit.record("pipeline.failed", "agent", run_id, str(exc), outcome="error")
            return {"run_id": run_id, "status": "failed", "error": str(exc)}

    def _bridge(self, run_id: str, event: str, data: dict) -> None:
        try:
            self.studio.events.emit(run_id, event, data)
            agent = data.get("agent", "")
            if event == "agent.started" and agent in STAGE_PROGRESS:
                stage, progress = STAGE_PROGRESS[agent]
                self.studio.events.stage(run_id, stage, progress / 100.0, agent=agent)
            if event == "agent.finished":
                self.studio.metrics.inc(
                    "afp_agent_runs_total",
                    labels={"agent": agent, "status": str(data.get("status", ""))},
                )
                self.studio.metrics.observe(
                    "afp_agent_duration_seconds", float(data.get("duration_sec", 0)),
                    labels={"agent": agent},
                )
        except KeyError:
            pass
        except Exception:
            logger.debug("event bridge failed", exc_info=True)

    @staticmethod
    def _film_payload(film) -> dict:
        if not film:
            return {}
        return {
            "title": film.title,
            "telugu_title": film.telugu_title,
            "runtime_minutes": film.runtime_minutes,
            "runtime": film.runtime_str,
            "languages": film.languages,
            "aspect_ratio": film.aspect_ratio,
            "acts": len(film.acts),
            "sequences": sum(len(act.sequences) for act in film.acts),
            "shots": sum(len(seq.shots) for act in film.acts for seq in act.sequences),
            "cast": len(film.cast),
            "music_themes": len(film.music_themes),
            "music_cues": len(film.music_cues),
        }

    def get(self, run_id: str) -> Optional[dict]:
        return self.studio.runs.get(run_id)

    def list(self, limit: int = 20) -> list[dict]:
        return self.studio.runs.list(limit=limit, kind="pipeline")

    def status(self) -> dict:
        latest = self.list(limit=1)
        return {
            "status": "running" if self.studio.jobs.running() else "idle",
            "running_jobs": self.studio.jobs.running(),
            "total_runs": self.studio.runs.count(),
            "latest": latest[0] if latest else None,
            "script_loaded": self.studio.script.path().exists(),
        }


class StudioService:
    """Composition root for the whole film studio."""

    def __init__(self):
        self.settings = settings
        self.providers = provider_registry
        self.artifacts = ArtifactStore()
        self.runs = RunStore()
        self.events = EventBus(self.runs)
        self.jobs = JobManager(max_workers=settings.max_workers)
        self.memory = MemoryStore()
        self.guardrails = GuardrailEngine(settings.guardrail_strict, settings.max_script_chars)
        self.audit = AuditLog()
        self.approvals = ApprovalGate()
        self.tracer = Tracer(self.runs)
        self.metrics = MetricsRegistry()
        self.logs = LogBuffer()
        self.exporter = JsonlExporter()
        self.evals = EvalStore()
        self.evaluator = PipelineEvaluator(self.evals)
        self.rag = rag_engine
        self.script = ScriptService(self.guardrails)
        self.models = model_registry
        self.pipeline = PipelineService(self)
        self.started_at = utcnow()

    # ── knowledge ────────────────────────────────────────────────────────
    def ask(self, query: str, k: int = 6) -> dict:
        film = self.script.load()
        self.rag.ensure(film, str(self.script.path()))
        answer = self.rag.ask(query, k=k)
        self.memory.remember(query, scope="semantic", key=f"qa:{query[:60]}", tags=["qa"])
        return answer

    def index(self, force: bool = False) -> dict:
        film = self.script.load()
        return self.rag.ensure(film, str(self.script.path()), force=force)

    def snapshot(self) -> dict:
        latest = self.pipeline.list(limit=1)
        latest_run = self.runs.get(latest[0]["id"]) if latest else None
        return {
            "app": settings.app_name,
            "version": settings.version,
            "environment": settings.environment,
            "started_at": self.started_at,
            "script": {
                "path": str(self.script.path()),
                "exists": self.script.path().exists(),
            },
            "config": settings.as_dict(),
            "pipeline": self.pipeline.status(),
            "runs": self.pipeline.list(limit=12),
            "latest": latest_run,
            "providers": self.providers.flat_status(),
            "provider_status": self.providers.status(),
            "rag": self.rag.stats(),
            "graph": self.rag.graph_payload(limit=80) if self.rag.chunks else {},
            "memory": {"stats": self.memory.stats(), "recent": self.memory.list(limit=8)},
            "evals": self.evals.summary(),
            "artifacts": self.artifacts.manifest(),
            "models": self.models.to_dict(),
            "approvals": self.approvals.list(),
            "audit": self.audit.list(limit=12),
            "metrics": self.metrics.snapshot(),
            "logs": self.logs.list(limit=30),
            "agents": [
                {
                    "name": name,
                    "label": label,
                    "description": description,
                    "progress": progress,
                }
                for name, (label, description, progress) in _agent_meta().items()
            ],
        }


def _agent_meta() -> dict[str, tuple[str, str, int]]:
    from src.graph_engine import AGENT_LABELS

    return {
        name: (label, description, STAGE_PROGRESS[name][1])
        for name, (label, description) in AGENT_LABELS.items()
    }


studio = StudioService()
