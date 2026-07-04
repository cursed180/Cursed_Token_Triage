"""``token-triage`` command-line entrypoint."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from token_triage import __version__
from token_triage.analyze import build_report, zero_metered_models
from token_triage.anonymize import anonymize_records
from token_triage.parser import collect_records, default_projects_dir
from token_triage.pricing import MODEL_RATES, load_rates_override
from token_triage.report import render_json, render_markdown


def _parse_since(value: str) -> datetime:
    """Accept either a duration like ``7d`` / ``24h`` or an ISO datetime."""
    value = value.strip()
    if not value:
        raise argparse.ArgumentTypeError("--since may not be empty")
    if value[-1] in {"d", "h"} and value[:-1].isdigit():
        n = int(value[:-1])
        delta = timedelta(days=n) if value[-1] == "d" else timedelta(hours=n)
        return datetime.now(timezone.utc) - delta
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--since must be ISO datetime or duration (e.g. '7d', '24h'); got {value!r}"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="token-triage",
        description=(
            "Local-only audit of Claude Code token usage. Reads "
            "~/.claude/projects/*.jsonl on your machine; nothing leaves it."
        ),
    )
    parser.add_argument(
        "--projects-dir",
        type=Path,
        default=None,
        help="Directory containing Claude Code project subdirectories "
        "(default: ~/.claude/projects).",
    )
    parser.add_argument(
        "--since",
        type=_parse_since,
        default=None,
        help="Only include records on or after this point. "
        "Accepts ISO datetime ('2026-04-01T00:00:00Z') or a duration ('7d', '24h').",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format (default: markdown).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the report to this file (default: stdout).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing --output file instead of refusing.",
    )
    parser.add_argument(
        "--rates",
        type=Path,
        default=None,
        help="JSON file overriding model rates (e.g. for Bedrock / Vertex / negotiated tiers).",
    )
    parser.add_argument(
        "--anon",
        action="store_true",
        help="Replace project paths and session ids with stable opaque hashes "
        "(useful for screenshots / sharing).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="How many projects to include in the top-projects table (default: 10).",
    )
    parser.add_argument(
        "--windows",
        type=int,
        default=5,
        help="How many sliding 5-hour windows to surface (default: 5).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"token-triage {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # Reports contain non-ASCII glyphs (e.g. the ``→`` in window ranges). A
    # redirected stdout on Windows defaults to the legacy code page (cp1252),
    # which can't encode them and raises UnicodeEncodeError. Force UTF-8 so the
    # report renders identically on every platform and through a pipe.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    args = build_parser().parse_args(argv)

    projects_dir = args.projects_dir or default_projects_dir()
    if not projects_dir.exists():
        print(
            f"error: projects directory not found: {projects_dir}",
            file=sys.stderr,
        )
        print(
            "hint: install Claude Code first or pass --projects-dir.",
            file=sys.stderr,
        )
        return 2

    rates_table = MODEL_RATES
    if args.rates is not None:
        try:
            rates_table = load_rates_override(args.rates)
        except (OSError, ValueError) as exc:
            print(f"error: failed to load rates from {args.rates}: {exc}", file=sys.stderr)
            return 2

    records = collect_records(projects_dir, since=args.since)
    if args.anon:
        records = anonymize_records(records)

    report = build_report(
        records,
        rates_table=rates_table,
        top_n=args.top,
        window_n=args.windows,
    )

    for row in zero_metered_models(report["model_breakdown"], rates_table):
        print(
            f"warning: model '{row['model']}' has {row['call_count']} call(s) but $0.00 cost"
            " — pricing may be missing (pass --rates)",
            file=sys.stderr,
        )

    rendered = render_json(report) if args.format == "json" else render_markdown(report)

    if args.output is not None:
        if args.output.exists() and not args.force:
            print(
                f"error: output file already exists: {args.output}",
                file=sys.stderr,
            )
            print(
                "hint: use --force to overwrite or choose a different path.",
                file=sys.stderr,
            )
            return 2
        try:
            args.output.write_text(rendered, encoding="utf-8")
        except OSError as exc:
            print(f"error: cannot write to {args.output}: {exc}", file=sys.stderr)
            return 2
    else:
        sys.stdout.write(rendered)
        if not rendered.endswith("\n"):
            sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
