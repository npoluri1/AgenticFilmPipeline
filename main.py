#!/usr/bin/env python3
"""Entry point for the RUTHAMBHARA Agentic Film Studio.

Examples
--------
    python main.py                       # banner + command list
    python main.py serve                 # API + dashboard on http://localhost:8080
    python main.py run                   # one sample production run
    python main.py run --full --media    # full-film plan with rendered media
    python main.py mvp                   # sample run with all media enabled
    python main.py catalog               # acts / sequences / shots
    python main.py ask "Who is Veera?"   # GraphRAG question answering
    python main.py providers             # provider health
    python main.py evals --export        # evaluations + LoRA/QLoRA export
    python main.py mcp                   # MCP JSON-RPC over stdio
    python main.py legacy                # original AgentSupervisor pipeline

Any legacy invocation (``python main.py --script ... --mode hybrid``) still
works and is routed to the original supervisor pipeline.
"""
from __future__ import annotations

import argparse
import sys

from src.cli import (
    _configure_stdio,
    banner,
    cmd_ask,
    cmd_catalog,
    cmd_evals,
    cmd_legacy,
    cmd_mcp,
    cmd_providers,
    cmd_run,
    cmd_serve,
)


def _add_run_flags(parser: argparse.ArgumentParser, *, mvp: bool = False) -> None:
    parser.add_argument("--script", help="Override the screenplay path")
    parser.add_argument(
        "--mode", default="hybrid", choices=["hybrid", "parallel", "sequential"],
        help="Agent execution mode (default: hybrid)",
    )
    parser.add_argument("--language", default="te", help="Primary language code (default: te)")
    parser.add_argument("--tier", default="free", choices=["free", "premium"], help="Model tier")
    if not mvp:
        parser.add_argument("--full", action="store_true", help="Plan the full film")
        parser.add_argument("--analysis", action="store_true", help="Analysis-only scope")
        parser.add_argument("--no-media", action="store_true", help="Plan only; render no media")
        parser.add_argument("--media", action="store_true", help="Force media rendering on")
        parser.add_argument("--video", action="store_true", help="Force video assembly on")
        parser.add_argument("--max-shots", type=int, default=None, help="Cap rendered shots")
        parser.add_argument("--sequences", type=int, default=None, help="Sample sequence count")
        parser.add_argument("--threshold", type=float, default=None, help="Quality gate threshold")
        parser.add_argument("--repair-loops", type=int, default=None, help="Max repair loops")
        parser.add_argument("--approval", action="store_true", help="Require operator approval")
        parser.add_argument("--no-eval", action="store_true", help="Skip the LLM-rubric evaluation")
        parser.add_argument("--no-rag", action="store_true", help="Skip GraphRAG indexing")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=(
            "RUTHAMBHARA — agentic Telugu feature-film studio: 8 LangGraph agents, "
            "GraphRAG, MCP tools, evaluations, guardrails and a live dashboard."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Run the FastAPI server + dashboard")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true")
    serve.add_argument("--log-level", default="info")
    serve.set_defaults(func=cmd_serve)

    run = sub.add_parser("run", help="Execute one production run (synchronous)")
    _add_run_flags(run)
    run.add_argument("--json", action="store_true", help="Print the raw result as JSON")
    run.set_defaults(func=cmd_run)

    mvp = sub.add_parser("mvp", help="Sample run with every media stage enabled")
    _add_run_flags(mvp, mvp=True)
    mvp.set_defaults(func=_cmd_mvp)

    catalog = sub.add_parser("catalog", help="Print the parsed screenplay structure")
    catalog.add_argument("--script", default=None)
    catalog.add_argument("--json", action="store_true")
    catalog.set_defaults(func=cmd_catalog)

    ask = sub.add_parser("ask", help="Ask a GraphRAG question about the film")
    ask.add_argument("question")
    ask.add_argument("-k", type=int, default=6)
    ask.add_argument("--json", action="store_true")
    ask.set_defaults(func=cmd_ask)

    providers = sub.add_parser("providers", help="Show provider health")
    providers.add_argument("--json", action="store_true")
    providers.set_defaults(func=cmd_providers)

    evals = sub.add_parser("evals", help="Show evaluation history")
    evals.add_argument("--limit", type=int, default=25)
    evals.add_argument("--export", action="store_true", help="Export the fine-tuning dataset")
    evals.add_argument("--json", action="store_true")
    evals.set_defaults(func=cmd_evals)

    mcp = sub.add_parser("mcp", help="Serve MCP tools over stdio")
    mcp.set_defaults(func=cmd_mcp)

    legacy = sub.add_parser("legacy", help="Original AgentSupervisor pipeline")
    legacy.add_argument("--script", default=None)
    legacy.add_argument("--mode", default="hybrid", choices=["sequential", "parallel", "hybrid"])
    legacy.add_argument("--language", default="te")
    legacy.add_argument("--all-languages", action="store_true")
    legacy.set_defaults(func=cmd_legacy)

    return parser


def _apply_mvp_defaults(args):
    """MVP = sample scope, every media stage on, evaluation on."""
    args.full = False
    args.analysis = False
    args.media = True
    args.video = True
    args.no_media = False
    args.max_shots = getattr(args, "max_shots", None)
    args.sequences = getattr(args, "sequences", None)
    args.threshold = getattr(args, "threshold", None)
    args.repair_loops = getattr(args, "repair_loops", None)
    args.approval = False
    args.no_eval = False
    args.no_rag = False
    return args


def _cmd_mvp(args) -> int:
    return cmd_run(_apply_mvp_defaults(args))


def _legacy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=(
            "RUTHAMBHARA — Agentic Film Pipeline for Telugu Feature Film Production "
            "(legacy AgentSupervisor mode)"
        ),
    )
    parser.add_argument("--script", default=None, help="Path to the Ruthambhara screenplay")
    parser.add_argument("--mode", choices=["sequential", "parallel", "hybrid"], default="hybrid")
    parser.add_argument("--language", default="te", choices=["te", "ta", "hi", "ml", "kn", "en"])
    parser.add_argument("--all-languages", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)

    # Backwards compatibility: `python main.py --script ...` keeps working.
    if argv and argv[0].startswith("-"):
        args = _legacy_parser().parse_args(argv)
        return cmd_legacy(args)

    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        banner()
        return 0

    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
