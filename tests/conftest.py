"""Shared pytest fixtures for token-triage tests."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from token_triage.parser import UsageRecord


def make_record(
    *,
    project: str = "/home/user/myproject",
    project_slug: str | None = None,
    session_id: str = "session-aaaa",
    timestamp: datetime | None = None,
    model: str = "claude-sonnet-4-6",
    input_tokens: int = 100,
    cache_write_5m_tokens: int = 0,
    cache_write_1h_tokens: int = 0,
    cache_read_tokens: int = 0,
    output_tokens: int = 200,
) -> UsageRecord:
    if project_slug is None:
        project_slug = project.replace("/", "-")
    if timestamp is None:
        timestamp = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
    return UsageRecord(
        project=project,
        project_slug=project_slug,
        session_id=session_id,
        timestamp=timestamp,
        model=model,
        input_tokens=input_tokens,
        cache_write_5m_tokens=cache_write_5m_tokens,
        cache_write_1h_tokens=cache_write_1h_tokens,
        cache_read_tokens=cache_read_tokens,
        output_tokens=output_tokens,
    )


def write_session_jsonl(path: Path, records: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


@pytest.fixture
def synthetic_projects_dir(tmp_path: Path) -> Path:
    """Build a small synthetic Claude Code projects tree under tmp_path.

    Three projects are seeded:
      - webapp: Opus 4.7, many short-output turns (triggers opus-short-turns)
      - pipeline: Sonnet 4.6, big cache writes vs small reads (low cache hit)
      - scripts: Opus 4.7, single dominant session (single-session-burn)
    """
    root = tmp_path / "projects"
    root.mkdir()

    base = datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc)

    def _assistant(
        *,
        ts: datetime,
        session: str,
        model: str,
        input_tokens: int,
        cache_write_5m: int,
        cache_read: int,
        output_tokens: int,
    ) -> dict:
        return {
            "type": "assistant",
            "sessionId": session,
            "timestamp": ts.isoformat().replace("+00:00", "Z"),
            "message": {
                "model": model,
                "role": "assistant",
                "usage": {
                    "input_tokens": input_tokens,
                    "cache_creation_input_tokens": cache_write_5m,
                    "cache_read_input_tokens": cache_read,
                    "output_tokens": output_tokens,
                    "cache_creation": {
                        "ephemeral_5m_input_tokens": cache_write_5m,
                        "ephemeral_1h_input_tokens": 0,
                    },
                },
            },
        }

    def _user(ts: datetime, session: str) -> dict:
        return {"type": "user", "sessionId": session, "timestamp": ts.isoformat()}

    web_dir = root / "-home-user-webapp"
    web_records: list[dict] = []
    for i in range(30):
        ts = base + timedelta(minutes=4 * i)
        web_records.append(_user(ts, "web-session-1"))
        web_records.append(
            _assistant(
                ts=ts + timedelta(seconds=2),
                session="web-session-1",
                model="claude-opus-4-7",
                input_tokens=120,
                cache_write_5m=5_000,
                cache_read=4_000,
                output_tokens=200,
            )
        )
    write_session_jsonl(web_dir / "01.jsonl", web_records)

    pipeline_dir = root / "-home-user-pipeline"
    pipeline_records: list[dict] = []
    pipeline_base = base + timedelta(hours=5, minutes=30)
    for i in range(12):
        ts = pipeline_base + timedelta(minutes=5 * i)
        pipeline_records.append(_user(ts, "pipeline-session-1"))
        pipeline_records.append(
            _assistant(
                ts=ts + timedelta(seconds=2),
                session="pipeline-session-1",
                model="claude-sonnet-4-6",
                input_tokens=200,
                cache_write_5m=10_000,
                cache_read=1_000,
                output_tokens=500,
            )
        )
    write_session_jsonl(pipeline_dir / "01.jsonl", pipeline_records)

    scripts_dir = root / "-home-user-scripts"
    scripts_records: list[dict] = []
    scripts_base = base + timedelta(days=1, hours=1)
    for i in range(10):
        ts = scripts_base + timedelta(minutes=3 * i)
        scripts_records.append(_user(ts, "scripts-session-1"))
        scripts_records.append(
            _assistant(
                ts=ts + timedelta(seconds=2),
                session="scripts-session-1",
                model="claude-opus-4-7",
                input_tokens=500,
                cache_write_5m=20_000,
                cache_read=18_000,
                output_tokens=1_500,
            )
        )
    write_session_jsonl(scripts_dir / "01.jsonl", scripts_records)

    return root
