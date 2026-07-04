"""Opt-in anonymization of project paths and session ids for shareable output."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from token_triage.parser import UsageRecord


def _short_hash(value: str, salt: str, length: int = 8) -> str:
    digest = hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()
    return digest[:length]


def anonymize_records(
    records: Iterable[UsageRecord],
    *,
    salt: str = "token-triage",
) -> list[UsageRecord]:
    """Return new records with stable opaque ids in place of project/session names.

    Hashing uses a fixed salt so the same input maps to the same id within one run,
    keeping the report internally consistent. Output is not reversible without the
    raw input.
    """
    out: list[UsageRecord] = []
    for r in records:
        out.append(
            UsageRecord(
                project=f"project-{_short_hash(r.project_slug, salt)}",
                project_slug=f"project-{_short_hash(r.project_slug, salt)}",
                session_id=f"session-{_short_hash(r.session_id, salt)}" if r.session_id else "",
                timestamp=r.timestamp,
                model=r.model,
                input_tokens=r.input_tokens,
                cache_write_5m_tokens=r.cache_write_5m_tokens,
                cache_write_1h_tokens=r.cache_write_1h_tokens,
                cache_read_tokens=r.cache_read_tokens,
                output_tokens=r.output_tokens,
            )
        )
    return out
