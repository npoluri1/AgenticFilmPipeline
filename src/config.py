"""Central configuration for the RUTHAMBHARA Agentic Film Pipeline.

Everything is free-first: the system is fully functional offline using
deterministic / local providers, and automatically upgrades to premium
providers when API keys or local model servers are available.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
ARTIFACTS_DIR = OUTPUT_DIR / "artifacts"
RUNS_DIR = OUTPUT_DIR / "runs"
INDEX_DIR = OUTPUT_DIR / "index"
EVALS_DIR = OUTPUT_DIR / "evals"
MEMORY_DIR = OUTPUT_DIR / "memory"
CHECKPOINT_DIR = OUTPUT_DIR / "checkpoints"
STORYBOARD_DIR = ARTIFACTS_DIR / "storyboard"
VOICE_DIR = ARTIFACTS_DIR / "voice"
VIDEO_DIR = ARTIFACTS_DIR / "video"
FINAL_DIR = ARTIFACTS_DIR / "final"

for _d in (
    DATA_DIR, OUTPUT_DIR, ARTIFACTS_DIR, RUNS_DIR, INDEX_DIR, EVALS_DIR,
    MEMORY_DIR, CHECKPOINT_DIR, STORYBOARD_DIR, VOICE_DIR, VIDEO_DIR, FINAL_DIR,
):
    _d.mkdir(parents=True, exist_ok=True)


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


# Candidate locations for the feature screenplay.  The pipeline never
# hard-fails on a missing external drive: it falls back to the bundled script.
_SCRIPT_CANDIDATES = [
    os.getenv("AFP_SCRIPT_PATH", ""),
    str(DATA_DIR / "ruthambhara_script.md"),
    r"D:\WorkSpace\Telugu_Film_Stroy_Board\feature\ఋతంభర_పూర్తి_సినిమా_స్క్రిప్ట్.md",
    str(DATA_DIR / "sample_script.txt"),
]


def resolve_script_path(explicit: str | None = None) -> Path:
    candidates = [explicit] if explicit else []
    candidates += _SCRIPT_CANDIDATES
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return DATA_DIR / "sample_script.txt"


def detect_script_path() -> Path:
    """Prefer the bundled screenplay, then the canonical external folder."""
    bundled = DATA_DIR / "ruthambhara_script.md"
    if bundled.exists():
        return bundled
    folder = Path(r"D:\WorkSpace\Telugu_Film_Stroy_Board\feature")
    if folder.exists():
        md_files = sorted(folder.glob("*.md"), key=lambda p: p.stat().st_size, reverse=True)
        if md_files:
            return md_files[0]
    return resolve_script_path()


@dataclass
class Settings:
    app_name: str = "RUTHAMBHARA Agentic Film Studio"
    version: str = "3.0.0"
    environment: str = os.getenv("AFP_ENV", "development")
    host: str = os.getenv("AFP_HOST", "0.0.0.0")
    port: int = _int("AFP_PORT", 8080)

    # Screenplay
    script_path: str = field(default_factory=lambda: str(detect_script_path()))

    # Providers (free-first)
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("AFP_OLLAMA_MODEL", "llama3.2:3b")
    # Local Ollama generation is opt-in: CPU inference is slower than the
    # deterministic reasoner, so the demo stays instant by default.
    use_ollama: bool = _bool("AFP_USE_OLLAMA", False)
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    llm_timeout_sec: float = _float("AFP_LLM_TIMEOUT", 2.5)
    premium_enabled: bool = _bool("AFP_PREMIUM_ENABLED", False)

    # Media
    render_media: bool = _bool("AFP_RENDER_MEDIA", True)
    render_video: bool = _bool("AFP_RENDER_VIDEO", True)
    storyboard_width: int = _int("AFP_STORYBOARD_WIDTH", 640)
    storyboard_height: int = _int("AFP_STORYBOARD_HEIGHT", 360)
    max_render_shots: int = _int("AFP_MAX_RENDER_SHOTS", 0)  # 0 = all
    tts_voice: str = os.getenv("AFP_TTS_VOICE", "te-IN-ShrutiNeural")
    # ``wav`` keeps the demo deterministic and instant. Set AFP_TTS_BACKEND=edge
    # to use free Microsoft neural voices (needs network).
    tts_backend: str = os.getenv("AFP_TTS_BACKEND", "wav")  # auto|edge|pyttsx3|wav
    ffmpeg_path: str = os.getenv("AFP_FFMPEG", "ffmpeg")
    video_fps: int = _int("AFP_VIDEO_FPS", 24)
    video_width: int = _int("AFP_VIDEO_WIDTH", 1280)
    video_height: int = _int("AFP_VIDEO_HEIGHT", 720)

    # Pipeline
    default_mode: str = os.getenv("AFP_MODE", "hybrid")
    default_tier: str = os.getenv("AFP_TIER", "free")
    default_scope: str = os.getenv("AFP_SCOPE", "sample")  # sample|full|analysis
    sample_sequences: int = _int("AFP_SAMPLE_SEQUENCES", 3)
    sample_max_shots: int = _int("AFP_SAMPLE_MAX_SHOTS", 12)
    max_workers: int = _int("AFP_MAX_WORKERS", 4)
    quality_threshold: float = _float("AFP_QUALITY_THRESHOLD", 0.80)
    max_repair_loops: int = _int("AFP_MAX_REPAIR_LOOPS", 2)
    require_approval: bool = _bool("AFP_REQUIRE_APPROVAL", False)

    # RAG
    embedding_dim: int = _int("AFP_EMBEDDING_DIM", 384)
    chunk_size: int = _int("AFP_CHUNK_SIZE", 700)
    chunk_overlap: int = _int("AFP_CHUNK_OVERLAP", 80)
    rag_top_k: int = _int("AFP_RAG_TOP_K", 6)

    # Guardrails
    guardrail_strict: bool = _bool("AFP_GUARDRAIL_STRICT", True)
    max_script_chars: int = _int("AFP_MAX_SCRIPT_CHARS", 2_000_000)

    cors_origins: list[str] = field(default_factory=lambda: [
        o.strip() for o in os.getenv("AFP_CORS_ORIGINS", "*").split(",") if o.strip()
    ])

    @property
    def script(self) -> Path:
        path = Path(self.script_path)
        return path if path.exists() else resolve_script_path()

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    def as_dict(self) -> dict:
        return {
            "app_name": self.app_name,
            "version": self.version,
            "environment": self.environment,
            "script_path": str(self.script),
            "premium_enabled": self.premium_enabled,
            "render_media": self.render_media,
            "render_video": self.render_video,
            "default_mode": self.default_mode,
            "default_tier": self.default_tier,
            "default_scope": self.default_scope,
            "quality_threshold": self.quality_threshold,
            "ollama_base_url": self.ollama_base_url,
            "ollama_model": self.ollama_model,
            "providers": {
                "ollama": True,
                "openai": self.has_openai,
                "anthropic": self.has_anthropic,
                "ffmpeg": True,
            },
        }


settings = Settings()
