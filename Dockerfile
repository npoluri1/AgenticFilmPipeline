# ── RUTHAMBHARA Agentic Film Studio ────────────────────────────────────────────
# CPU-only, free-first image.  Everything below works offline; FFmpeg is the only
# system dependency and is used for animatics, A/V alignment and reel assembly.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    AFP_HOST=0.0.0.0 \
    AFP_PORT=8080 \
    AFP_ENV=production

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md main.py ./
COPY src ./src
COPY data ./data

RUN pip install --upgrade pip \
    && pip install -e ".[rag]" \
    && mkdir -p output

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

CMD ["python", "main.py", "serve", "--host", "0.0.0.0", "--port", "8080"]
