from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import make_record
from token_triage.analyze import (
    aggregate_projects,
    build_report,
    derive_findings,
    hot_5h_windows,
    model_breakdown,
    top_projects,
    zero_metered_models,
)


@pytest.fixture
def base_time() -> datetime:
    return datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc)


def test_aggregate_projects_sums_tokens(base_time: datetime) -> None:
    records = [
        make_record(
            project="/home/user/a",
            project_slug="-home-user-a",
            session_id="s1",
            timestamp=base_time,
            input_tokens=100,
            output_tokens=200,
            cache_read_tokens=10,
            cache_write_5m_tokens=20,
        ),
        make_record(
            project="/home/user/a",
            project_slug="-home-user-a",
            session_id="s1",
            timestamp=base_time + timedelta(minutes=5),
            input_tokens=50,
            output_tokens=100,
        ),
        make_record(
            project="/home/user/b",
            project_slug="-home-user-b",
            session_id="s2",
            timestamp=base_time,
            input_tokens=300,
            output_tokens=400,
        ),
    ]
    stats = aggregate_projects(records)
    assert set(stats.keys()) == {"/home/user/a", "/home/user/b"}
    a = stats["/home/user/a"]
    assert a.input_tokens == 150
    assert a.output_tokens == 300
    assert a.cache_read_tokens == 10
    assert a.cache_write_5m_tokens == 20
    assert a.record_count == 2
    assert a.sessions == {"s1"}


def test_top_projects_orders_by_cost(base_time: datetime) -> None:
    records = [
        # Low-cost project
        make_record(project="/p/a", project_slug="-p-a", model="claude-haiku-4-5"),
        # High-cost project: opus with big output
        make_record(
            project="/p/b",
            project_slug="-p-b",
            model="claude-opus-4-7",
            input_tokens=1000,
            output_tokens=10_000,
        ),
    ]
    stats = aggregate_projects(records)
    ranked = top_projects(stats, n=2)
    assert ranked[0].project == "/p/b"
    assert ranked[1].project == "/p/a"


def test_hot_5h_windows_picks_dense_burst(base_time: datetime) -> None:
    # 10 expensive Opus calls within 30 min, then a quiet record 24h later.
    records = [
        make_record(
            project="/p/a",
            project_slug="-p-a",
            model="claude-opus-4-7",
            timestamp=base_time + timedelta(minutes=3 * i),
            input_tokens=500,
            output_tokens=2000,
        )
        for i in range(10)
    ]
    records.append(
        make_record(
            project="/p/a",
            project_slug="-p-a",
            model="claude-haiku-4-5",
            timestamp=base_time + timedelta(hours=24),
            input_tokens=10,
            output_tokens=10,
        )
    )
    windows = hot_5h_windows(records, n=2)
    assert len(windows) >= 1
    top = windows[0]
    assert top["record_count"] == 10
    assert top["cost_usd"] > 0.4


def test_hot_5h_windows_empty() -> None:
    assert hot_5h_windows([], n=3) == []


def test_model_breakdown_orders_by_cost(base_time: datetime) -> None:
    records = [
        make_record(model="claude-haiku-4-5", input_tokens=100, output_tokens=100),
        make_record(model="claude-opus-4-7", input_tokens=100, output_tokens=10_000),
        make_record(model="claude-sonnet-4-6", input_tokens=100, output_tokens=1_000),
    ]
    rows = model_breakdown(records)
    assert rows[0]["model"] == "claude-opus-4-7"
    assert rows[0]["family"] == "opus"
    assert sum(r["call_share"] for r in rows) == pytest.approx(1.0, abs=1e-3)


def test_findings_detect_opus_short_turns(base_time: datetime) -> None:
    records = [
        make_record(
            project="/p/a",
            project_slug="-p-a",
            session_id=f"s{i}",
            model="claude-opus-4-7",
            timestamp=base_time + timedelta(minutes=i),
            input_tokens=100,
            cache_write_5m_tokens=5_000,
            cache_read_tokens=4_000,
            output_tokens=200,  # short
        )
        for i in range(40)
    ]
    stats = aggregate_projects(records)
    findings = derive_findings(records, stats, model_breakdown(records))
    ids = {f["id"] for f in findings}
    assert "opus_short_turns" in ids
    opus_finding = next(f for f in findings if f["id"] == "opus_short_turns")
    assert opus_finding["severity"] in {"high", "medium"}


def test_findings_detect_low_cache_hit(base_time: datetime) -> None:
    records = [
        make_record(
            project="/p/a",
            project_slug="-p-a",
            session_id="s1",
            model="claude-sonnet-4-6",
            timestamp=base_time + timedelta(minutes=i),
            input_tokens=200,
            cache_write_5m_tokens=10_000,
            cache_read_tokens=500,
            output_tokens=500,
        )
        for i in range(15)
    ]
    stats = aggregate_projects(records)
    findings = derive_findings(records, stats, model_breakdown(records))
    ids = {f["id"] for f in findings}
    assert "low_cache_hit" in ids


def test_findings_detect_single_session_burn(base_time: datetime) -> None:
    big_session = [
        make_record(
            project="/p/a",
            project_slug="-p-a",
            session_id="big",
            model="claude-opus-4-7",
            timestamp=base_time + timedelta(minutes=i),
            input_tokens=500,
            output_tokens=3_000,
        )
        for i in range(20)
    ]
    other = [
        make_record(
            project="/p/b",
            project_slug="-p-b",
            session_id=f"small-{i}",
            model="claude-haiku-4-5",
            timestamp=base_time + timedelta(hours=i + 1),
            input_tokens=10,
            output_tokens=10,
        )
        for i in range(3)
    ]
    records = big_session + other
    stats = aggregate_projects(records)
    findings = derive_findings(records, stats, model_breakdown(records))
    ids = {f["id"] for f in findings}
    assert "single_session_burn" in ids


def test_build_report_empty() -> None:
    report = build_report([])
    assert report["totals"]["record_count"] == 0
    assert report["totals"]["total_cost_usd"] == 0.0
    assert report["top_projects"] == []
    assert report["hot_5h_windows"] == []
    assert report["model_breakdown"] == []
    assert report["findings"] == []


def test_build_report_shape(base_time: datetime) -> None:
    records = [
        make_record(
            project="/p/a",
            project_slug="-p-a",
            session_id="s1",
            model="claude-opus-4-7",
            timestamp=base_time + timedelta(minutes=i),
            input_tokens=200,
            output_tokens=500,
        )
        for i in range(5)
    ]
    report = build_report(records, top_n=3, window_n=2)
    assert report["schema"] == "token-triage/1"
    assert report["totals"]["record_count"] == 5
    assert len(report["top_projects"]) == 1
    assert report["top_projects"][0]["project"] == "/p/a"
    assert len(report["hot_5h_windows"]) == 1
    assert report["model_breakdown"][0]["model"] == "claude-opus-4-7"


# ---- per-bucket cost totals (Change 2) ----


def test_build_report_totals_have_bucket_cost_keys(base_time: datetime) -> None:
    """build_report totals must include the four per-bucket *_cost_usd keys."""
    records = [make_record(model="claude-sonnet-4-6", input_tokens=100, output_tokens=200)]
    report = build_report(records)
    totals = report["totals"]
    for key in ("input_cost_usd", "cache_write_cost_usd", "cache_read_cost_usd", "output_cost_usd"):
        assert key in totals, f"totals missing key: {key}"


def test_build_report_bucket_costs_sum_to_total(base_time: datetime) -> None:
    """The four per-bucket costs sum to total_cost_usd within rounding.

    Buckets and total are each independently rounded to 4 dp, so sum-of-rounded can
    differ from the rounded total by ~2e-4. A real additivity bug (the cost_of vs
    cost_breakdown_of paths disagreeing) would diverge by far more than that.
    """
    records = [
        make_record(
            model="claude-opus-4-7",
            input_tokens=500,
            cache_write_5m_tokens=10_000,
            cache_read_tokens=8_000,
            output_tokens=1_000,
        ),
        make_record(
            model="claude-sonnet-4-6",
            input_tokens=200,
            cache_write_5m_tokens=0,
            cache_read_tokens=0,
            output_tokens=300,
        ),
    ]
    report = build_report(records)
    totals = report["totals"]
    bucket_sum = (
        totals["input_cost_usd"]
        + totals["cache_write_cost_usd"]
        + totals["cache_read_cost_usd"]
        + totals["output_cost_usd"]
    )
    assert bucket_sum == pytest.approx(totals["total_cost_usd"], abs=1e-3)


def test_build_report_bucket_costs_are_nonzero_when_tokens_exist(base_time: datetime) -> None:
    """Each bucket with tokens must contribute non-zero cost (for a priced model)."""
    records = [
        make_record(
            model="claude-sonnet-4-6",
            input_tokens=1_000,
            cache_write_5m_tokens=5_000,
            cache_read_tokens=3_000,
            output_tokens=500,
        )
    ]
    report = build_report(records)
    totals = report["totals"]
    assert totals["input_cost_usd"] > 0.0
    assert totals["cache_write_cost_usd"] > 0.0
    assert totals["cache_read_cost_usd"] > 0.0
    assert totals["output_cost_usd"] > 0.0


def test_build_report_empty_has_zero_bucket_costs() -> None:
    """Empty record list must produce zero for all per-bucket cost keys."""
    report = build_report([])
    totals = report["totals"]
    assert totals["input_cost_usd"] == 0.0
    assert totals["cache_write_cost_usd"] == 0.0
    assert totals["cache_read_cost_usd"] == 0.0
    assert totals["output_cost_usd"] == 0.0


# ---- zero_metered_models helper (Change 3) ----


def test_zero_metered_models_flags_unknown_model() -> None:
    """A model with calls but $0 cost must appear in zero_metered_models."""
    records = [make_record(model="weird-unknown-model", input_tokens=500, output_tokens=500)]
    report = build_report(records)
    flagged = zero_metered_models(report["model_breakdown"])
    assert len(flagged) == 1
    assert flagged[0]["model"] == "weird-unknown-model"


def test_zero_metered_models_does_not_flag_priced_models() -> None:
    """A priced model must NOT appear in zero_metered_models."""
    records = [make_record(model="claude-sonnet-4-6", input_tokens=500, output_tokens=500)]
    report = build_report(records)
    flagged = zero_metered_models(report["model_breakdown"])
    assert flagged == []


def test_zero_metered_models_does_not_flag_frontier_models() -> None:
    """Fable 5 and Opus 4.8 must NOT appear in zero_metered_models (regression for #11 fix)."""
    records = [
        make_record(model="claude-fable-5", input_tokens=1_000, output_tokens=500),
        make_record(model="claude-opus-4-8", input_tokens=1_000, output_tokens=500),
    ]
    report = build_report(records)
    flagged = zero_metered_models(report["model_breakdown"])
    assert flagged == []
