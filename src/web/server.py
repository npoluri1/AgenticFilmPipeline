"""FastAPI application: REST API, SSE streaming, MCP transport and dashboard.

Run with::

    python main.py serve --port 8080

Routes are namespaced under ``/api`` except for a small set of legacy endpoints
(``/script``, ``/scenes``, ``/models``, ``/pipeline/*``) that existing clients
and tests rely on.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.config import ARTIFACTS_DIR, OUTPUT_DIR, settings
from src.mcp_server import handle_http, mcp_registry
from src.models.humanizer import Humanizer, ScriptEnhancer
from src.models.model_registry import registry as model_registry
from src.models.schemas import PipelineMode
from src.readers.ruthambhara_reader import RuthambharaReader
from src.services import studio
from src.utils.logger import get_logger
from src.web.dashboard import dashboard_html

logger = get_logger("web")

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description=(
        "Agentic Telugu feature-film studio: 8-agent LangGraph pipeline, GraphRAG, "
        "MCP tools, evaluations, guardrails and a live dashboard."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=str(ARTIFACTS_DIR)), name="artifacts")

VIDEOS_DIR = OUTPUT_DIR / "videos"
if VIDEOS_DIR.exists():
    app.mount("/videos", StaticFiles(directory=str(VIDEOS_DIR)), name="videos")


# ─────────────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────────────


class RunRequest(BaseModel):
    scope: Optional[str] = Field(default=None, description="sample|analysis|full")
    mode: Optional[str] = Field(default=None, description="hybrid|parallel|sequential")
    language: Optional[str] = None
    tier: Optional[str] = None
    max_shots: Optional[int] = None
    sample_sequences: Optional[int] = None
    render_media: Optional[bool] = None
    render_video: Optional[bool] = None
    quality_threshold: Optional[float] = None
    max_repair_loops: Optional[int] = None
    require_approval: Optional[bool] = None
    eval: Optional[bool] = None
    index_rag: Optional[bool] = None
    script_path: Optional[str] = None
    model_selections: Optional[dict[str, str]] = None


class LegacyRunRequest(BaseModel):
    mode: str = "hybrid"
    language: str = "te"
    scope: str = "sample"
    all_languages: bool = False
    tier: str = "free"
    max_shots: int = 12
    sample_sequences: int = 3
    render_media: bool = False
    render_video: bool = False
    model_selections: dict[str, str] = Field(default_factory=dict)


class AskRequest(BaseModel):
    question: str
    k: int = 6


class ModelSelectionUpdate(BaseModel):
    category: str
    model_id: str
    tier: str = "free"


class ApprovalDecision(BaseModel):
    approved: bool
    by: str = "operator"
    comment: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Root / health
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/")
async def root():
    return {
        "app": settings.app_name,
        "version": settings.version,
        "film": "ఋతంభర — RUTHAMBHARA",
        "dashboard": "/dashboard",
        "docs": "/docs",
        "mcp": "/mcp",
        "endpoints": [
            "/api/dashboard — full studio snapshot",
            "/api/runs — submit a production run (async)",
            "/api/runs/{id}/events — SSE stream",
            "/api/ask — GraphRAG question answering",
            "/api/providers — provider health",
            "/api/evals — evaluation summary",
            "/api/metrics — Prometheus metrics",
            "/mcp — MCP JSON-RPC tool gateway",
            "/script, /scenes, /models, /pipeline/run — legacy endpoints",
            "/artifacts/* — generated media",
        ],
    }


@app.get("/health")
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "timestamp": time.time(),
        "script": str(studio.script.path()),
        "script_exists": studio.script.path().exists(),
        "engine": "langgraph",
        "running_jobs": studio.jobs.running(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard & snapshot
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(dashboard_html())


@app.get("/api/dashboard")
async def api_dashboard():
    snapshot = studio.snapshot()
    snapshot["mcp"] = mcp_registry.stats()
    snapshot["endpoints"] = {"dashboard": "/dashboard", "mcp": "/mcp"}
    return snapshot


@app.get("/api/graph")
async def api_graph(mode: str = "hybrid"):
    from src.graph_engine import film_graph_runner

    try:
        pipeline_mode = PipelineMode(mode)
    except ValueError:
        raise HTTPException(400, f"unknown mode: {mode}")
    return film_graph_runner.spec(pipeline_mode)


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline runs
# ─────────────────────────────────────────────────────────────────────────────


@app.post("/api/runs")
async def submit_run(req: Optional[RunRequest] = Body(default=None)):
    options = req.model_dump(exclude_none=True) if req else {}
    run = studio.pipeline.submit(options)
    return {"run": run, "events_url": f"/api/runs/{run['id']}/events"}


@app.get("/api/runs")
async def list_runs(limit: int = Query(20, ge=1, le=200)):
    return {"runs": studio.pipeline.list(limit=limit)}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    run = studio.pipeline.get(run_id)
    if not run:
        raise HTTPException(404, f"run not found: {run_id}")
    return run


@app.get("/api/runs/{run_id}/result")
async def get_run_result(run_id: str):
    run = studio.pipeline.get(run_id)
    if not run:
        raise HTTPException(404, f"run not found: {run_id}")
    return {
        "run_id": run_id,
        "status": run.get("status"),
        "stage": run.get("stage"),
        "progress": run.get("progress"),
        "error": run.get("error"),
        "result": run.get("result"),
    }


@app.get("/api/runs/{run_id}/artifacts")
async def get_run_artifacts(run_id: str):
    files = [f for f in studio.artifacts.list(limit=2000) if run_id in f["path"]]
    return {"run_id": run_id, "count": len(files), "files": files}


@app.get("/api/runs/{run_id}/events")
async def stream_run_events(run_id: str, request: Request, since: int = 0):
    if not studio.pipeline.get(run_id):
        raise HTTPException(404, f"run not found: {run_id}")

    async def stream():
        cursor = max(0, since)
        while True:
            if await request.is_disconnected():
                break
            events = studio.runs.events_since(run_id, cursor)
            for event in events:
                cursor += 1
                payload = json.dumps(event, ensure_ascii=False, default=str)
                yield f"data: {payload}\n\n"
            run = studio.pipeline.get(run_id) or {}
            terminal = run.get("status") in {"completed", "failed", "awaiting_approval"}
            if terminal and not events:
                final = {
                    "seq": cursor,
                    "type": "run.closed",
                    "level": "info",
                    "data": {
                        "status": run.get("status"),
                        "progress": run.get("progress"),
                        "stage": run.get("stage"),
                        "error": run.get("error"),
                    },
                }
                yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
                break
            await asyncio.sleep(0.35)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge / GraphRAG
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/api/script")
async def api_script():
    return studio.script.catalog()


@app.get("/api/rag/search")
async def rag_search(q: str = Query(..., min_length=2), k: int = Query(6, ge=1, le=20)):
    studio.index()
    return {"query": q, "results": studio.rag.search(q, k=k), "stats": studio.rag.stats()}


@app.get("/api/rag/graph")
async def rag_graph(limit: int = Query(160, ge=1, le=600)):
    studio.index()
    return studio.rag.graph_payload(limit=limit)


@app.post("/api/ask")
async def ask(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(400, "question is required")
    return studio.ask(req.question, k=req.k)


@app.get("/api/memory")
async def memory(q: Optional[str] = None, limit: int = Query(25, ge=1, le=200)):
    if q:
        return {"memories": studio.memory.recall(q, k=limit)}
    return {"memories": studio.memory.list(limit=limit), "stats": studio.memory.stats()}


# ─────────────────────────────────────────────────────────────────────────────
# Observability, evaluation, governance
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/api/providers")
async def providers(refresh: bool = False):
    return studio.providers.status(refresh=refresh)


@app.get("/api/evals")
async def evals(limit: int = Query(25, ge=1, le=200)):
    return {"summary": studio.evals.summary(), "entries": studio.evals.list(limit=limit)}


@app.post("/api/evals/export")
async def export_evals():
    return studio.evals.export_finetune()


@app.get("/api/logs")
async def logs(limit: int = Query(100, ge=1, le=1000), level: str = ""):
    return {"logs": studio.logs.list(level=level, limit=limit)}


@app.get("/api/audit")
async def audit(limit: int = Query(50, ge=1, le=500)):
    return {"audit": studio.audit.list(limit=limit)}


@app.get("/api/approvals")
async def approvals(run_id: Optional[str] = None):
    return {"approvals": studio.approvals.list(run_id=run_id)}


@app.post("/api/approvals/{approval_id}")
async def decide_approval(approval_id: str, decision: ApprovalDecision):
    try:
        result = studio.approvals.decide(
            approval_id, decision.approved, by=decision.by, comment=decision.comment
        )
    except KeyError:
        raise HTTPException(404, f"approval not found: {approval_id}")
    studio.audit.record(
        "approval.decide", decision.by, approval_id,
        "approved" if decision.approved else "rejected",
    )
    return result


@app.get("/api/metrics")
async def metrics_json():
    return studio.metrics.snapshot()


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics_prometheus():
    return PlainTextResponse(studio.metrics.render() or "# no metrics yet\n")


# ─────────────────────────────────────────────────────────────────────────────
# MCP gateway
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/api/mcp/tools")
async def mcp_tools():
    return {
        "server": "ruthambhara-film-studio",
        "tools": mcp_registry.list_tools(),
        "stats": mcp_registry.stats(),
    }


@app.post("/mcp")
@app.post("/api/mcp")
async def mcp_endpoint(payload: Any = Body(...)):
    response = handle_http(payload)
    if isinstance(response, dict) and "id" not in response:
        return {"jsonrpc": "2.0"}
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Legacy endpoints (kept for existing clients and tests)
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/script")
async def get_script(enhanced: bool = Query(False)):
    film = studio.script.load()
    if enhanced:
        film = ScriptEnhancer().enhance_for_human_clarity(film)
    return _film_payload(film)


@app.get("/script/enhanced")
async def get_enhanced_script():
    film = studio.script.load()
    story = Humanizer().render_script_as_story(film)
    return {"story": story, "format": "markdown"}


@app.get("/scenes")
async def get_scenes():
    film = studio.script.load()
    payload = _film_payload(film)
    video_files = {}
    if VIDEOS_DIR.exists():
        for file in VIDEOS_DIR.iterdir():
            if file.suffix.lower() in (".mp4", ".webm", ".mov", ".avi", ".mkv"):
                video_files[file.stem] = file.name
    for act in payload["acts"]:
        for seq in act["sequences"]:
            for shot in seq["shots"]:
                key = f"act{act['number']}_seq{seq['number']}_shot{shot['number'].replace('.', '_')}"
                shot["video_url"] = f"/videos/{video_files[key]}" if key in video_files else None
    return payload


@app.get("/models")
async def get_models():
    return model_registry.to_dict()


@app.post("/models/select")
async def select_model(update: ModelSelectionUpdate):
    model = model_registry.get_model(update.model_id)
    if not model:
        raise HTTPException(404, f"model '{update.model_id}' not found")
    return {
        "selected": {
            "category": update.category,
            "model": model.__dict__,
            "tier": update.tier,
        }
    }


@app.post("/pipeline/run")
async def legacy_run_pipeline(req: LegacyRunRequest):
    if not studio.script.path().exists():
        raise HTTPException(404, f"screenplay not found: {studio.script.path()}")
    options = req.model_dump(exclude={"all_languages"})
    return studio.pipeline.run(options)


@app.get("/pipeline/status")
async def legacy_pipeline_status():
    return studio.pipeline.status()


def _film_payload(film) -> dict:
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
                "total_sequences": len(act.sequences),
                "total_shots": sum(len(seq.shots) for seq in act.sequences),
                "sequences": [
                    {
                        "number": seq.number,
                        "english_name": seq.english_name,
                        "telugu_name": seq.telugu_name,
                        "runtime_minutes": seq.runtime_minutes,
                        "total_shots": len(seq.shots),
                        "shots": [
                            {
                                "number": shot.number,
                                "setting": shot.setting,
                                "duration_sec": shot.duration_sec,
                                "lens": shot.lens or "Standard",
                                "camera_movement": shot.camera_movement or "Static",
                                "visual_description": shot.visual_description or shot.setting,
                                "sound": shot.sound or "",
                                "emotion_context": shot.emotion_context,
                                "dialog": [
                                    {
                                        "character": d.get("character", ""),
                                        "telugu": d.get("telugu", ""),
                                        "english": d.get("english", ""),
                                    }
                                    for d in (shot.dialog or [])
                                ],
                            }
                            for shot in seq.shots
                        ],
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


# Re-export the reader for backwards compatibility (some scripts import it here).
__all__ = ["app", "RuthambharaReader"]
