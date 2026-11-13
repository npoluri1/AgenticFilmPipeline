"""Shared test configuration.

Environment variables are set *before* ``src.config`` is imported so the test
suite is deterministic and fully offline:

* no Ollama generation (the deterministic reasoner is faster and stable)
* offline WAV synthesis instead of network TTS
* media rendering available for the API smoke test
"""
from __future__ import annotations

import os

os.environ.setdefault("AFP_ENV", "test")
os.environ.setdefault("AFP_USE_OLLAMA", "0")
os.environ.setdefault("AFP_PREMIUM_ENABLED", "0")
os.environ.setdefault("AFP_TTS_BACKEND", "wav")
os.environ.setdefault("AFP_RENDER_MEDIA", "1")
os.environ.setdefault("AFP_RENDER_VIDEO", "1")

import pytest  # noqa: E402

from src.config import settings  # noqa: E402


@pytest.fixture(scope="session")
def script_path() -> str:
    path = settings.script
    assert path.exists(), f"bundled screenplay missing: {path}"
    return str(path)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from src.web.server import app

    with TestClient(app) as test_client:
        yield test_client
