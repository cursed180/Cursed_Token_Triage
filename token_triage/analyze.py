"""Aggregate usage records into the audit report shape.

Output sections:
    - totals: tokens by bucket, total cost, record count, time range
    - top_projects: ranked by USD cost
    - hot_5h_windows: top sliding 5-hour windows by cost (account-scoped)
    - model_breakdown: cost + call share per model
    - cache_health: read/write ratio per project
    - findings: ranked, human-readable waste-pattern callouts
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from token_triage.parser import UsageRecord
from token_triage.pricing import (
    MODEL_FAMILY_RANK,
    RATES_AS_OF,
    ModelRates,
    cost_breakdown_of,
    cost_of,
    family_of,
    lookup_rates,
    normalize_model_id,
)

WINDOW = timedelta(hours=5)


@dataclass
class ProjectStats:
    project: str
    cost_usd: float = 0.0
    input_tokens: int = 0
    cache_write_5m_tokens: int = 0
    cache_write_1h_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    record_count: int = 0
    sessions: set[str] = field(default_factory=set)
    model_costs: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    @property
    def cache_reuse(self) -> float:
        """Reads-per-write ratio. ``> 1`` means each cached chunk gets reused; ``< 1``
        means more is being written to cache than read back."""
        writes = self.cache_write_5m_tokens + self.cache_write_1h_tokens
        if writes == 0:
            return 0.0
        return self.cache_read_tokens / writes


def _record_cost(record: UsageRecord, rates_table: dict[str, ModelRates] | None) -> float:
    return cost_of(
        model=record.model,
        input_tokens=record.input_tokens,
        cache_write_5m_tokens=record.cache_write_5m_tokens,
        cache_write_1h_tokens=record.cache_write_1h_tokens,
        cache_read_tokens=record.cache_read_tokens,
        output_tokens=record.output_tokens,
        rates_table=rates_table,
    )


def aggregate_projects(
    records: Iterable[UsageRecord],
    rates_table: dict[str, ModelRates] | None = None,
) -> dict[str, ProjectStats]:
    by_project: dict[str, ProjectStats] = {}
    for record in records:
        stats = by_project.get(record.project)
        if stats is None:
            stats = ProjectStats(project=record.project)
            by_project[record.project] = stats
        c = _record_cost(record, rates_table)
        stats.cost_usd += c
        stats.input_tokens += record.input_tokens
        stats.cache_write_5m_tokens += record.cache_write_5m_tokens
        stats.cache_write_1h_tokens += record.cache_write_1h_tokens
        stats.cache_read_tokens += record.cache_read_tokens
        stats.output_tokens += record.output_tokens
        stats.record_count += 1
        if record.session_id:
            stats.sessions.add(record.session_id)
        stats.model_costs[normalize_model_id(record.model)] += c
    return by_project


def top_projects(stats: dict[str, ProjectStats], n: int = 10) -> list[ProjectStats]:
    return sorted(stats.values(), key=lambda s: s.cost_usd, reverse=True)[:n]


def hot_5h_windows(
    records: list[UsageRecord],
    rates_table: dict[str, ModelRates] | None = None,
    n: int = 5,
) -> list[dict[str, Any]]:
    """Rank sliding 5h windows by USD cost.

    Each record's timestamp opens a candidate window ``[t, t+5h)``; we sum the
    cost of all records whose timestamp falls in that range. Returns the top
    ``n`` non-overlapping windows (greedy: take the highest, drop everything
    that falls inside it, repeat).
    """
    if not records or n <= 0:
        return []
    sorted_records = sorted(records, key=lambda r: r.timestamp)
    record_costs = [_record_cost(r, rates_table) for r in sorted_records]
    n_records = len(sorted_records)

    candidates: list[tuple[float, int, int]] = []  # (cost, start_idx, end_idx_exclusive)
    j = 0
    running = 0.0
    for i in range(n_records):
        if j < i:
            j = i
            running = 0.0
        # Advance the window start so [start, end) is within WINDOW.
        # Here i is the start; extend j while timestamps fall inside.
        while j < n_records and sorted_records[j].timestamp - sorted_records[i].timestamp < WINDOW:
            running += record_costs[j]
            j += 1
        candidates.append((running, i, j))
        running -= record_costs[i]

    candidates.sort(key=lambda c: c[0], reverse=True)
    chosen: list[tuple[float, int, int]] = []
    used: list[tuple[int, int]] = []
    for cost, start, end in candidates:
        if cost <= 0:
            break
        if any(not (end <= u_start or start >= u_end) for u_start, u_end in used):
            continue
        chosen.append((cost, start, end))
        used.append((start, end))
        if len(chosen) >= n:
            break

    out: list[dict[str, Any]] = []
    for cost, start, end in chosen:
        window_records = sorted_records[start:end]
        first_ts = window_records[0].timestamp
        last_ts = window_records[-1].timestamp
        models = sorted({normalize_model_id(r.model) for r in window_records})
        projects = sorted({r.project for r in window_records})
        out.append(
            {
                "start": first_ts.isoformat(),
                "end": last_ts.isoformat(),
                "duration_minutes": round((last_ts - first_ts).total_seconds() / 60.0, 1),
                "cost_usd": round(cost, 4),
                "record_count": len(window_records),
                "models": models,
                "projects": projects,
            }
        )
    return out


def model_breakdown(
    records: Iterable[UsageRecord],
    rates_table: dict[str, ModelRates] | None = None,
) -> list[dict[str, Any]]:
    cost_by_model: dict[str, float] = defaultdict(float)
    calls_by_model: dict[str, int] = defaultdict(int)
    for r in records:
        m = normalize_model_id(r.model)
        cost_by_model[m] += _record_cost(r, rates_table)
        calls_by_model[m] += 1

    total_cost = sum(cost_by_model.values()) or 1.0
    total_calls = sum(calls_by_model.values()) or 1
    rows = []
    for model in sorted(cost_by_model, key=lambda m: cost_by_model[m], reverse=True):
        rows.append(
            {
                "model": model,
                "family": family_of(model),
                "cost_usd": round(cost_by_model[model], 4),
                "cost_share": round(cost_by_model[model] / total_cost, 4),
                "call_count": calls_by_model[model],
                "call_share": round(calls_by_model[model] / total_calls, 4),
                "unpriced": lookup_rates(model, rates_table) is None,
            }
        )
    return rows


def _short_record_count(records: Iterable[UsageRecord]) -> int:
    return sum(1 for _ in records)


def derive_findings(
    records: list[UsageRecord],
    project_stats: dict[str, ProjectStats],
    breakdown: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Surface ranked, opinionated waste callouts. Bounded to a small set."""
    findings: list[dict[str, Any]] = []

    # 1. Opus-when-Sonnet-fits: short turns on Opus that a Sonnet/Haiku probably
    # could have handled. We approximate "short" as <= 256 output tokens.
    opus_short_calls = 0
    opus_short_cost = 0.0
    for r in records:
        if family_of(r.model) == "opus" and r.output_tokens <= 256:
            opus_short_calls += 1
            opus_short_cost += cost_of(
                model=r.model,
                input_tokens=r.input_tokens,
                cache_write_5m_tokens=r.cache_write_5m_tokens,
                cache_write_1h_tokens=r.cache_write_1h_tokens,
                cache_read_tokens=r.cache_read_tokens,
                output_tokens=r.output_tokens,
            )
    if opus_short_calls > 0 and opus_short_cost > 0:
        findings.append(
            {
                "id": "opus_short_turns",
                "severity": "high" if opus_short_cost >= 1.0 else "medium",
                "title": "Opus calls with short output (likely Sonnet-fit)",
                "evidence": {
                    "call_count": opus_short_calls,
                    "estimated_cost_usd": round(opus_short_cost, 4),
                    "threshold_output_tokens": 256,
                },
                "recommendation": (
                    "Route short, decision-style turns to Sonnet 4.6 (5x cheaper input, "
                    "5x cheaper output at current rates). Reserve Opus for hard reasoning."
                ),
            }
        )

    # 2. Low cache hit ratio on a hot project. Pick the worst offender among
    # projects with non-trivial spend, ranked by ``(1 - ratio) * cost``.
    candidates = []
    for stats in project_stats.values():
        writes = stats.cache_write_5m_tokens + stats.cache_write_1h_tokens
        if writes == 0 or stats.cost_usd < 0.50:
            continue
        ratio = stats.cache_reuse
        if ratio >= 1.0:
            continue
        score = (1.0 - ratio) * stats.cost_usd
        candidates.append((score, stats, ratio, writes))
    if candidates:
        _, stats, ratio, writes = max(candidates, key=lambda c: c[0])
        findings.append(
            {
                "id": "low_cache_hit",
                "severity": "medium",
                "title": "Low cache-hit ratio on a high-spend project",
                "evidence": {
                    "project": stats.project,
                    "cache_read_tokens": stats.cache_read_tokens,
                    "cache_write_tokens": writes,
                    "ratio": round(ratio, 2),
                    "project_cost_usd": round(stats.cost_usd, 4),
                },
                "recommendation": (
                    "Each cache write costs 1.25x base input; reads cost 0.1x. A ratio "
                    "below 1.0 means you're paying to fill caches that aren't being reused. "
                    "Look for sessions that rebuild context frequently (frequent /clear, "
                    "huge variable instructions)."
                ),
            }
        )

    # 3. Long single-session burn -- a single sessionId responsible for >25% of total cost.
    cost_by_session: dict[str, float] = defaultdict(float)
    project_by_session: dict[str, str] = {}
    for r in records:
        if not r.session_id:
            continue
        cost_by_session[r.session_id] += _record_cost(r, None)
        project_by_session[r.session_id] = r.project
    total_cost = sum(s.cost_usd for s in project_stats.values()) or 0.0
    if cost_by_session and total_cost > 0:
        top_session, top_cost = max(cost_by_session.items(), key=lambda kv: kv[1])
        if top_cost / total_cost >= 0.25 and total_cost >= 1.0:
            findings.append(
                {
                    "id": "single_session_burn",
                    "severity": "medium",
                    "title": "One session dominates spend",
                    "evidence": {
                        "session_id": top_session,
                        "project": project_by_session[top_session],
                        "session_cost_usd": round(top_cost, 4),
                        "share_of_total": round(top_cost / total_cost, 3),
                    },
                    "recommendation": (
                        "Sessions that grow unboundedly often re-pay cache writes as the "
                        "context shifts. Break work into focused sessions; use /compact when "
                        "a session crosses ~50% of its window."
                    ),
                }
            )

    # 4. Family mix imbalance: Opus calls > 50% by count and only one family used.
    if breakdown:
        opus_calls = sum(b["call_count"] for b in breakdown if b["family"] == "opus")
        total_calls = sum(b["call_count"] for b in breakdown) or 1
        families_used = {b["family"] for b in breakdown if b["family"]}
        if opus_calls / total_calls >= 0.5 and len(families_used) <= 1:
            findings.append(
                {
                    "id": "single_tier_routing",
                    "severity": "low",
                    "title": "All routing on one model tier",
                    "evidence": {
                        "opus_call_share": round(opus_calls / total_calls, 3),
                        "families_used": sorted(f for f in families_used if f),
                    },
                    "recommendation": (
                        "Mix tiers. Haiku 4.5 handles search / formatting / boilerplate at "
                        "1/5 the Sonnet rate; Sonnet handles most implementation. Reserve Opus "
                        "for architectural reasoning."
                    ),
                }
            )

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: severity_rank.get(f["severity"], 3))
    return findings


def zero_metered_models(
    breakdown: list[dict[str, Any]],
    rates_table: dict[str, ModelRates] | None = None,
) -> list[dict[str, Any]]:
    """Return breakdown rows where a model has calls but no entry in the rates table.

    Keyed on ``lookup_rates(model) is None`` rather than ``cost_usd == 0.0`` so that
    models deliberately zeroed out via ``--rates`` (explicit operator override) are
    excluded.  Only models with no table entry at all — the exact bug class #11 fixed
    for Fable 5 / Mythos 5 — trigger the guardrail.

    Used by the CLI to emit a $0-meter warning on stderr.
    """
    return [
        row
        for row in breakdown
        if row["call_count"] > 0 and lookup_rates(row["model"], rates_table) is None
    ]


def build_report(
    records: list[UsageRecord],
    *,
    rates_table: dict[str, ModelRates] | None = None,
    top_n: int = 10,
    window_n: int = 5,
) -> dict[str, Any]:
    project_stats = aggregate_projects(records, rates_table)
    top_n_projects = top_projects(project_stats, n=top_n)
    breakdown = model_breakdown(records, rates_table)
    findings = derive_findings(records, project_stats, breakdown)
    windows = hot_5h_windows(records, rates_table, n=window_n)

    timestamps = [r.timestamp for r in records]
    total_cost = sum(s.cost_usd for s in project_stats.values())
    total_input = sum(s.input_tokens for s in project_stats.values())
    total_cache_writes = sum(
        s.cache_write_5m_tokens + s.cache_write_1h_tokens for s in project_stats.values()
    )
    total_cache_reads = sum(s.cache_read_tokens for s in project_stats.values())
    total_output = sum(s.output_tokens for s in project_stats.values())

    # Per-bucket cost totals: must sum per-record (each record may use a different
    # model with different per-bucket rates).  Summing aggregate token counts times
    # a single rate would be wrong when multiple models are present.
    bucket_input_cost = 0.0
    bucket_cache_write_cost = 0.0
    bucket_cache_read_cost = 0.0
    bucket_output_cost = 0.0
    for r in records:
        bd = cost_breakdown_of(
            model=r.model,
            input_tokens=r.input_tokens,
            cache_write_5m_tokens=r.cache_write_5m_tokens,
            cache_write_1h_tokens=r.cache_write_1h_tokens,
            cache_read_tokens=r.cache_read_tokens,
            output_tokens=r.output_tokens,
            rates_table=rates_table,
        )
        bucket_input_cost += bd.input_cost_usd
        bucket_cache_write_cost += bd.cache_write_cost_usd
        bucket_cache_read_cost += bd.cache_read_cost_usd
        bucket_output_cost += bd.output_cost_usd

    family_share: dict[str, float] = defaultdict(float)
    for row in breakdown:
        if row["family"]:
            family_share[row["family"]] += row["cost_share"]

    return {
        "schema": "token-triage/1",
        "rates_as_of": RATES_AS_OF,
        "unpriced_models": [
            {"model": row["model"], "call_count": row["call_count"]}
            for row in zero_metered_models(breakdown, rates_table)
        ],
        "totals": {
            "record_count": len(records),
            "total_cost_usd": round(total_cost, 4),
            "input_tokens": total_input,
            "input_cost_usd": round(bucket_input_cost, 4),
            "cache_write_tokens": total_cache_writes,
            "cache_write_cost_usd": round(bucket_cache_write_cost, 4),
            "cache_read_tokens": total_cache_reads,
            "cache_read_cost_usd": round(bucket_cache_read_cost, 4),
            "output_tokens": total_output,
            "output_cost_usd": round(bucket_output_cost, 4),
            "first_event": min(timestamps).isoformat() if timestamps else None,
            "last_event": max(timestamps).isoformat() if timestamps else None,
            "family_cost_share": {
                fam: round(family_share.get(fam, 0.0), 4) for fam in ("opus", "sonnet", "haiku")
            },
        },
        "top_projects": [
            {
                "project": s.project,
                "cost_usd": round(s.cost_usd, 4),
                "record_count": s.record_count,
                "session_count": len(s.sessions),
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "cache_read_tokens": s.cache_read_tokens,
                "cache_write_tokens": s.cache_write_5m_tokens + s.cache_write_1h_tokens,
                "cache_reuse": round(s.cache_reuse, 2),
                "model_costs": {m: round(c, 4) for m, c in sorted(s.model_costs.items())},
            }
            for s in top_n_projects
        ],
        "hot_5h_windows": windows,
        "model_breakdown": breakdown,
        "findings": findings,
    }


__all__ = [
    "MODEL_FAMILY_RANK",
    "ProjectStats",
    "aggregate_projects",
    "build_report",
    "derive_findings",
    "hot_5h_windows",
    "model_breakdown",
    "top_projects",
    "zero_metered_models",
]
