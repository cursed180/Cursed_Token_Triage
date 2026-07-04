"""Parse Claude Code event-log JSONL files into a flat list of usage records.

Every directory under ``~/.claude/projects/`` corresponds to one ``cwd``.
The directory name is the absolute path with separators rewritten to ``-``.
Each ``*.jsonl`` file inside is a single Claude Code session; assistant turns
contain a ``message.usage`` block we attribute to the project + session.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class UsageRecord:
    project: str  # decoded cwd, e.g. "/home/user/myproject"
    project_slug: str  # raw directory name from ~/.claude/projects/
    session_id: str
    timestamp: datetime
    model: str
    input_tokens: int
    cache_write_5m_tokens: int
    cache_write_1h_tokens: int
    cache_read_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.cache_write_5m_tokens
            + self.cache_write_1h_tokens
            + self.cache_read_tokens
            + self.output_tokens
        )


def default_projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def decode_project_slug(slug: str) -> str:
    """Reverse the directory-name encoding back to a path-like string.

    Claude Code rewrites ``/`` to ``-`` in cwd to form the directory name.
    ``-home-user-myproject`` -> ``/home/user/myproject``. The mapping is lossy
    (a real ``-`` in the original path becomes indistinguishable from ``/``),
    so this is best-effort: we use it for display only.
    """
    if not slug:
        return slug
    return "/" + slug.lstrip("-").replace("-", "/") if slug.startswith("-") else slug


def _parse_timestamp(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw).astimezone(timezone.utc)
    except ValueError:
        return None


def _split_cache_writes(usage: dict) -> tuple[int, int]:
    """Return (5m_writes, 1h_writes) given a single ``usage`` dict.

    Older log lines have only ``cache_creation_input_tokens``; newer ones
    additionally split via ``cache_creation.ephemeral_5m_input_tokens`` /
    ``ephemeral_1h_input_tokens``. We trust the split when available; otherwise
    we attribute the whole creation count to the 5m bucket (the API default).
    """
    total = int(usage.get("cache_creation_input_tokens") or 0)
    detail = usage.get("cache_creation") or {}
    if isinstance(detail, dict):
        m5 = int(detail.get("ephemeral_5m_input_tokens") or 0)
        h1 = int(detail.get("ephemeral_1h_input_tokens") or 0)
        if m5 + h1 > 0:
            return m5, h1
    return total, 0


def parse_record(record: dict, project: str, project_slug: str) -> UsageRecord | None:
    """Convert one parsed JSONL line into a ``UsageRecord``, or ``None`` to skip."""
    if record.get("type") != "assistant":
        return None
    message = record.get("message") or {}
    usage = message.get("usage") or {}
    model = message.get("model") or ""
    if not model or not usage:
        return None
    ts = _parse_timestamp(record.get("timestamp", ""))
    if ts is None:
        return None
    m5, h1 = _split_cache_writes(usage)
    rec = UsageRecord(
        project=project,
        project_slug=project_slug,
        session_id=str(record.get("sessionId") or ""),
        timestamp=ts,
        model=model,
        input_tokens=int(usage.get("input_tokens") or 0),
        cache_write_5m_tokens=m5,
        cache_write_1h_tokens=h1,
        cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
    )
    # Skip the ``<synthetic>`` sentinel only. Claude Code emits ``"model": "<synthetic>"``
    # entries for API-error / no-response turns: a populated ``usage`` block but all-zero
    # token counts. They carry no cost and no analytical signal, and -- left in -- would
    # trip a spurious "$0 metered" warning (the pseudo-model has no pricing entry). We
    # gate on the model id, not ``total_tokens == 0`` alone, so a *real* model that emits
    # a zero-token turn (streaming abort, rate-limit reject, partial failure) is retained
    # and counted rather than silently dropped.
    if rec.model == "<synthetic>" and rec.total_tokens == 0:
        return None
    return rec


def iter_records_from_file(path: Path, *, project_slug: str | None = None) -> Iterator[UsageRecord]:
    """Yield usage records from a single ``.jsonl`` file."""
    slug = project_slug or path.parent.name
    project = decode_project_slug(slug)
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            usage_record = parse_record(record, project=project, project_slug=slug)
            if usage_record is not None:
                yield usage_record


def iter_jsonl_files(projects_dir: Path) -> Iterator[Path]:
    """Yield every ``*.jsonl`` file under any first-level project directory."""
    if not projects_dir.exists():
        return
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        yield from sorted(project_dir.glob("*.jsonl"))


def collect_records(
    projects_dir: Path,
    *,
    since: datetime | None = None,
) -> list[UsageRecord]:
    """Collect all usage records from a projects directory, optionally filtered by ``since``.

    Files that can't be read (permission denied, transient I/O error) are skipped
    with a warning on stderr; this keeps a single bad file from aborting the run
    on systems with unusual ``.claude`` directory permissions.
    """
    records: list[UsageRecord] = []
    for path in iter_jsonl_files(projects_dir):
        try:
            for record in iter_records_from_file(path):
                if since is None or record.timestamp >= since:
                    records.append(record)
        except OSError as exc:
            print(f"warning: skipping {path}: {exc}", file=sys.stderr)
            continue
    return records


def filter_since(records: Iterable[UsageRecord], since: datetime) -> list[UsageRecord]:
    return [r for r in records if r.timestamp >= since]
