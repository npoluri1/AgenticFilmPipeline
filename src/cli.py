"""Command-line interface for the RUTHAMBHARA Agentic Film Studio.

The CLI is a thin shell over :data:`src.services.studio`, so every command uses
exactly the same runtime as the REST API, the MCP gateway and the dashboard.

    python main.py serve                 # FastAPI + dashboard on :8080
    python main.py run                   # one production run (sample scope)
    python main.py run --full --media    # full-film plan + rendered media
    python main.py catalog               # screenplay structure
    python main.py ask "Who is Veera?"   # GraphRAG question answering
    python main.py providers             # provider health
    python main.py evals --export        # evaluation summary / LoRA dataset
    python main.py mcp                   # MCP over stdio (for Claude Desktop)
    python main.py legacy                # the original AgentSupervisor pipeline
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

from src.config import settings


# ─────────────────────────────────────────────────────────────────────────────
# Output helpers
# ─────────────────────────────────────────────────────────────────────────────


def _configure_stdio() -> None:
    """Make Telugu output safe on Windows consoles (cp1252 by default)."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # pragma: no cover - exotic consoles
                pass


def _supports_color() -> bool:
    return bool(getattr(sys.stdout, "isatty", lambda: False)()) and not sys.platform.startswith("win")


def _c(text: str, code: str) -> str:
    if not _supports_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def _header(title: str) -> None:
    bar = "─" * 68
    print()
    print(_c(bar, "90"))
    print(_c(f"  {title}", "1;33"))
    print(_c(bar, "90"))


def _kv(pairs: list[tuple[str, Any]]) -> None:
    width = max((len(str(k)) for k, _ in pairs), default=0)
    for key, value in pairs:
        print(f"  {str(key).ljust(width)}  {value}")


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _status_line(label: str, ok: bool, detail: str = "") -> None:
    mark = _c("✔", "32") if ok else _c("✘", "31")
    print(f"  {mark} {label:<26} {detail}")


# ─────────────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────────────


def cmd_serve(args) -> int:
    import uvicorn

    host = args.host or settings.host
    port = args.port or settings.port
    _header("RUTHAMBHARA Agentic Film Studio — server")
    _kv([
        ("Dashboard", f"http://localhost:{port}/dashboard"),
        ("API docs", f"http://localhost:{port}/docs"),
        ("MCP", f"http://localhost:{port}/mcp"),
        ("Screenplay", settings.script),
        ("Reload", bool(args.reload)),
    ])
    print()
    uvicorn.run(
        "src.web.server:app",
        host=host,
        port=port,
        reload=bool(args.reload),
        log_level=args.log_level,
    )
    return 0


def _run_options(args) -> dict:
    scope = "full" if getattr(args, "full", False) else (
        "analysis" if getattr(args, "analysis", False) else "sample"
    )
    options: dict = {
        "scope": scope,
        "mode": getattr(args, "mode", "hybrid"),
        "language": getattr(args, "language", "te"),
        "tier": getattr(args, "tier", "free"),
        "eval": not getattr(args, "no_eval", False),
        "index_rag": not getattr(args, "no_rag", False),
    }
    script = getattr(args, "script", None)
    if script:
        options["script_path"] = str(Path(script))
    if getattr(args, "max_shots", None) is not None:
        options["max_shots"] = args.max_shots
    if getattr(args, "sequences", None) is not None:
        options["sample_sequences"] = args.sequences
    if getattr(args, "media", False):
        options["render_media"] = True
    if getattr(args, "no_media", False):
        options["render_media"] = False
        options["render_video"] = False
    if getattr(args, "video", False):
        options["render_video"] = True
    if getattr(args, "threshold", None) is not None:
        options["quality_threshold"] = args.threshold
    if getattr(args, "repair_loops", None) is not None:
        options["max_repair_loops"] = args.repair_loops
    if getattr(args, "approval", False):
        options["require_approval"] = True
    return options


def cmd_run(args) -> int:
    from src.services import studio

    if args.script and not Path(args.script).exists():
        print(f"Screenplay not found: {args.script}", file=sys.stderr)
        return 2

    options = _run_options(args)
    if getattr(args, "json", False):
        result = studio.pipeline.run(options)
        _print_json(result)
        return 0 if result.get("status") != "failed" else 1

    _header("Production run")
    _kv([
        ("Screenplay", studio.script.path(options.get("script_path"))),
        ("Scope", options["scope"]),
        ("Mode", options["mode"]),
        ("Language", options["language"]),
        ("Media", "on" if options.get("render_media") else "off"),
        ("Video", "on" if options.get("render_video") else "off"),
    ])
    print()
    print(_c("  running 8 agents through the LangGraph pipeline…", "36"))

    started = time.time()
    result = studio.pipeline.run(options)
    elapsed = time.time() - started

    if result.get("status") == "failed":
        print(_c(f"\n  ✘ run failed: {result.get('error')}", "31"))
        return 1

    film = result.get("film", {})
    quality = result.get("quality", {}) or {}
    evaluation = result.get("evaluation") or {}
    artifacts = result.get("artifacts", {}) or {}
    agents = result.get("agents", []) or []
    graph = result.get("graph", {}) or {}

    print()
    _print_run_summary(film, quality, evaluation, artifacts, agents, graph, elapsed)

    run_id = result.get("run_id", "")
    print()
    _kv([
        ("Run id", run_id),
        ("Dashboard", "http://localhost:%d/dashboard" % settings.port),
        ("Run JSON", f"/api/runs/{run_id}"),
        ("Artifacts", f"output/artifacts/<agent>/{run_id}/"),
    ])

    if result.get("status") == "awaiting_approval":
        print(_c("\n  ⏳ awaiting operator approval at the quality gate", "33"))
        print(f"     GET  /api/approvals?run_id={run_id}")
    return 0


def _print_run_summary(film, quality, evaluation, artifacts, agents, graph, elapsed) -> None:
    _kv([
        ("Film", f"{film.get('title', '—')} ({film.get('telugu_title', '')})"),
        ("Scope", f"{film.get('acts', '—')} acts · {film.get('sequences', '—')} sequences · "
                  f"{film.get('shots', '—')} shots"),
        ("Cast / themes", f"{film.get('cast', '—')} cast · {film.get('music_themes', '—')} themes"),
        ("Runtime", film.get("runtime", "—")),
        ("Languages", ", ".join(film.get("languages", []) or [])),
        ("Quality", f"mean {quality.get('mean_score', '—')} · "
                    f"decision {quality.get('decision', '—')} · "
                    f"{quality.get('repair_loops', 0)} repairs"),
        ("Evaluation", f"{evaluation.get('overall', '—')} "
                       f"({'passed' if evaluation.get('passed') else 'review'})"
                       if evaluation else "disabled"),
        ("Elapsed", f"{elapsed:.2f}s"),
    ])

    if agents:
        print()
        print(f"  {'Agent':<22} {'Status':<11} {'Time':>8}")
        print("  " + "─" * 44)
        for agent in agents:
            mark = {"completed": "✔", "failed": "✘"}.get(agent.get("status", ""), "·")
            print(
                f"  {mark} {agent.get('name', ''):<20} {agent.get('status', ''):<11} "
                f"{agent.get('duration_sec', 0):7.2f}s"
            )
        if graph.get("repair_loops"):
            print(f"\n  ↻ {graph['repair_loops']} repair loop(s): {graph.get('repairs') or []}")

    if artifacts:
        print()
        print("  Artifacts")
        for name, payload in artifacts.items():
            if isinstance(payload, dict):
                headline = ", ".join(
                    f"{k}={v}" for k, v in payload.items()
                    if isinstance(v, (str, int, float)) and k in {
                        "frames", "rendered", "count", "cards", "lines", "audio_files",
                        "clips", "shots", "mean_score", "sequence_reports",
                    }
                )
                print(f"    • {name:<12} {headline}")
            else:
                print(f"    • {name:<12} {payload}")


def cmd_catalog(args) -> int:
    from src.services import studio

    catalog = studio.script.catalog(getattr(args, "script", None))
    if args.json:
        _print_json(catalog)
        return 0

    _header(f"{catalog['title']} ({catalog['telugu_title']})")
    _kv([
        ("Runtime", f"{catalog['runtime']} ({catalog['runtime_minutes']} min)"),
        ("Languages", ", ".join(catalog["languages"])),
        ("Aspect ratio", catalog["aspect_ratio"]),
        ("Acts", catalog["total_acts"]),
        ("Sequences", catalog["total_sequences"]),
        ("Shots", catalog["total_shots"]),
        ("Cast", len(catalog["cast"])),
        ("Music themes", len(catalog["music_themes"])),
    ])
    print()
    for act in catalog["acts"]:
        print(_c(f"  ACT {act['number']} · {act['english_subtitle']} "
                 f"({act['start_time']} → {act['end_time']})", "1;33"))
        for seq in act["sequences"]:
            print(f"    {seq['number']:>2}. {seq['english_name']:<44} "
                  f"{seq['runtime_minutes']:>4}′ · {len(seq['shots'])} shots")
        print()
    return 0


def cmd_ask(args) -> int:
    from src.services import studio

    answer = studio.ask(args.question, k=args.k)
    if args.json:
        _print_json(answer)
        return 0

    _header("GraphRAG")
    print(f"  {_c('Q:', '1;33')} {args.question}\n")
    print(answer.get("answer", "(no answer)"))
    citations = answer.get("citations") or []
    if citations:
        print()
        print(_c("  Citations", "1;36"))
        for i, citation in enumerate(citations, start=1):
            score = citation.get("score")
            score_text = f" · score {score:.3f}" if isinstance(score, (int, float)) else ""
            print(f"  [{i}] {citation.get('kind', 'chunk')}{score_text}")
            text = str(citation.get("text", "")).replace("\n", " ")
            print(f"      {text[:220]}")
    return 0


def cmd_providers(args) -> int:
    from src.services import studio

    status = studio.providers.status(refresh=True)
    if args.json:
        _print_json(status)
        return 0

    _header("Providers")
    llm = status.get("llm", {})
    _kv([
        ("LLM backend", llm.get("active", "template-reasoner")),
        ("Fallbacks", ", ".join(llm.get("chain", []) or llm.get("fallbacks", []) or [])),
    ])
    print()
    _print_json(status)
    return 0


def cmd_evals(args) -> int:
    from src.services import studio

    summary = studio.evals.summary()
    if args.export:
        summary["finetune"] = studio.evals.export_finetune()
    if args.json:
        _print_json(summary)
        return 0

    _header("Evaluations")
    _kv([
        ("Evaluations", summary.get("total", 0)),
        ("Mean overall", summary.get("mean_overall", "—")),
        ("Pass rate", summary.get("pass_rate", "—")),
    ])
    entries = studio.evals.list(limit=args.limit)
    if entries:
        print()
        print(f"  {'Eval id':<28} {'Run':<26} {'Overall':>8} {'Pass':>6}")
        print("  " + "─" * 72)
        for entry in entries:
            print(f"  {entry.get('eval_id', ''):<28} {entry.get('run_id', ''):<26} "
                  f"{entry.get('overall', 0):>8.3f} {'yes' if entry.get('passed') else 'no':>6}")
    if args.export:
        print()
        _kv([("Fine-tune export", summary["finetune"])])
    return 0


def cmd_mcp(args) -> int:
    from src.mcp_server import serve_stdio

    serve_stdio()
    return 0


def cmd_legacy(args) -> int:
    """Original AgentSupervisor pipeline (sequential, in-process, no media)."""
    from src.models.schemas import PipelineContext, PipelineMode
    from src.supervisor import AgentSupervisor

    script = Path(args.script) if args.script else settings.script
    if not script.exists():
        print(f"Screenplay not found: {script}", file=sys.stderr)
        return 2

    ctx = PipelineContext(
        pipeline_id=f"legacy_{int(time.time())}",
        mode=PipelineMode(args.mode),
        source_script_path=str(script),
        language=args.language,
        total_duration_minutes=205.0,
        options={},
    )
    supervisor = AgentSupervisor()
    started = time.time()
    results = supervisor.run(ctx)
    elapsed = time.time() - started
    print(supervisor.get_pipeline_summary(results, ctx))
    print(f"\n  Wall clock time: {elapsed:.2f}s")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Suggestion helper (used by the "status" command / no-arg banner)
# ─────────────────────────────────────────────────────────────────────────────


def banner() -> None:
    _header("RUTHAMBHARA Agentic Film Studio")
    _kv([
        ("Version", settings.version),
        ("Screenplay", settings.script),
        ("Default scope", settings.default_scope),
        ("LLM", "ollama" if settings.use_ollama else "free deterministic reasoner"),
    ])
    print()
    print("  Commands")
    for line in (
        "serve                 start the API + dashboard (http://localhost:8080/dashboard)",
        "run [--full] [--media] one end-to-end production run",
        "catalog               print acts / sequences / shots",
        "ask \"question\"        GraphRAG over the screenplay",
        "providers             provider health",
        "evals [--export]      evaluation summary and LoRA/QLoRA export",
        "mcp                   MCP JSON-RPC over stdio",
        "legacy                original AgentSupervisor pipeline",
    ):
        print(f"    {line}")


def entrypoint() -> int:
    """Console-script entry point (``ruthambhara``)."""
    from main import main

    return main()

