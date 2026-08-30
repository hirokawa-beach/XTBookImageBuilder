from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import sys

from .config import load_settings
from .control import StopRequested
from .pipeline import Pipeline
from .progress import ConsoleProgress


COMMANDS = ("all", "fetch-dumps", "extract", "metadata", "classify", "download", "convert", "build", "report")


def _parser() -> ArgumentParser:
    parser = ArgumentParser(prog="python3 -m jawikiimg")
    parser.add_argument("--config", type=Path, help="TOML config path (default: ./config.toml)")
    parser.add_argument("--workdir", type=Path, help="override working directory")
    parser.add_argument(
        "--json-progress", action="store_true",
        help="emit machine-readable JSON progress instead of terminal progress",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("gui", help="start Tkinter GUI")
    for name in COMMANDS:
        child = sub.add_parser(name)
        if name in ("all", "extract"):
            child.add_argument("--limit", type=int, help="stop discovery at N unique images")
        if name in ("all", "fetch-dumps"):
            child.add_argument("--date", help="dump snapshot YYYYMMDD (default: latest complete)")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    reporter = ConsoleProgress(json_mode=args.json_progress)
    try:
        settings = load_settings(args.config, args.workdir)
        if args.command == "gui":
            from .gui import run_gui
            run_gui(settings)
            return 0
        pipeline = Pipeline(settings)
        if args.command == "all":
            result = pipeline.all(limit=args.limit, date=args.date, progress=reporter)
        elif args.command == "fetch-dumps":
            result = pipeline.fetch_dumps(args.date, reporter)
        elif args.command == "extract":
            result = pipeline.extract(args.limit, reporter)
        elif args.command == "metadata":
            result = pipeline.metadata(reporter)
        elif args.command == "classify":
            result = pipeline.classify(reporter)
        elif args.command == "download":
            result = pipeline.download(reporter)
        elif args.command == "convert":
            result = pipeline.convert(reporter)
        elif args.command == "build":
            result = pipeline.build(reporter)
        else:
            result = pipeline.report()
        reporter.close()
        print(result)
        return 0
    except StopRequested:
        reporter.close()
        print("Safely stopped; completed records will be reused on the next run.", file=sys.stderr)
        return 130
    except (ValueError, RuntimeError, OSError) as exc:
        reporter.close()
        print(f"error: {exc}", file=sys.stderr)
        return 1
