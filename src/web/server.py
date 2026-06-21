import json
import time
import yaml
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.readers.ruthambhara_reader import RuthambharaReader
from src.models.model_registry import registry
from src.models.humanizer import Humanizer, ScriptEnhancer
from src.models.schemas import PipelineContext, PipelineMode
from src.supervisor import AgentSupervisor
from src.utils.logger import get_logger

logger = get_logger("web")
SCRIPT_PATH = Path("D:\\WorkSpace\\Telugu_Film_Stroy_Board\\feature\\ఋతంభర_పూర్తి_సినిమా_స్క్రిప్ట్.md")

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "output"
VIDEOS_DIR = OUTPUT_DIR / "videos"

app = FastAPI(title="RUTHAMBHARA — Agentic Film Pipeline API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if VIDEOS_DIR.exists():
    app.mount("/videos", StaticFiles(directory=str(VIDEOS_DIR)), name="videos")


class RunPipelineRequest(BaseModel):
    mode: str = "hybrid"
    language: str = "te"
    all_languages: bool = False
    model_selections: dict[str, str] = {}
    tier: str = "free"


class ModelSelectionUpdate(BaseModel):
    category: str
    model_id: str
    tier: str


@app.get("/")
async def root():
    return {
        "app": "RUTHAMBHARA Agentic Film Pipeline",
        "version": "2.0",
        "film": "ఋతంభర — Ruthambhara",
        "endpoints": [
            "/script — View parsed script",
            "/script/enhanced — View human-enhanced script",
            "/scenes — View all scenes with shot details",
            "/models — View available models (Free + Premium)",
            "/pipeline/run — Run pipeline",
            "/pipeline/status — Pipeline status",
            "/videos/* — Serve generated video files",
            "/health — Health check",
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": time.time()}


@app.get("/script")
async def get_script(enhanced: bool = Query(False)):
    if not SCRIPT_PATH.exists():
        raise HTTPException(404, f"Script not found: {SCRIPT_PATH}")

    reader = RuthambharaReader()
    film = reader.read(str(SCRIPT_PATH))

    if enhanced:
        enhancer = ScriptEnhancer()
        film = enhancer.enhance_for_human_clarity(film)

    acts_data = []
    for act in film.acts:
        seqs = []
        for seq in act.sequences:
            seqs.append({
                "number": seq.number,
                "english_name": seq.english_name,
                "telugu_name": seq.telugu_name,
                "runtime_minutes": seq.runtime_minutes,
                "shots": [
                    {
                        "number": s.number,
                        "setting": s.setting,
                        "duration_sec": s.duration_sec,
                        "lens": s.lens,
                        "camera_movement": s.camera_movement,
                        "visual_description": s.visual_description,
                        "sound": s.sound,
                        "emotion_context": s.emotion_context,
                        "dialog": s.dialog,
                    }
                    for s in seq.shots
                ],
            })
        acts_data.append({
            "number": act.number,
            "english_subtitle": act.english_subtitle,
            "start_time": act.start_time,
            "end_time": act.end_time,
            "sequences": seqs,
        })

    return {
        "title": film.title,
        "telugu_title": film.telugu_title,
        "runtime": film.runtime_str,
        "runtime_minutes": film.runtime_minutes,
        "languages": film.languages,
        "aspect_ratio": film.aspect_ratio,
        "cast": [{"role": c.role, "actor": c.actor, "function": c.function} for c in film.cast],
        "music_themes": [{"name": t.name, "telugu_name": t.telugu_name, "instruments": t.instruments} for t in film.music_themes],
        "acts": acts_data,
        "total_acts": len(film.acts),
        "total_sequences": sum(len(a.sequences) for a in film.acts),
        "total_shots": sum(len(s.shots) for a in film.acts for s in a.sequences),
    }


@app.get("/script/enhanced")
async def get_enhanced_script():
    if not SCRIPT_PATH.exists():
        raise HTTPException(404, f"Script not found: {SCRIPT_PATH}")
    reader = RuthambharaReader()
    film = reader.read(str(SCRIPT_PATH))
    humanizer = Humanizer()
    story = humanizer.render_script_as_story(film)
    return {"story": story, "format": "markdown"}


@app.get("/scenes")
async def get_scenes():
    if not SCRIPT_PATH.exists():
        raise HTTPException(404, f"Script not found: {SCRIPT_PATH}")
    reader = RuthambharaReader()
    film = reader.read(str(SCRIPT_PATH))

    output = []
    video_files = {}
    if VIDEOS_DIR.exists():
        for f in VIDEOS_DIR.iterdir():
            if f.suffix.lower() in (".mp4", ".webm", ".mov", ".avi", ".mkv"):
                video_files[f.stem] = f.name

    for act in film.acts:
        act_data = {
            "number": act.number,
            "english_subtitle": act.english_subtitle,
            "telugu_subtitle": act.telugu_subtitle,
            "start_time": act.start_time,
            "end_time": act.end_time,
            "sequences": [],
        }
        for seq in act.sequences:
            shots_data = []
            for shot in seq.shots:
                shot_key = f"act{act.number}_seq{seq.number}_shot{shot.number.replace('.','_')}"
                video_url = f"/videos/{video_files[shot_key]}" if shot_key in video_files else None
                shots_data.append({
                    "number": shot.number,
                    "setting": shot.setting,
                    "duration_sec": shot.duration_sec,
                    "lens": shot.lens or "Standard",
                    "camera_movement": shot.camera_movement or "Static",
                    "visual_description": shot.visual_description or shot.setting,
                    "dialog": [{"character": d.get("character",""), "line": d.get("dialog","")} for d in (shot.dialog or [])],
                    "sound": shot.sound or "",
                    "emotion_context": shot.emotion_context,
                    "video_url": video_url,
                })
            seq_data = {
                "number": seq.number,
                "english_name": seq.english_name,
                "telugu_name": seq.telugu_name,
                "runtime_minutes": seq.runtime_minutes,
                "shots": shots_data,
                "total_shots": len(seq.shots),
            }
            act_data["sequences"].append(seq_data)
        act_data["total_sequences"] = len(act.sequences)
        act_data["total_shots"] = sum(len(s.shots) for s in act.sequences)
        output.append(act_data)

    return {
        "title": film.title,
        "telugu_title": film.telugu_title,
        "runtime": film.runtime_str,
        "runtime_minutes": film.runtime_minutes,
        "languages": film.languages,
        "total_acts": len(film.acts),
        "total_sequences": sum(len(a.sequences) for a in film.acts),
        "total_shots": sum(len(s.shots) for a in film.acts for s in a.sequences),
        "acts": output,
    }


@app.get("/models")
async def get_models():
    return registry.to_dict()


@app.post("/models/select")
async def select_model(update: ModelSelectionUpdate):
    model = registry.get_model(update.model_id)
    if not model:
        raise HTTPException(404, f"Model '{update.model_id}' not found")
    return {
        "selected": {
            "category": update.category,
            "model": model.__dict__,
            "tier": update.tier,
        }
    }


@app.post("/pipeline/run")
async def run_pipeline(req: RunPipelineRequest):
    if not SCRIPT_PATH.exists():
        raise HTTPException(404, f"Script not found: {SCRIPT_PATH}")

    ctx = PipelineContext(
        pipeline_id=f"ruthambhara_{int(time.time())}",
        mode=PipelineMode(req.mode),
        source_script_path=str(SCRIPT_PATH),
        language=req.language,
        total_duration_minutes=205.0,
        model_selections=req.model_selections,
        tier=req.tier,
    )

    supervisor = AgentSupervisor()
    start = time.time()
    results = supervisor.run(ctx)
    elapsed = time.time() - start

    return {
        "pipeline_id": ctx.pipeline_id,
        "status": "completed",
        "mode": req.mode,
        "agents": [
            {
                "name": r.agent_name,
                "status": r.status.value,
                "duration_sec": round(r.duration_sec, 2),
            }
            for r in results
        ],
        "total_time_sec": round(elapsed, 2),
        "quality": {
            "passed": sum(1 for r in ctx.quality_reports if r.passed),
            "total": len(ctx.quality_reports),
        },
        "film": {
            "title": "RUTHAMBHARA",
            "acts": len(ctx.film.acts) if ctx.film else 0,
            "sequences": sum(len(a.sequences) for a in ctx.film.acts) if ctx.film else 0,
            "shots": sum(len(s.shots) for a in ctx.film.acts for s in a.sequences) if ctx.film else 0,
        } if ctx.film else {},
    }


@app.get("/pipeline/status")
async def pipeline_status():
    return {"status": "idle", "ready": True, "script_loaded": SCRIPT_PATH.exists()}
