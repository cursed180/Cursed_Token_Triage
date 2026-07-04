"""Generate the sample report JSON + Markdown shipped with this repo.

Run from the repo root:

    python -m examples.generate_sample

The generated files (``examples/sample-output.json`` and
``examples/sample-output.md``) ship as marketing artefacts and as a stable
fixture for the CI privacy scrub. The data is fully synthetic — no real Claude
Code logs are read.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from token_triage.analyze import build_report
from token_triage.parser import UsageRecord
from token_triage.report import render_json, render_markdown


def _record(
    *,
    project: str,
    session_id: str,
    timestamp: datetime,
    model: str,
    input_tokens: int,
    cache_write_5m_tokens: int,
    cache_read_tokens: int,
    output_tokens: int,
) -> UsageRecord:
    return UsageRecord(
        project=project,
        project_slug=project.replace("/", "-"),
        session_id=session_id,
        timestamp=timestamp,
        model=model,
        input_tokens=input_tokens,
        cache_write_5m_tokens=cache_write_5m_tokens,
        cache_write_1h_tokens=0,
        cache_read_tokens=cache_read_tokens,
        output_tokens=output_tokens,
    )


def build_synthetic_records() -> list[UsageRecord]:
    base = datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc)
    records: list[UsageRecord] = []

    # Project: ai-coding-cli — heavy Opus user with short turns
    for i in range(35):
        records.append(
            _record(
                project="/home/devuser/ai-coding-cli",
                session_id="ai-coding-cli/session-001",
                timestamp=base + timedelta(minutes=4 * i),
                model="claude-opus-4-7",
                input_tokens=180,
                cache_write_5m_tokens=4_500,
                cache_read_tokens=3_500,
                output_tokens=220,
            )
        )

    # Project: revenue-dashboard — Sonnet, big writes vs small reads
    pipeline_base = base + timedelta(hours=6)
    for i in range(18):
        records.append(
            _record(
                project="/home/devuser/revenue-dashboard",
                session_id="revenue-dashboard/session-001",
                timestamp=pipeline_base + timedelta(minutes=5 * i),
                model="claude-sonnet-4-6",
                input_tokens=300,
                cache_write_5m_tokens=12_000,
                cache_read_tokens=900,
                output_tokens=600,
            )
        )

    # Project: infra-scripts — single Opus session that dominates spend
    scripts_base = base + timedelta(days=1, hours=2)
    for i in range(14):
        records.append(
            _record(
                project="/home/devuser/infra-scripts",
                session_id="infra-scripts/session-001",
                timestamp=scripts_base + timedelta(minutes=4 * i),
                model="claude-opus-4-7",
                input_tokens=600,
                cache_write_5m_tokens=18_000,
                cache_read_tokens=15_000,
                output_tokens=1_400,
            )
        )

    # Project: docs-site — well-routed Haiku user, low cost (kept off the top)
    for i in range(8):
        records.append(
            _record(
                project="/home/devuser/docs-site",
                session_id="docs-site/session-001",
                timestamp=scripts_base + timedelta(hours=4, minutes=2 * i),
                model="claude-haiku-4-5",
                input_tokens=80,
                cache_write_5m_tokens=200,
                cache_read_tokens=400,
                output_tokens=300,
            )
        )

    return records


def main() -> None:
    out_dir = Path(__file__).parent
    records = build_synthetic_records()
    report = build_report(records, top_n=5, window_n=3)

    json_path = out_dir / "sample-output.json"
    md_path = out_dir / "sample-output.md"
    json_path.write_text(render_json(report) + "\n")
    md_path.write_text(render_markdown(report))
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
