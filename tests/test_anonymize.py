from __future__ import annotations

from datetime import datetime, timezone

from token_triage.anonymize import anonymize_records
from token_triage.parser import UsageRecord


def _record(project: str, slug: str, session: str) -> UsageRecord:
    return UsageRecord(
        project=project,
        project_slug=slug,
        session_id=session,
        timestamp=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
        model="claude-sonnet-4-6",
        input_tokens=100,
        cache_write_5m_tokens=0,
        cache_write_1h_tokens=0,
        cache_read_tokens=0,
        output_tokens=200,
    )


def test_anonymize_strips_paths() -> None:
    records = [_record("/home/user/secret-thing", "-home-user-secret-thing", "session-abc")]
    out = anonymize_records(records)
    assert "secret-thing" not in out[0].project
    assert "secret-thing" not in out[0].project_slug
    assert "abc" not in out[0].session_id
    assert out[0].project.startswith("project-")
    assert out[0].session_id.startswith("session-")


def test_anonymize_is_stable_within_run() -> None:
    records = [
        _record("/home/user/secret-thing", "-home-user-secret-thing", "session-abc"),
        _record("/home/user/secret-thing", "-home-user-secret-thing", "session-abc"),
    ]
    out = anonymize_records(records)
    assert out[0].project == out[1].project
    assert out[0].session_id == out[1].session_id


def test_anonymize_preserves_token_counts() -> None:
    records = [_record("/home/user/p1", "-home-user-p1", "s1")]
    out = anonymize_records(records)
    assert out[0].input_tokens == 100
    assert out[0].output_tokens == 200
    assert out[0].timestamp == records[0].timestamp


def test_anonymize_handles_missing_session_id() -> None:
    records = [_record("/home/user/p1", "-home-user-p1", "")]
    out = anonymize_records(records)
    assert out[0].session_id == ""
