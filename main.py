#!/usr/bin/env python3
import argparse
import sys
import time
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from src.models.schemas import PipelineContext, PipelineMode
from src.supervisor import AgentSupervisor
from src.utils.logger import get_logger

logger = get_logger("main")

LANGUAGES = {
    "te": "Telugu", "ta": "Tamil", "hi": "Hindi",
    "ml": "Malayalam", "kn": "Kannada", "en": "English",
}


def main():
    parser = argparse.ArgumentParser(
        description="RUTHAMBHARA — Agentic Film Pipeline for Telugu Feature Film Production"
    )
    parser.add_argument("--script", type=str,
                        default="D:\\WorkSpace\\Telugu_Film_Stroy_Board\\feature\\ఋతంభర_పూర్తి_సినిమా_స్క్రిప్ట్.md",
                        help="Path to Ruthambhara script file")
    parser.add_argument("--mode", choices=["sequential", "parallel", "hybrid"],
                        default="hybrid", help="Pipeline execution mode")
    parser.add_argument("--language", default="te", choices=list(LANGUAGES.keys()),
                        help="Primary language code")
    parser.add_argument("--all-languages", action="store_true",
                        help="Process all film languages")

    args = parser.parse_args()

    script_path = args.script
    if not Path(script_path).exists():
        print(f"Script not found: {script_path}")
        sys.exit(1)

    ctx = PipelineContext(
        pipeline_id=f"ruthambhara_{int(time.time())}",
        mode=PipelineMode(args.mode),
        source_script_path=script_path,
        language=args.language,
        total_duration_minutes=205.0,
    )

    supervisor = AgentSupervisor()

    print(f"\n  RUTHAMBHARA — Agentic Film Pipeline")
    print(f"  Script: {script_path}")
    print(f"  Mode: {args.mode}")
    print(f"  Language: {LANGUAGES.get(args.language, args.language)}")
    if args.all_languages:
        print(f"  All languages: enabled")
    print()

    start = time.time()
    results = supervisor.run(ctx)
    elapsed = time.time() - start

    print(supervisor.get_pipeline_summary(results, ctx))
    print(f"\n  Wall clock time: {elapsed:.2f}s")
    print()

    if args.all_languages and ctx.film:
        print("  Languages to process:")
        for lang in ctx.film.languages:
            print(f"    - {LANGUAGES.get(lang, lang)}")
        print()


if __name__ == "__main__":
    main()
