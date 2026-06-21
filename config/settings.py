import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

PIPELINE_CONFIG = CONFIG_DIR / "pipeline.yaml"

SCENE_CHUNK_SIZE_MINUTES = 10
MAX_PARALLEL_AGENTS = 4
QUALITY_CHECK_INTERVAL_SECONDS = 30
