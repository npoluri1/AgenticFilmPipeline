"""CLI parsing and option-mapping tests (no pipeline execution)."""
from __future__ import annotations

import main
from src.cli import _run_options


def test_parser_has_all_commands():
    parser = main.build_parser()
    for command in ("serve", "run", "mvp", "catalog", "ask", "providers", "evals", "mcp", "legacy"):
        args = parser.parse_args([command] if command != "ask" else ["ask", "q"])
        assert args.command == command


def test_run_options_full_media():
    args = main.build_parser().parse_args(["run", "--full", "--media", "--video"])
    options = _run_options(args)
    assert options["scope"] == "full"
    assert options["render_media"] is True
    assert options["render_video"] is True
    assert options["eval"] is True


def test_run_options_no_media_disables_video():
    args = main.build_parser().parse_args(["run", "--no-media"])
    options = _run_options(args)
    assert options["render_media"] is False
    assert options["render_video"] is False


def test_mvp_forces_media():
    args = main._apply_mvp_defaults(main.build_parser().parse_args(["mvp"]))
    options = _run_options(args)
    assert options["scope"] == "sample"
    assert options["render_media"] is True
    assert options["render_video"] is True
