"""Free-first AI provider layer.

Every provider degrades gracefully:

* LLM: Ollama (local) -> OpenAI-compatible -> deterministic template engine
* Embeddings: sentence-transformers -> deterministic hash embedder
* TTS: edge-tts (free cloud) -> pyttsx3 -> offline WAV synthesiser
* Image: diffusers (local SD) -> Pillow procedural storyboard painter
* Video: FFmpeg -> manifest planner

No API key or GPU is required for the system to run end-to-end.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import math
import os
import random
import shutil
import struct
import subprocess
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

from src.config import settings
from src.core.text import stable_hash, truncate

# Pillow is a hard dependency of the free storyboard renderer.
try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    PIL_AVAILABLE = True
except Exception:  # pragma: no cover - optional environment
    PIL_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Provider metadata
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ProviderInfo:
    name: str
    kind: str
    tier: str
    available: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "tier": self.tier,
            "available": self.available,
            "detail": self.detail,
        }


# ─────────────────────────────────────────────────────────────────────────────
# LLM providers
# ─────────────────────────────────────────────────────────────────────────────


class BaseLLM:
    name = "base"
    tier = "free"

    def available(self) -> bool:
        return True

    def complete(self, prompt: str, system: str = "", temperature: float = 0.4, max_tokens: int = 900) -> str:
        raise NotImplementedError


class TemplateLLM(BaseLLM):
    """Deterministic offline reasoning engine.

    It is intentionally transparent: the pipeline uses it to produce stable,
    explainable creative analysis without hallucinating external facts.
    """

    name = "template-reasoner"
    tier = "free"

    def complete(self, prompt: str, system: str = "", temperature: float = 0.4, max_tokens: int = 900) -> str:
        text = (prompt or "").strip()
        low = text.lower()
        if "json" in low and ("analysis" in low or "schema" in low):
            return json.dumps({
                "engine": self.name,
                "summary": truncate(text, 220),
                "confidence": 0.72,
                "notes": [
                    "Deterministic offline analysis; connect Ollama or an API key for richer reasoning.",
                ],
            }, ensure_ascii=False)
        if "beat" in low or "structure" in low:
            return (
                "Structure read: the sequence uses escalating stakes, a clear turning point, "
                "and a visual motif that mirrors the protagonist's internal conflict. "
                "Recommended emphasis: preserve negative space around the emotional beat."
            )
        if "character" in low or "arc" in low:
            return (
                "Character read: motivation is legible through action rather than exposition. "
                "The arc moves from guarded stillness to deliberate choice; keep physical "
                "business minimal so the performance carries the subtext."
            )
        if "visual" in low or "storyboard" in low or "shot" in low:
            return (
                "Visual read: strong foreground/background separation, a dominant vertical "
                "motif, and a restrained palette. Use a slow push-in for the reveal and let "
                "ambient sound carry the transition."
            )
        return (
            f"Offline analysis ({self.name}): {truncate(text, 200)} "
            "Connect a local or premium LLM for deeper reasoning."
        )


class OllamaLLM(BaseLLM):
    name = "ollama"
    tier = "free"

    #: How long to skip a failed Ollama endpoint before probing it again.
    COOLDOWN_SEC = 120.0

    def __init__(self, base_url: str, model: str, timeout: float = 2.5):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._last_check = 0.0
        self._cached = False
        self._cooldown_until = 0.0
        self._lock = threading.Lock()
        # Fail fast when the host is unreachable, but allow a real local model
        # enough time to generate once the connection succeeds.
        self._connect_timeout = max(0.5, min(float(timeout), 2.0))
        self._read_timeout = max(30.0, float(timeout) * 20)

    def _cooling_down(self) -> bool:
        return time.time() < self._cooldown_until

    def trip(self, seconds: float | None = None) -> None:
        """Open the circuit breaker after a failed request."""
        with self._lock:
            self._cooldown_until = time.time() + (seconds or self.COOLDOWN_SEC)
            self._cached = False

    def available(self) -> bool:
        if self._cooling_down():
            return False
        with self._lock:
            if time.time() - self._last_check < 60:
                return self._cached
            self._last_check = time.time()
            try:
                response = httpx.get(
                    f"{self.base_url}/api/tags",
                    timeout=httpx.Timeout(
                        connect=self._connect_timeout,
                        read=self._read_timeout,
                        write=self._connect_timeout,
                        pool=self._connect_timeout,
                    ),
                )
                self._cached = response.status_code == 200
            except Exception:
                self._cached = False
            return self._cached

    def complete(self, prompt: str, system: str = "", temperature: float = 0.4, max_tokens: int = 900) -> str:
        if self._cooling_down():
            raise RuntimeError("ollama circuit breaker open")
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            response = httpx.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=httpx.Timeout(
                    connect=self._connect_timeout,
                    read=self._read_timeout,
                    write=self._connect_timeout,
                    pool=self._connect_timeout,
                ),
            )
            response.raise_for_status()
            return (response.json().get("response") or "").strip()
        except Exception:
            self.trip()
            raise


class OpenAICompatibleLLM(BaseLLM):
    name = "openai-compatible"
    tier = "premium"

    def __init__(self, api_key: str, base_url: str, model: str = "gpt-4o-mini", timeout: float = 45.0):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, prompt: str, system: str = "", temperature: float = 0.4, max_tokens: int = 900) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return (response.json()["choices"][0]["message"]["content"] or "").strip()


class AnthropicLLM(BaseLLM):
    name = "anthropic"
    tier = "premium"

    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022", timeout: float = 45.0):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(self, prompt: str, system: str = "", temperature: float = 0.4, max_tokens: int = 900) -> str:
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "system": system,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        blocks = response.json().get("content", [])
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()


class LLMRouter:
    """Selects the best available LLM; always has a deterministic fallback."""

    def __init__(self):
        self.template = TemplateLLM()
        self.ollama = OllamaLLM(settings.ollama_base_url, settings.ollama_model, settings.llm_timeout_sec)
        self.openai = OpenAICompatibleLLM(settings.openai_api_key, settings.openai_base_url)
        self.anthropic = AnthropicLLM(settings.anthropic_api_key)
        self._cache: list[ProviderInfo] = []
        self._cache_at = 0.0
        self.calls = 0
        self.fallbacks = 0
        self.last_provider = self.template.name

    def _chain(self) -> list[BaseLLM]:
        chain: list[BaseLLM] = []
        if settings.use_ollama:
            chain.append(self.ollama)
        if settings.premium_enabled:
            chain += [self.anthropic, self.openai]
        chain.append(self.template)
        return chain

    def complete(self, prompt: str, system: str = "", temperature: float = 0.4, max_tokens: int = 900) -> str:
        self.calls += 1
        for provider in self._chain():
            if not provider.available():
                continue
            try:
                result = provider.complete(prompt, system, temperature, max_tokens)
                if result:
                    self.last_provider = provider.name
                    return result
            except Exception:
                self.fallbacks += 1
                continue
        self.last_provider = self.template.name
        return self.template.complete(prompt, system, temperature, max_tokens)

    def status(self, refresh: bool = False) -> list[ProviderInfo]:
        if not refresh and time.time() - self._cache_at < 60 and self._cache:
            return self._cache
        infos = [
            ProviderInfo(
                self.ollama.name, "llm", "free", self.ollama.available(),
                (f"{settings.ollama_model} @ {settings.ollama_base_url}"
                 + ("" if settings.use_ollama else " (set AFP_USE_OLLAMA=1 to enable)")),
            ),
            ProviderInfo(self.openai.name, "llm", "premium", self.openai.available(), "OPENAI_API_KEY present" if self.openai.available() else "set OPENAI_API_KEY"),
            ProviderInfo(self.anthropic.name, "llm", "premium", self.anthropic.available(), "ANTHROPIC_API_KEY present" if self.anthropic.available() else "set ANTHROPIC_API_KEY"),
            ProviderInfo(self.template.name, "llm", "free", True, "deterministic offline reasoner"),
        ]
        self._cache = infos
        self._cache_at = time.time()
        return infos

    def info(self) -> dict:
        return {
            "active": self.last_provider,
            "calls": self.calls,
            "fallbacks": self.fallbacks,
            "providers": [p.to_dict() for p in self.status()],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Embeddings
# ─────────────────────────────────────────────────────────────────────────────


class HashEmbedder:
    """Deterministic, dependency-free embedding model.

    Hashing bag-of-words + character trigrams into a fixed-dimensional space is
    good enough for screenplay retrieval and keeps the demo fully offline.
    """

    name = "hash-embedder"

    def __init__(self, dim: int = 384):
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        from src.core.text import tokenize

        vec = [0.0] * self.dim
        tokens = tokenize(text)
        for token in tokens:
            idx = int(stable_hash(token)[:8], 16) % self.dim
            vec[idx] += 1.0
        for token in tokens:
            for n in (3, 4):
                if len(token) < n:
                    continue
                for i in range(len(token) - n + 1):
                    idx = int(stable_hash(token[i:i + n])[:8], 16) % self.dim
                    vec[idx] += 0.25
        for a, b in zip(tokens, tokens[1:]):
            idx = int(stable_hash(a + "_" + b)[:8], 16) % self.dim
            vec[idx] += 0.5
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class SentenceTransformerEmbedder:
    name = "sentence-transformers"

    def __init__(self):
        from sentence_transformers import SentenceTransformer  # type: ignore

        self.model = SentenceTransformer(os.getenv("AFP_ST_MODEL", "all-MiniLM-L6-v2"))

    def embed(self, text: str) -> list[float]:
        return self.model.encode(text, normalize_embeddings=True).tolist()

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True).tolist()


class EmbeddingRouter:
    def __init__(self, dim: int = 384):
        self.hash = HashEmbedder(dim)
        self.backend = self.hash
        self._st_checked = False

    def _choose(self):
        if self._st_checked:
            return
        self._st_checked = True
        if os.getenv("AFP_USE_ST_EMBEDDINGS", "0") == "1" and importlib.util.find_spec("sentence_transformers"):
            try:
                self.backend = SentenceTransformerEmbedder()
            except Exception:
                self.backend = self.hash

    def embed(self, text: str) -> list[float]:
        self._choose()
        return self.backend.embed(text)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        self._choose()
        return self.backend.embed_many(texts)

    def info(self) -> dict:
        self._choose()
        return {"backend": self.backend.name, "dimension": self.hash.dim}


# ─────────────────────────────────────────────────────────────────────────────
# Text to speech
# ─────────────────────────────────────────────────────────────────────────────


_EMOTION_MELODY = {
    "anger": (196.0, 0.40),
    "intense_anger": (208.0, 0.42),
    "sadness": (146.0, 0.30),
    "deep_sadness": (130.0, 0.28),
    "joy": (262.0, 0.38),
    "pure_joy": (294.0, 0.40),
    "fear": (220.0, 0.30),
    "paralyzing_fear": (233.0, 0.28),
    "calm": (174.0, 0.30),
    "serene_calm": (165.0, 0.28),
    "suspense": (200.0, 0.32),
    "neutral": (185.0, 0.32),
    "contemplative_neutral": (180.0, 0.30),
}


class WavSynth:
    """Offline prosody synthesiser producing real, playable WAV files.

    It is intentionally a stylised voice-bed (not a speech model): it gives the
    pipeline a playable audio track for every line, timings that match the
    screenplay, and a deterministic artifact that reviewers can scrub.
    """

    name = "offline-wave-synth"

    def __init__(self, sample_rate: int = 22050):
        self.sample_rate = sample_rate

    def synthesize(self, text: str, out_path: Path, voice: str = "", emotion: str = "neutral") -> dict:
        text = (text or "…").strip()
        # Rough speaking-rate model: ~14 Telugu/English characters per second.
        duration = max(1.2, min(9.0, len(text) / 14.0))
        base, energy = _EMOTION_MELODY.get(emotion, _EMOTION_MELODY["neutral"])
        seed = int(stable_hash(text + voice)[:8], 16)
        rng = random.Random(seed)
        frames = int(self.sample_rate * duration)
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with wave.open(str(out_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.sample_rate)
            data = bytearray()
            syllables = max(2, int(duration * 4))
            for i in range(frames):
                t = i / self.sample_rate
                # syllable envelope + sentence intonation
                syllable_pos = (t * syllables) % 1.0
                env = math.sin(math.pi * syllable_pos) ** 0.7
                phrase = 0.65 + 0.35 * math.sin(2 * math.pi * t / max(1.0, duration))
                f0 = base * (1.0 + 0.06 * math.sin(2 * math.pi * 0.9 * t)) * (1.0 + 0.02 * rng.uniform(-1, 1))
                value = (
                    0.55 * math.sin(2 * math.pi * f0 * t)
                    + 0.22 * math.sin(2 * math.pi * (f0 * 2.02) * t)
                    + 0.12 * math.sin(2 * math.pi * (f0 * 3.01) * t)
                    + 0.05 * math.sin(2 * math.pi * 120 * t)
                )
                sample = value * env * phrase * energy
                # fade in/out
                if t < 0.05:
                    sample *= t / 0.05
                if t > duration - 0.08:
                    sample *= max(0.0, (duration - t) / 0.08)
                data.extend(struct.pack("<h", int(max(-1.0, min(1.0, sample)) * 32767)))
            wav.writeframes(bytes(data))

        return {
            "path": str(out_path),
            "duration_sec": round(duration, 2),
            "backend": self.name,
            "voice": voice or "offline",
            "format": "wav",
            "sample_rate": self.sample_rate,
        }


class EdgeTTS:
    """Free Microsoft Edge neural voices (requires network + edge-tts)."""

    name = "edge-tts"
    tier = "free"

    def __init__(self):
        self._available = importlib.util.find_spec("edge_tts") is not None

    def available(self) -> bool:
        return self._available

    def synthesize(self, text: str, out_path: Path, voice: str, emotion: str = "neutral") -> dict:
        import edge_tts  # type: ignore

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        async def _run() -> None:
            communicate = edge_tts.Communicate(text, voice or settings.tts_voice)
            await communicate.save(str(out_path))

        asyncio.run(_run())
        duration = 0.0
        try:
            with wave.open(str(out_path), "rb") as wav:
                duration = wav.getnframes() / wav.getframerate()
        except Exception:
            try:
                from mutagen.mp3 import MP3  # type: ignore

                duration = MP3(str(out_path)).info.length
            except Exception:
                duration = max(1.0, len(text) / 14.0)
        return {
            "path": str(out_path),
            "duration_sec": round(duration, 2),
            "backend": self.name,
            "voice": voice or settings.tts_voice,
            "format": out_path.suffix.lstrip("."),
        }


class Pyttsx3TTS:
    name = "pyttsx3"

    def __init__(self):
        self._available = importlib.util.find_spec("pyttsx3") is not None

    def available(self) -> bool:
        return self._available

    def synthesize(self, text: str, out_path: Path, voice: str, emotion: str = "neutral") -> dict:
        import pyttsx3  # type: ignore

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        engine = pyttsx3.init()
        engine.setProperty("rate", 165)
        engine.save_to_file(text, str(out_path))
        engine.runAndWait()
        return {
            "path": str(out_path),
            "duration_sec": round(max(1.0, len(text) / 14.0), 2),
            "backend": self.name,
            "voice": voice or "system",
            "format": out_path.suffix.lstrip("."),
        }


class TTSRouter:
    def __init__(self):
        self.edge = EdgeTTS()
        self.pyttsx3 = Pyttsx3TTS()
        self.wav = WavSynth()
        self.calls = 0
        self.fallbacks = 0
        self.last_backend = self.wav.name

    def synthesize(self, text: str, out_path: Path, voice: str = "", emotion: str = "neutral") -> dict:
        self.calls += 1
        backend = (settings.tts_backend or "auto").lower()
        candidates = []
        if backend in {"auto", "edge"} and self.edge.available():
            candidates.append(("edge", self.edge, out_path.with_suffix(".mp3")))
        if backend in {"auto", "pyttsx3"} and self.pyttsx3.available():
            candidates.append(("pyttsx3", self.pyttsx3, out_path.with_suffix(".wav")))
        candidates.append(("wav", self.wav, out_path.with_suffix(".wav")))

        for name, provider, target in candidates:
            try:
                result = provider.synthesize(text, target, voice, emotion)
                if not Path(result["path"]).exists() or Path(result["path"]).stat().st_size < 64:
                    raise RuntimeError("empty audio")
                self.last_backend = name
                return result
            except Exception:
                self.fallbacks += 1
                continue
        # Guaranteed fallback
        result = self.wav.synthesize(text, out_path.with_suffix(".wav"), voice, emotion)
        self.last_backend = self.wav.name
        return result

    def info(self) -> dict:
        return {
            "backend": self.last_backend,
            "calls": self.calls,
            "fallbacks": self.fallbacks,
            "providers": [
                {"name": "edge-tts", "tier": "free", "available": self.edge.available()},
                {"name": "pyttsx3", "tier": "free", "available": self.pyttsx3.available()},
                {"name": "offline-wave-synth", "tier": "free", "available": True},
            ],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Procedural storyboard renderer (free, offline, real PNGs)
# ─────────────────────────────────────────────────────────────────────────────


EMOTION_PALETTES: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]] = {
    "intense_anger": ((26, 6, 6), (160, 44, 18), (255, 176, 74)),
    "deep_sadness": ((5, 10, 24), (22, 58, 102), (126, 176, 214)),
    "pure_joy": ((34, 21, 4), (232, 146, 32), (255, 226, 141)),
    "serene_calm": ((4, 20, 26), (18, 82, 94), (128, 206, 196)),
    "paralyzing_fear": ((12, 6, 20), (64, 20, 78), (150, 92, 166)),
    "contemplative_neutral": ((8, 12, 22), (40, 62, 96), (176, 198, 222)),
    "suspense": ((14, 10, 8), (86, 60, 26), (214, 168, 86)),
    "neutral": ((10, 14, 22), (48, 68, 96), (190, 208, 224)),
}

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\seguisb.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
_TELUGU_FONTS = [r"C:\Windows\Fonts\Nirmala.ttf", r"C:\Windows\Fonts\gautami.ttf"]


def _font(size: int, telugu: bool = False) -> Any:
    if not PIL_AVAILABLE:
        return None
    candidates = (_TELUGU_FONTS if telugu else []) + _FONT_CANDIDATES
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _wrap(draw: Any, text: str, font: Any, max_width: int, max_lines: int = 4) -> list[str]:
    words = (text or "").split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        try:
            width = draw.textbbox((0, 0), candidate, font=font)[2]
        except Exception:
            width = len(candidate) * 8
        if width <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if lines and len(lines) == max_lines and words:
        lines[-1] = truncate(lines[-1], max(8, max_width // 8))
    return lines


class StoryboardRenderer:
    """Paints cinematic pre-visualisation frames with Pillow.

    This is a real graphics-engineering module: seeded procedural landscapes,
    emotion-driven colour grading, rule-of-thirds composition, silhouettes,
    atmospheric perspective, film grain and letterboxing.
    """

    name = "pillow-procedural"

    def __init__(self, width: int = 640, height: int = 360):
        self.width = width
        self.height = height

    def available(self) -> bool:
        return PIL_AVAILABLE

    def render_shot(self, shot: dict, out_path: Path, title: str = "RUTHAMBHARA") -> dict:
        if not PIL_AVAILABLE:
            raise RuntimeError("Pillow is not installed")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        width, height = self.width, self.height
        emotion = shot.get("emotion") or shot.get("emotion_context") or "neutral"
        top, mid, glow = EMOTION_PALETTES.get(emotion, EMOTION_PALETTES["neutral"])
        seed = int(stable_hash(str(shot.get("number", "")) + shot.get("setting", ""))[:8], 16)
        rng = random.Random(seed)
        horizon = int(height * rng.uniform(0.52, 0.66))

        img = Image.new("RGB", (width, height), top)
        draw = ImageDraw.Draw(img, "RGBA")

        # Sky gradient
        for y in range(horizon):
            t = y / max(1, horizon)
            draw.line([(0, y), (width, y)], fill=_lerp(top, mid, t ** 0.8))

        # Sun / moon disc
        cx = int(width * rng.uniform(0.58, 0.82))
        cy = int(horizon * rng.uniform(0.28, 0.55))
        radius = int(height * rng.uniform(0.08, 0.14))
        for r in range(radius * 3, 0, -2):
            alpha = int(80 * (1 - r / (radius * 3)) ** 2)
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*glow, alpha))
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=glow)

        # Layered mountains / skyline
        for layer in range(4):
            depth = 1 - layer / 5
            base_y = horizon + int(height * 0.03 * layer)
            points = [(0, height)]
            x = 0
            while x <= width:
                step = max(18, int(width * 0.08))
                peak = base_y - int(height * (0.04 + 0.09 * depth) * rng.uniform(0.4, 1.0))
                points.append((x, peak))
                x += step
            points.append((width, height))
            shade = _lerp(mid, top, 0.15 + layer * 0.18)
            draw.polygon(points, fill=shade)

        # Ground gradient
        for y in range(horizon, height):
            t = (y - horizon) / max(1, height - horizon)
            draw.line([(0, y), (width, y)], fill=_lerp(_lerp(mid, top, 0.45), top, t * 0.8))

        # Silhouettes / subject
        setting_upper = str(shot.get("setting", "")).upper()
        if "CLOSE-UP" in setting_upper or "ECU" in setting_upper or "EYE" in setting_upper:
            self._draw_eye(draw, width, height, rng, glow)
        elif "BLACK" in setting_upper:
            draw.rectangle([0, 0, width, height], fill=(3, 3, 5, 255))
            draw.ellipse([width * 0.47, height * 0.42, width * 0.53, height * 0.48], fill=(*glow, 60))
        elif "CRANE" in setting_upper or "GOD-VIEW" in setting_upper or "AERIAL" in setting_upper:
            self._draw_village(draw, width, height, horizon, rng, glow)
        else:
            self._draw_figures(draw, width, height, horizon, rng, glow)

        # Atmospheric fog bands
        fog = ImageDraw.Draw(img, "RGBA")
        for _ in range(3):
            y = rng.randint(horizon - 20, height - 20)
            fog.rectangle([0, y, width, y + 18], fill=(*glow, rng.randint(8, 18)))

        # Letterbox + subtle vignette
        bar = int(height * 0.055)
        draw.rectangle([0, 0, width, bar], fill=(0, 0, 0))
        draw.rectangle([0, height - bar, width, height], fill=(0, 0, 0))
        vignette = Image.new("L", (width, height), 0)
        vdraw = ImageDraw.Draw(vignette)
        vdraw.ellipse([-width * 0.15, -height * 0.2, width * 1.15, height * 1.2], fill=255)
        vignette = vignette.filter(ImageFilter.GaussianBlur(30))
        black = Image.new("RGB", (width, height), (0, 0, 0))
        img = Image.composite(img, black, vignette)

        # Film grain
        draw = ImageDraw.Draw(img, "RGBA")
        for _ in range(int(width * height * 0.012)):
            x, y = rng.randint(0, width - 1), rng.randint(0, height - 1)
            shade = rng.randint(0, 255)
            draw.point((x, y), fill=(shade, shade, shade, rng.randint(4, 14)))

        # Composition guides (very subtle)
        thirds = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(thirds)
        for fx in (1 / 3, 2 / 3):
            gdraw.line([(width * fx, bar), (width * fx, height - bar)], fill=(255, 255, 255, 10), width=1)
        for fy in (1 / 3, 2 / 3):
            gdraw.line([(0, height * fy), (width, height * fy)], fill=(255, 255, 255, 10), width=1)
        img = Image.alpha_composite(img.convert("RGBA"), thirds).convert("RGB")

        # Overlay typography
        draw = ImageDraw.Draw(img, "RGBA")
        small = _font(max(9, int(height * 0.030)))
        body = _font(max(11, int(height * 0.036)))
        head = _font(max(13, int(height * 0.045)))
        pad = int(width * 0.025)
        draw.rectangle([0, height - bar - int(height * 0.28), width, height - bar], fill=(0, 0, 0, 120))
        code = f"ACT {shot.get('act', '?')} · SEQ {shot.get('sequence', '?')} · SHOT {shot.get('number', '?')}"
        draw.text((pad, height - bar - int(height * 0.26)), code, font=small, fill=(*glow, 230))
        lines = _wrap(draw, str(shot.get("setting", "")), head, width - pad * 2, 2)
        y = height - bar - int(height * 0.21)
        for line in lines:
            draw.text((pad, y), line, font=head, fill=(238, 244, 255, 245))
            y += int(height * 0.052)
        meta = " · ".join(filter(None, [
            str(shot.get("lens", "")) or "35mm",
            str(shot.get("camera_movement", "")) or "static",
            f"{shot.get('duration_sec', 5)}s",
            emotion.replace("_", " "),
        ]))
        draw.text((pad, height - bar - int(height * 0.10)), meta, font=small, fill=(*glow, 220))
        draw.text((width - pad - draw.textbbox((0, 0), title, font=small)[2], bar + int(height * 0.012)),
                  title, font=small, fill=(255, 255, 255, 150))

        img.save(out_path, "PNG", optimize=True)
        return {
            "path": str(out_path),
            "width": width,
            "height": height,
            "renderer": self.name,
            "emotion": emotion,
        }

    def _draw_figures(self, draw: Any, width: int, height: int, horizon: int, rng: random.Random, glow: tuple) -> None:
        count = rng.randint(1, 4)
        for i in range(count):
            fx = rng.uniform(0.18, 0.82) if count > 1 else rng.uniform(0.38, 0.62)
            scale = rng.uniform(0.8, 1.25)
            cx = int(width * fx)
            base = horizon + int(height * rng.uniform(0.08, 0.22))
            body_h = int(height * 0.20 * scale)
            head_r = max(5, int(body_h * 0.17))
            color = (10, 12, 16, 235)
            draw.ellipse([cx - head_r, base - body_h - head_r * 2, cx + head_r, base - body_h], fill=color)
            draw.polygon([
                (cx - head_r * 1.5, base),
                (cx - head_r * 0.9, base - body_h * 0.92),
                (cx + head_r * 0.9, base - body_h * 0.92),
                (cx + head_r * 1.5, base),
            ], fill=color)
            # rim light
            draw.line([(cx + head_r * 0.6, base - body_h * 0.3), (cx + head_r * 0.6, base - body_h * 0.9)],
                      fill=(*glow, 90), width=max(1, width // 640))

    def _draw_eye(self, draw: Any, width: int, height: int, rng: random.Random, glow: tuple) -> None:
        cx, cy = width // 2, int(height * 0.46)
        w, h = int(width * 0.46), int(height * 0.17)
        draw.polygon([(cx - w, cy), (cx, cy - h), (cx + w, cy), (cx, cy + h)], fill=(236, 240, 245, 255))
        iris_r = int(h * 0.92)
        draw.ellipse([cx - iris_r, cy - iris_r, cx + iris_r, cy + iris_r], fill=(30, 60, 60, 255))
        pupil_r = int(iris_r * 0.45)
        draw.ellipse([cx - pupil_r, cy - pupil_r, cx + pupil_r, cy + pupil_r], fill=(4, 6, 8, 255))
        draw.ellipse([cx - pupil_r // 2, cy - pupil_r // 2, cx, cy], fill=(255, 255, 255, 180))
        for i in range(5):
            fx = cx + rng.randint(-w, w)
            fy = cy + rng.randint(-h // 2, h // 2)
            draw.line([(cx, cy), (fx, fy)], fill=(*glow, 20), width=1)

    def _draw_village(self, draw: Any, width: int, height: int, horizon: int, rng: random.Random, glow: tuple) -> None:
        for i in range(14):
            bx = int(width * rng.uniform(0.05, 0.95))
            by = horizon + int(height * rng.uniform(0.02, 0.28))
            bw = int(width * rng.uniform(0.025, 0.06))
            bh = int(height * rng.uniform(0.03, 0.07))
            draw.rectangle([bx, by - bh, bx + bw, by], fill=(12, 14, 18, 230))
            draw.polygon([(bx - 3, by - bh), (bx + bw // 2, by - bh - bh // 2), (bx + bw + 3, by - bh)],
                         fill=(10, 12, 16, 235))
            if rng.random() > 0.55:
                draw.ellipse([bx + bw // 2 - 1, by - bh + 2, bx + bw // 2 + 2, by - bh + 5],
                             fill=(*glow, 180))
        # central figure
        cx = width // 2
        draw.ellipse([cx - 5, horizon + 8, cx + 5, horizon + 20], fill=(4, 5, 7, 255))
        draw.rectangle([cx - 4, horizon + 18, cx + 4, horizon + 36], fill=(4, 5, 7, 255))

    def render_character_card(self, profile: dict, out_path: Path) -> dict:
        if not PIL_AVAILABLE:
            raise RuntimeError("Pillow is not installed")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        width, height = 480, 600
        seed = int(stable_hash(str(profile.get("name", "")))[:8], 16)
        rng = random.Random(seed)
        palette = EMOTION_PALETTES.get("contemplative_neutral")
        img = Image.new("RGB", (width, height), (8, 10, 18))
        draw = ImageDraw.Draw(img, "RGBA")
        for y in range(height):
            t = y / height
            draw.line([(0, y), (width, y)], fill=_lerp((8, 10, 18), palette[1], 0.35 * (1 - t) + 0.05))
        # silhouette portrait
        cx = width // 2
        draw.ellipse([cx - 95, 120, cx + 95, 340], fill=(18, 22, 30, 255))
        draw.ellipse([cx - 70, 160, cx + 70, 320], fill=(28, 34, 44, 255))
        draw.rounded_rectangle([cx - 130, 340, cx + 130, 560], radius=40, fill=(16, 20, 28, 255))
        # accent line
        draw.rectangle([40, 560, width - 40, 563], fill=palette[2])
        head = _font(28)
        body = _font(16)
        small = _font(12)
        draw.text((40, 60), str(profile.get("name", "Character"))[:28], font=head, fill=(240, 246, 255))
        draw.text((40, 96), f"{profile.get('actor', '')}", font=body, fill=palette[2])
        lines = _wrap(draw, str(profile.get("function", "")), small, width - 80, 3)
        y = 580
        for line in lines[:2]:
            draw.text((40, y - 20), line, font=small, fill=(150, 165, 185))
            y += 16
        img.save(out_path, "PNG", optimize=True)
        return {"path": str(out_path), "width": width, "height": height, "renderer": self.name}

    def render_contact_sheet(self, frames: list[dict], out_path: Path, title: str = "") -> dict:
        if not PIL_AVAILABLE:
            raise RuntimeError("Pillow is not installed")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cols = 3
        thumb_w, thumb_h = 320, 180
        rows = max(1, math.ceil(len(frames) / cols))
        label_h = 26
        header_h = 46
        width = cols * thumb_w + 24
        height = header_h + rows * (thumb_h + label_h) + 16
        sheet = Image.new("RGB", (width, height), (8, 10, 16))
        draw = ImageDraw.Draw(sheet)
        head = _font(18)
        small = _font(11)
        draw.text((12, 14), title or "Storyboard", font=head, fill=(235, 242, 255))
        for i, frame in enumerate(frames[: cols * 8]):
            path = Path(frame.get("path", ""))
            if not path.exists():
                continue
            row, col = divmod(i, cols)
            x = 12 + col * thumb_w
            y = header_h + row * (thumb_h + label_h)
            try:
                thumb = Image.open(path).convert("RGB")
                thumb.thumbnail((thumb_w - 8, thumb_h - 8))
                sheet.paste(thumb, (x + (thumb_w - thumb.width) // 2, y + (thumb_h - thumb.height) // 2))
            except Exception:
                draw.rectangle([x + 4, y + 4, x + thumb_w - 4, y + thumb_h - 4], fill=(20, 24, 34))
            caption = f"{frame.get('number', '')} · {truncate(frame.get('setting', ''), 34)}"
            draw.text((x + 4, y + thumb_h + 5), caption, font=small, fill=(160, 175, 195))
        sheet.save(out_path, "PNG", optimize=True)
        return {"path": str(out_path), "frames": len(frames), "renderer": self.name}


class DiffusersRenderer:
    """Optional local Stable Diffusion renderer (enabled with AFP_USE_DIFFUSERS=1)."""

    name = "diffusers-sdxl"

    def __init__(self):
        self._pipe = None
        self._available = (
            os.getenv("AFP_USE_DIFFUSERS", "0") == "1"
            and importlib.util.find_spec("diffusers") is not None
        )

    def available(self) -> bool:
        return self._available

    def render_shot(self, shot: dict, out_path: Path, title: str = "RUTHAMBHARA") -> dict:
        import torch  # type: ignore
        from diffusers import AutoPipelineForText2Image  # type: ignore

        if self._pipe is None:
            self._pipe = AutoPipelineForText2Image.from_pretrained(
                os.getenv("AFP_SD_MODEL", "stabilityai/sdxl-turbo"),
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            )
            self._pipe = self._pipe.to("cuda" if torch.cuda.is_available() else "cpu")
        prompt = (
            f"cinematic film still, {shot.get('setting')}, {shot.get('visual_description', '')}, "
            f"{shot.get('lens', '')}, {shot.get('emotion', 'neutral')}, anamorphic 2.39:1, "
            "dramatic lighting, production design, no text"
        )
        image = self._pipe(prompt=prompt, num_inference_steps=4, guidance_scale=0.0).images[0]
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(out_path)
        return {"path": str(out_path), "renderer": self.name, "prompt": prompt}


class ImageRouter:
    def __init__(self, width: int = 640, height: int = 360):
        self.procedural = StoryboardRenderer(width, height)
        self.diffusers = DiffusersRenderer()
        self.calls = 0
        self.last_backend = self.procedural.name

    def render_shot(self, shot: dict, out_path: Path, title: str = "RUTHAMBHARA") -> dict:
        self.calls += 1
        if self.diffusers.available():
            try:
                result = self.diffusers.render_shot(shot, out_path, title)
                self.last_backend = self.diffusers.name
                return result
            except Exception:
                pass
        result = self.procedural.render_shot(shot, out_path, title)
        self.last_backend = self.procedural.name
        return result

    def info(self) -> dict:
        return {
            "backend": self.last_backend,
            "renders": self.calls,
            "providers": [
                {"name": self.procedural.name, "tier": "free", "available": self.procedural.available()},
                {"name": self.diffusers.name, "tier": "free", "available": self.diffusers.available()},
            ],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Video / animatic rendering
# ─────────────────────────────────────────────────────────────────────────────


class FFmpegVideo:
    name = "ffmpeg"

    def __init__(self, binary: str = ""):
        self.binary = binary or settings.ffmpeg_path
        self.path = shutil.which(self.binary) or (self.binary if Path(self.binary).exists() else "")

    def available(self) -> bool:
        return bool(self.path)

    def _run(self, args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.path] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def still_to_clip(
        self,
        image: Path,
        out_path: Path,
        duration: float,
        audio: Optional[Path] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fps: Optional[int] = None,
    ) -> dict:
        if not self.available():
            raise RuntimeError("ffmpeg unavailable")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        duration = max(0.6, min(float(duration), 30.0))
        width = width or settings.video_width
        height = height or settings.video_height
        fps = fps or settings.video_fps
        args = [
            "-y", "-loop", "1", "-i", str(image),
            "-t", f"{duration:.2f}",
            "-vf",
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"fps={fps},format=yuv420p",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        ]
        if audio and Path(audio).exists():
            args += ["-i", str(audio), "-shortest", "-c:a", "aac", "-b:a", "96k"]
        args += [str(out_path)]
        result = self._run(args)
        if result.returncode != 0 or not out_path.exists():
            raise RuntimeError((result.stderr or "ffmpeg failed")[-500:])
        return {"path": str(out_path), "duration_sec": duration, "backend": self.name}

    def concat_clips(self, clips: list[Path], out_path: Path) -> dict:
        if not self.available():
            raise RuntimeError("ffmpeg unavailable")
        if not clips:
            raise RuntimeError("no clips")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        list_file = out_path.parent / f"{out_path.stem}_concat.txt"
        body = "\n".join(f"file '{Path(c).as_posix()}'" for c in clips)
        list_file.write_text(body + "\n", encoding="utf-8")
        args = [
            "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", str(out_path),
        ]
        result = self._run(args)
        if result.returncode != 0 or not out_path.exists():
            # Re-encode fallback for mismatched codecs
            args = [
                "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                "-pix_fmt", "yuv420p", str(out_path),
            ]
            result = self._run(args)
        if result.returncode != 0 or not out_path.exists():
            raise RuntimeError((result.stderr or "concat failed")[-500:])
        return {"path": str(out_path), "clips": len(clips), "backend": self.name}

    def concat_with_audio(self, video_path: Path, audio_path: Path, out_path: Path) -> dict:
        if not self.available():
            raise RuntimeError("ffmpeg unavailable")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = self._run([
            "-y", "-i", str(video_path), "-i", str(audio_path),
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", str(out_path),
        ])
        if result.returncode != 0 or not out_path.exists():
            raise RuntimeError((result.stderr or "mux failed")[-500:])
        return {"path": str(out_path), "backend": self.name}

    def info(self) -> dict:
        version = ""
        if self.available():
            try:
                version = (self._run(["-version"], 10).stdout or "").splitlines()[0]
            except Exception:
                version = "ffmpeg"
        return {"name": self.name, "available": self.available(), "path": self.path, "version": version}


class VideoRouter:
    def __init__(self):
        self.ffmpeg = FFmpegVideo()
        self.calls = 0

    def available(self) -> bool:
        return self.ffmpeg.available()

    def still_to_clip(self, image: Path, out_path: Path, duration: float, audio: Optional[Path] = None, **kwargs: Any) -> dict:
        self.calls += 1
        return self.ffmpeg.still_to_clip(image, out_path, duration, audio, **kwargs)

    def concat(self, clips: list[Path], out_path: Path) -> dict:
        self.calls += 1
        return self.ffmpeg.concat_clips(clips, out_path)

    def info(self) -> dict:
        return {"backend": "ffmpeg" if self.available() else "manifest", "renders": self.calls, **self.ffmpeg.info()}


# ─────────────────────────────────────────────────────────────────────────────
# Provider facade
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ProviderRegistry:
    llm: LLMRouter = field(default_factory=LLMRouter)
    embeddings: EmbeddingRouter = field(default_factory=EmbeddingRouter)
    tts: TTSRouter = field(default_factory=TTSRouter)
    image: ImageRouter = field(default_factory=ImageRouter)
    video: VideoRouter = field(default_factory=VideoRouter)

    def status(self, refresh: bool = False) -> dict:
        return {
            "llm": self.llm.info(),
            "embeddings": self.embeddings.info(),
            "tts": self.tts.info(),
            "image": self.image.info(),
            "video": self.video.info(),
            "llm_providers": [p.to_dict() for p in self.llm.status(refresh)],
        }

    def flat_status(self, refresh: bool = False) -> list[dict]:
        rows: list[dict] = []
        for info in self.llm.status(refresh):
            rows.append(info.to_dict())
        rows.append(ProviderInfo("hash-embedder", "embedding", "free", True, self.embeddings.info()["backend"]).to_dict())
        for row in self.tts.info()["providers"]:
            rows.append(ProviderInfo(row["name"], "tts", row["tier"], row["available"], "").to_dict())
        for row in self.image.info()["providers"]:
            rows.append(ProviderInfo(row["name"], "image", row["tier"], row["available"], "").to_dict())
        rows.append(ProviderInfo("ffmpeg", "video", "free", self.video.available(), self.video.ffmpeg.path).to_dict())
        return rows


registry = ProviderRegistry()
