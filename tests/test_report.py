from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from tests.conftest import make_record
from token_triage.analyze import build_report
from token_triage.pricing import RATES_AS_OF
from token_triage.report import render_json, render_markdown


def _records():
    base = datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc)
    return [
        make_record(
            project="/home/user/web-app",
            project_slug="-home-user-web-app",
            session_id="s1",
            model="claude-opus-4-7",
            timestamp=base + timedelta(minutes=i),
            input_tokens=200,
            cache_write_5m_tokens=2_000,
            cache_read_tokens=1_500,
            output_tokens=400,
        )
        for i in range(3)
    ]


def test_render_json_round_trips() -> None:
    report = build_report(_records())
    rendered = render_json(report)
    parsed = json.loads(rendered)
    assert parsed["schema"] == "token-triage/1"
    assert parsed["totals"]["record_count"] == 3


def test_render_markdown_includes_sections() -> None:
    report = build_report(_records())
    md = render_markdown(report)
    assert "# Token Triage Report" in md
    assert "## Totals" in md
    assert "## Top projects by cost" in md
    assert "## Hottest 5-hour windows" in md
    assert "## Model breakdown" in md
    assert "## Findings" in md


def test_render_markdown_handles_empty() -> None:
    report = build_report([])
    md = render_markdown(report)
    assert "# Token Triage Report" in md
    assert "_No usage records found._" in md


def test_markdown_shows_rates_as_of_and_unpriced_section() -> None:
    report = build_report([make_record(model="claude-fable-6")])
    md = render_markdown(report)
    assert f"Built-in rates as of: {RATES_AS_OF}" in md
    assert "**(unpriced)**" in md
    assert "## Unpriced models" in md
    assert "`claude-fable-6`: 1 call(s)" in md


def test_markdown_omits_unpriced_section_when_all_priced() -> None:
    md = render_markdown(build_report([make_record(model="claude-sonnet-4-6")]))
    assert "## Unpriced models" not in md
    assert "(unpriced)" not in md
