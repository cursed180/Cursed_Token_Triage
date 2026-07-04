from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from token_triage.parser import (
    collect_records,
    decode_project_slug,
    iter_jsonl_files,
    iter_records_from_file,
    parse_record,
)


def test_decode_project_slug_round_trip() -> None:
    assert decode_project_slug("-home-user-myproject") == "/home/user/myproject"
    assert decode_project_slug("") == ""
    # Non-leading-dash slugs are returned as-is.
    assert decode_project_slug("relative-thing") == "relative-thing"


def test_parse_record_assistant() -> None:
    record = {
        "type": "assistant",
        "sessionId": "abc",
        "timestamp": "2026-04-01T12:00:00Z",
        "message": {
            "model": "claude-opus-4-7",
            "usage": {
                "input_tokens": 100,
                "cache_creation_input_tokens": 5_000,
                "cache_read_input_tokens": 4_000,
                "output_tokens": 200,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 5_000,
                    "ephemeral_1h_input_tokens": 0,
                },
            },
        },
    }
    parsed = parse_record(
        record, project="/home/user/myproject", project_slug="-home-user-myproject"
    )
    assert parsed is not None
    assert parsed.model == "claude-opus-4-7"
    assert parsed.input_tokens == 100
    assert parsed.cache_write_5m_tokens == 5_000
    assert parsed.cache_write_1h_tokens == 0
    assert parsed.cache_read_tokens == 4_000
    assert parsed.output_tokens == 200
    assert parsed.session_id == "abc"
    assert parsed.timestamp == datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)


def test_parse_record_skips_non_assistant() -> None:
    assert parse_record({"type": "user"}, project="x", project_slug="-x") is None
    assert parse_record({"type": "queue-operation"}, project="x", project_slug="-x") is None


def test_parse_record_skips_missing_usage() -> None:
    record = {
        "type": "assistant",
        "timestamp": "2026-04-01T12:00:00Z",
        "message": {"model": "claude-opus-4-7"},
    }
    assert parse_record(record, project="x", project_slug="-x") is None


def test_parse_record_skips_zero_token_synthetic() -> None:
    """``<synthetic>`` API-error turns have a populated usage block but all-zero
    tokens; they are not real usage and must be skipped (else they fire a spurious
    $0-meter warning, since the pseudo-model has no pricing entry)."""
    record = {
        "type": "assistant",
        "sessionId": "s1",
        "timestamp": "2026-04-01T12:00:00Z",
        "message": {
            "model": "<synthetic>",
            "usage": {
                "input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "output_tokens": 0,
            },
        },
    }
    assert parse_record(record, project="x", project_slug="-x") is None


def test_parse_record_keeps_zero_token_real_model() -> None:
    """A *real* model emitting an all-zero usage block (streaming abort, rate-limit
    reject, partial failure) must be retained -- the zero-token skip is gated on the
    ``<synthetic>`` sentinel, not on ``total_tokens == 0`` alone, so a real turn is
    never silently dropped (TT #14)."""
    record = {
        "type": "assistant",
        "sessionId": "s1",
        "timestamp": "2026-04-01T12:00:00Z",
        "message": {
            "model": "claude-opus-4-8",
            "usage": {
                "input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "output_tokens": 0,
            },
        },
    }
    parsed = parse_record(record, project="x", project_slug="-x")
    assert parsed is not None
    assert parsed.model == "claude-opus-4-8"
    assert parsed.total_tokens == 0


def test_parse_record_handles_old_schema_without_split() -> None:
    """Older event logs only have ``cache_creation_input_tokens`` (no split)."""
    record = {
        "type": "assistant",
        "sessionId": "abc",
        "timestamp": "2026-04-01T12:00:00Z",
        "message": {
            "model": "claude-sonnet-4-6",
            "usage": {
                "input_tokens": 100,
                "cache_creation_input_tokens": 1_000,
                "cache_read_input_tokens": 0,
                "output_tokens": 50,
            },
        },
    }
    parsed = parse_record(record, project="x", project_slug="-x")
    assert parsed is not None
    # Without a split, the whole creation count goes to the 5m bucket (API default).
    assert parsed.cache_write_5m_tokens == 1_000
    assert parsed.cache_write_1h_tokens == 0


def test_iter_records_from_file(tmp_path: Path) -> None:
    project_dir = tmp_path / "-home-user-myproject"
    project_dir.mkdir()
    session_path = project_dir / "session.jsonl"
    lines = [
        {"type": "user", "timestamp": "2026-04-01T12:00:00Z", "sessionId": "s1"},
        {
            "type": "assistant",
            "sessionId": "s1",
            "timestamp": "2026-04-01T12:00:02Z",
            "message": {
                "model": "claude-sonnet-4-6",
                "usage": {
                    "input_tokens": 10,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "output_tokens": 5,
                },
            },
        },
        "this is not json",
        {"type": "queue-operation"},
    ]
    with session_path.open("w") as f:
        for entry in lines:
            if isinstance(entry, dict):
                f.write(json.dumps(entry) + "\n")
            else:
                f.write(entry + "\n")

    records = list(iter_records_from_file(session_path))
    assert len(records) == 1
    assert records[0].input_tokens == 10
    assert records[0].project == "/home/user/myproject"


def test_iter_records_from_file_skips_synthetic(tmp_path: Path) -> None:
    """A ``<synthetic>`` all-zero turn in a session file is excluded end-to-end."""
    project_dir = tmp_path / "-home-user-myproject"
    project_dir.mkdir()
    session_path = project_dir / "session.jsonl"
    lines = [
        {
            "type": "assistant",
            "sessionId": "s1",
            "timestamp": "2026-04-01T12:00:00Z",
            "message": {
                "model": "<synthetic>",
                "usage": {
                    "input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "output_tokens": 0,
                },
            },
        },
        {
            "type": "assistant",
            "sessionId": "s1",
            "timestamp": "2026-04-01T12:00:02Z",
            "message": {
                "model": "claude-sonnet-4-6",
                "usage": {
                    "input_tokens": 10,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "output_tokens": 5,
                },
            },
        },
    ]
    with session_path.open("w") as f:
        for entry in lines:
            f.write(json.dumps(entry) + "\n")

    records = list(iter_records_from_file(session_path))
    assert len(records) == 1
    assert records[0].model == "claude-sonnet-4-6"


def test_iter_jsonl_files_skips_non_dirs(tmp_path: Path) -> None:
    (tmp_path / "stray-file.jsonl").write_text("")
    project_dir = tmp_path / "-home-user-myproject"
    project_dir.mkdir()
    (project_dir / "session.jsonl").write_text("")
    files = list(iter_jsonl_files(tmp_path))
    assert len(files) == 1
    assert files[0].parent.name == "-home-user-myproject"


def test_iter_jsonl_files_missing_dir(tmp_path: Path) -> None:
    assert list(iter_jsonl_files(tmp_path / "does-not-exist")) == []


def test_collect_records_filters_since(synthetic_projects_dir: Path) -> None:
    cutoff = datetime(2026, 4, 2, 0, 0, tzinfo=timezone.utc)
    records = collect_records(synthetic_projects_dir, since=cutoff)
    assert records, "expected some records on or after Apr 2"
    assert all(r.timestamp >= cutoff for r in records)


def test_collect_records_unfiltered(synthetic_projects_dir: Path) -> None:
    records = collect_records(synthetic_projects_dir)
    projects = {r.project for r in records}
    assert "/home/user/webapp" in projects
    assert "/home/user/pipeline" in projects
    assert "/home/user/scripts" in projects
