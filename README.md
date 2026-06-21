# ఋతంభర — RUTHAMBHARA

**Agentic Film Pipeline** — AI-powered feature film production system for the Telugu movie *Ruthambhara* (3h 25m, 6 Acts, 35 Sequences, 98 Shots).

## Features

- **8 Specialized Agents** — Script → Storyboard → Character → Voice → Animation → LipSync → Render → Quality
- **3 Pipeline Modes** — Sequential, Parallel (topological DAG), Hybrid
- **Free + Premium Models** — Choose per category (LLM, TTS, Image, Video, etc.)
- **Human-Enhanced Script** — Emotional context, camera movement, visual descriptions
- **Web UI** — Dashboard, model selection, pipeline control, enhanced story view
- **Docker Deployment** — Backend + Frontend + Ollama (local models)

## Model Tiers

| Tier | Cost | Examples |
|------|------|----------|
| **Free** | ₹0 | Ollama (Llama 3.2, Qwen 2.5), Coqui TTS, Stable Diffusion, Wav2Lip |
| **Premium** | API costs | GPT-4o, Claude 3.5, ElevenLabs, Runway Gen-4, DALL-E 3 |

## Quick Start

### Backend API
```bash
pip install -e .
uvicorn src.web.server:app --host 0.0.0.0 --port 8080 --reload
```

### Web UI
```bash
cd web && npm install && npm run dev
```

### Docker
```bash
docker compose up
```

### CLI Pipeline
```bash
python main.py --mode hybrid
python main.py --mode parallel --all-languages
```

## UI Tabs
- **Dashboard** — Script stats (acts, sequences, shots, cast)
- **Models** — Select Free or Premium models per category
- **Pipeline** — Run pipeline with selected config
- **Script Story** — View human-enhanced script with emotions
- **Cast** — Pan-India cast with roles

## Agents

| Agent | Free Model | Premium Model |
|-------|------------|---------------|
| Script | Llama 3.2 (Ollama) | GPT-4o |
| Storyboard | SD XL (Local) | DALL-E 3 / Midjourney |
| Character | Qwen 2.5 (Ollama) | Claude 3.5 Sonnet |
| Voice | Coqui TTS | ElevenLabs |
| Animation | AnimateDiff | Runway Gen-4 |
| LipSync | Wav2Lip | Runway Lip Sync |
| Render | FFmpeg | FFmpeg + GPU |
| Quality | Llama 3.2 | GPT-4o |

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Root info |
| `GET /script` | Parsed script JSON |
| `GET /script/enhanced` | Human-enhanced story |
| `GET /models` | Available models |
| `POST /models/select` | Select a model |
| `POST /pipeline/run` | Run pipeline |
| `GET /pipeline/status` | Pipeline status |
