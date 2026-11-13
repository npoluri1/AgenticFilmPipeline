# Agentic Film Studio — Project Documentation

**Name:** RUTHAMBHARA - Agentic Film Studio
**Version:** MVP complete, offline-first, deterministic
**Core business flow:** script → scene analysis → storyboard & cast → voice & animation → lipsync → render → quality gate → governance

---

## 1. Purpose

The Agentic Film Studio turns a screenplay into a complete short film with
multi-agent workflows: a script agent parses and breaks down scenes, a
storyboard agent frames shots, a character agent keeps cast identity
consistent, voice and animation agents generate performance, a lipsync agent
aligns dialogue, a render agent assembles the video, and a quality agent
gates the release. Every stage is deterministic and reproducible offline —
no LLM keys, no GPU, no ffmpeg required for the MVP (FFmpeg is used when
present for final assembly).

Everything on the dashboard comes from an actual execution. Ops: HTTP serves
the dashboard at `/dashboard` and the API at `/docs`; the same engine is
driven from the CLI.

---

## 2. Architecture

```text
                        ┌──────────────────────────────┐
                        │        FastAPI gateway       │
                        │  /dashboard  /api/v1/*  /docs│
                        └──────────────┬───────────────┘
                                       │
                        ┌──────────────▼───────────────┐
                        │     FilmGraphRunner          │
                        │  LangGraph StateGraph when   │
                        │  importable; builtin DAG     │
                        │  executor otherwise (repair: │
                        │  quality → repair → quality) │
                        └──────────────┬───────────────┘
                                       │
              ┌────────────────────────▼────────────────────────┐
              │  8 specialist agents (script, storyboard, char,  │
              │  voice, animation, lipsync, render, quality)    │
              └───────┬─────────────┬─────────────┬─────────────┘
                      │             │             │
              ┌───────▼──────┐ ┌────▼─────┐ ┌─────▼──────────┐
              │  GraphRAG    │ │ Domain   │ │ Provider       │
              │  screenwriting│ │ engine:  │ │ routers: LLM / │
              │  controls    │ │ scenes,  │ │ embed / TTS /  │
              │              │ │ shots,   │ │ image / video  │
              └──────────────┘ │ scan, CI │ └────────────────┘
                      │        └──────────┘
              ┌───────▼─────────────────────────────┐
              │ Guardrails · Memory · Evals · Audit │
              └─────────────────────────────────────┘
```

### Package layout

```text
src/
├── cli.py               CLI: serve | run | catalog | ask | providers | evals | mcp | legacy
├── config.py            environment + run options
├── graph_engine.py      FilmGraphRunner (LangGraph StateGraph + builtin fallback)
├── services.py          StudioService: submit/run/list, SSE bridge, RAG ask
├── providers.py         LLM / embeddings / TTS / image / video routers
├── rag.py               screenwriting retrieval
├── guardrails.py        injection + PII screening
├── memory.py            short/long/episodic memory
├── evals.py             EvalStore + PipelineEvaluator + finetune export (JSONL)
├── observability.py     metrics, traces, audit
├── mcp_server.py        MCP gateway + tools
├── dashboard_plugin.py  server-rendered dashboard
├── core/                event bus, text utilities
├── models/              humanizer, model registry, schemas
├── supervisor/          legacy orchestrator (kept for compatibility)
└── agents/              base + 8 specialist agents
```

### Runtime layers

| Layer | Module | Responsibility |
|-------|--------|----------------|
| API | `src/services.py` + `dashboard_plugin.py` | HTTP, dashboard HTML, SSE bridge |
| Engine | `src/graph_engine.py` | Stage graph, repair routing, result envelope |
| Agents | `src/agents/*` | 8 specialists with deterministic outputs |
| Providers | `src/providers.py` | LLM/embed/TTS/image/video router w/ offline defaults |
| RAG | `src/rag.py` | Screenwriting retrieval + hybrid search |
| Evals | `src/evals.py` | Quality gate, eval store, fine-tune export |
| Guardrails | `src/guardrails.py` | Prompt-injection and PII screening |
| MCP | `src/mcp_server.py` | Tool gateway |
| CLI | `src/cli.py` | `serve`, `run`, `catalog`, `ask`, `providers`, `evals`, `mcp`, `legacy` |

---

## 3. End-to-end production flow

### 3.1 Input

A request carries `script` (path or text), `options` (mode, quality, voice,
aspect) and `run_id`. `PipelineContext` holds the script, options and
per-agent outputs; `FilmState` (TypedDict) flows through the graph.

### 3.2 Stage contracts

| Stage | Agent | Produces |
|-------|-------|----------|
| `script` | Script Agent | Scene list, beat breakdown, dialogue lines |
| `storyboard` | Storyboard Agent | Shot list with framing and camera moves |
| `character` | Character Agent | Cast bible, appearance continuity |
| `voice` | Voice Agent | VO track + per-line timings |
| `animation` | Animation Agent | Motion/keyframe plan |
| `lipsync` | Lipsync Agent | Dialogue alignment report |
| `render` | Render Agent | Assembled video metadata (codec, fps, hash) |
| `quality` | Quality Agent | Rubric scores per scene, overall quality |

### 3.3 Repair loop

The quality node routes to `repair` when the mean score is below threshold
(max 2 rounds): the failing scene is recut/re-rendered and quality re-scores.
A cleaned re-scan is required before the governance gate.

### 3.4 Providers (free-first)

| Adapter | Offline default (free) | Optional upgrade |
|---------|------------------------|------------------|
| LLM | TemplateLLM (deterministic) | Ollama / OpenAI-compatible / Anthropic |
| Embeddings | HashEmbedder | SentenceTransformerEmbedder |
| TTS | WavSynth (silent placeholder) | EdgeTTS / Pyttsx3 |
| Image | StoryboardRenderer (Pillow frames) | DiffusersRenderer |
| Video | FFmpegVideo assembly | — |

---

## 4. Specialist agents

| Agent | File | Responsibility |
|-------|------|----------------|
| Script Agent | `agents/script_agent.py` | Parse the screenplay into scenes and beats |
| Storyboard Agent | `agents/storyboard_agent.py` | Frame each scene into shots |
| Character Agent | `agents/character_agent.py` | Cast bible, appearance consistency |
| Voice Agent | `agents/voice_agent.py` | VO lines, voice casting |
| Animation Agent | `agents/animation_agent.py` | Motion and keyframe plan |
| Lipsync Agent | `agents/lipsync_agent.py` | Dialogue alignment |
| Render Agent | `agents/render_agent.py` | Assembly into the final video |
| Quality Agent | `agents/quality_agent.py` | Rubric scoring, repair routing |

`supervisor/orchestrator.py` retains the legacy supervisor for compatibility;
new runs use the graph runner.

---

## 5. GraphRAG knowledge base

Screenwriting controls corpus (structure, pacing, dialogue, camera grammar,
three-act, cliffhangers) with hybrid BM25 + dense retrieval and one-hop
tag/category graph expansion. Citations are embedded in the agent outputs;
groundedness is scored in the eval suite.

---

## 6. Tools and MCP

`mcp_server.py` exposes the pipeline as tools behind a gateway: render
submission, catalog search, ask (RAG), and eval recording. `serve` + `mcp`
CLI subcommands wire the same gateway for tool-calling clients.

---

## 7. Governance and safety

- **Guardrails** (`guardrails.py`): injection detection + PII masking before
  ingestion; blocked input never enters the graph.
- **Audit** (`observability.py`): every agent invocation recorded with input
  hash, model, cost and policy decision.
- **Gate**: quality gate (`mean 0.967 · approve · 0 repairs`) must pass before
  the governance stage records the release decision.
- **Human approval** is required for paid render providers; automated gate
  prepares the release, humans approve it.

---

## 8. Evaluation rubric

`PipelineEvaluator` produces:

| Metric | Meaning |
|--------|---------|
| quality_score | Mean production rubric score from the quality gate |
| guardrail_safety | Guardrail score for the supplied inputs |
| per-agent reports | Overall score per specialist |

Eval store records every run; `export_finetune` emits a JSONL dataset
(`ruthambhara_finetune.jsonl`) for LoRA fine-tuning. Reference: **eval 0.992**.

---

## 9. MLOps and LoRA/QLoRA

Model registry (`models/model_registry.py`) + humanizer (`models/humanizer.py`)
+ eval-gated fine-tune export. The fine-tune dataset is built from recorded
eval runs; training itself is simulated offline in the MVP and labelled as such.

---

## 10. CI/CD and cloud deployment

The render agent emits a CI workflow (lint → build → render → upload) and a
3-cloud deployment plan (region, compute target, canary strategy, rollback,
monthly cost). The dashboard compares clouds side by side.

---

## 11. Dashboard

`GET /dashboard` serves the server-rendered MVP dashboard (KPIs, timeline,
agents, knowledge, evals, governance, stack). JSON: `/api/v1/dashboard/*`
for the React console.

---

## 12. API reference

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/dashboard` | HTML dashboard |
| GET | `/api/v1/dashboard/snapshot` | KPIs, agents, topology, governance, stack, demo |
| POST | `/api/v1/dashboard/demo` | Run the end-to-end proof |
| POST | `/api/v1/pipeline/run` | Run the film graph |
| POST | `/api/v1/codegen` | Generate artifacts |
| POST | `/api/v1/deploy` | Deployment plan |
| GET | `/docs` | OpenAPI |

CLI parity: `python -m agentic_film_pipeline run|serve|catalog|ask|providers|evals|mcp|legacy`.

---

## 13. Configuration

| Variable | Default | Effect |
|----------|---------|--------|
| `*_EMBEDDINGS` | `hashing` | `sentence-transformers` opts into MiniLM (lazy torch import) |
| `LLM_PROVIDER` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | unset | Optional LLM adapters (TemplateLLM default) |
| `OLLAMA_HOST` | `http://localhost:11434` | Local LLM endpoint |

No variable is required to run the dashboard or the demo. Python 3.11+ and
FFmpeg (optional) are the only hard requirements.

---

## 14. Running and testing

```powershell
# from the project root
python -m agentic_film_pipeline serve     # dashboard on :8080
python -m agentic_film_pipeline run --script data/script.txt
python -m pytest -q                       # 32 passed
```

Test coverage: `tests/test_api.py`, `tests/test_cli.py`,
`tests/test_pipeline.py` (graph, providers, guardrails, dashboards).

---

## 15. Stack coverage and honest status

| Status | Capabilities |
|--------|--------------|
| **Live** | FastAPI, LangGraph/DAG, multi-agent (8), ReAct/loops, tool calling, MCP, GraphRAG, memory, agent gateway, agent awareness, guardrails, observability, evals, governance/audit, CI/CD generation, FFmpeg assembly |
| **Fallback** | vector DB (in-process index), embeddings (hashing default; MiniLM opt-in), LangGraph (package-dependent) |
| **Simulated** | MLOps + LoRA/QLoRA (offline dataset + export), diffusion renders (Pillow storyboard frames) |
| **Available** | React console, Spring AI gateway, Kubernetes/IaC |

---

## 16. Design decisions

1. **Offline-first determinism.** The quality gate reproduces exactly without keys or GPUs.
2. **LangGraph with a real fallback.** A package named `langgraph` without `langgraph.graph` must not break the app.
3. **Free-first providers.** TemplateLLM, HashEmbedder, WavSynth, StoryboardRenderer and FFmpegVideo keep the pipeline real without paid services.
4. **Real checks over recorded fixtures.** Quality scoring runs over generated artifacts; repair is proven by a re-score.
5. **Legacy preservation.** The supervisor and its tests stay untouched.
6. **CLI + HTTP parity.** Every HTTP capability is reachable from the CLI subcommands.

---

## 17. Limitations and next steps

- The MVP does not execute generated code in-process; verification is static.
- Cloud plans are estimates, not live provisioning.
- LLM-backed generation is optional; the TemplateLLM default must remain a test mode.
- Vector DB adapters need a compatibility pass against current Chroma/Qdrant APIs.
- Real LoRA training requires PEFT/bitsandbytes and a GPU.

---

## 18. Full tech-stack matrix (this project)

| # | Technology | Status | Where it lives |
|---|-----------|--------|----------------|
| 1 | Python | live | whole backend |
| 2 | FastAPI | live | services + dashboard plugin |
| 3 | ReactJS / NextJS | available | repo `web/` console |
| 4 | Multi-Agents (8 specialists) | live | `src/agents/*` |
| 5 | ReAct reasoning | live | agent traces (think→act→observe→reflect) |
| 6 | Agent Loops / Graphs | live | `graph_engine.py` repair loop |
| 7 | LangChain | fallback | router pattern; optional |
| 8 | LangGraph | fallback | `FilmGraphRunner` (StateGraph or builtin) |
| 9 | RAG | live | `src/rag.py` |
| 10 | GraphRAG | live | tag/category graph expansion |
| 11 | VectorDB | fallback | in-process index; Chroma adapter exists |
| 12 | Embeddings | fallback | HashEmbedder default; SentenceTransformer opt-in |
| 13 | LlamaIndex (pattern) | live | ingestion/retrieval pattern in `rag.py` |
| 14 | MCP (server + gateway) | live | `src/mcp_server.py` |
| 15 | Tool Calling | live | tool registry + OpenAI-style schemas |
| 16 | Agent Gateway | live | capability routing |
| 17 | Agent Awareness | live | discovery graph |
| 18 | Memory | live | `src/memory.py` (short/long/episodic) |
| 19 | CrewAI | fallback | optional execution backend |
| 20 | AutoGen | fallback | optional execution backend |
| 21 | Spring AI | available | Java gateway service (separate) |
| 22 | LLMs (provider router) | fallback | Template/Ollama/OpenAI/Anthropic via `LLMRouter` |
| 23 | Prompting | live | agent prompt templates |
| 24 | Fine-Tuning (LoRA/QLoRA) | simulated | eval-gated JSONL export (`export_finetune`) |
| 25 | MLOps | simulated | `models/model_registry.py` + offline training |
| 26 | Evaluations (rubric) | live | `src/evals.py` |
| 27 | LLM Evaluation (groundedness) | live | RAG citation grounding |
| 28 | Observability | live | `src/observability.py` (metrics, traces, audit) |
| 29 | Guardrails | live | `src/guardrails.py` |
| 30 | Governance + audit | live | quality gate + audit trail |
| 31 | AI Workflows (CI/CD) | live | workflow generation + executor |
| 32 | Cloud | live | 3-cloud deployment plans |
| 33 | Kubernetes / IaC | available | infra templates |
| 34 | Design Patterns | live | Saga-style stage graph, State machine, Gateway, Registry, Fallback |
| 35 | Graphics engineering | live | Pillow/FFmpeg frame pipeline, camera moves |
| 36 | IoT | — | not in this project's scope |
| 37 | Quantum / Semiconductors | — | not in this project's scope |
| 38 | AGI/ASI, Agentic AI | live | 8-agent LangGraph orchestration |
| 39 | OpenClaw | fallback | provider router supports local OpenClaw-compatible endpoints |
