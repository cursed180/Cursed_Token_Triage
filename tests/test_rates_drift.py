"""Tests for scripts/check_rates_drift.py (the CI-only drift check).

The script lives outside the package (network imports are banned inside
token_triage/), so it is loaded by file path here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_rates_drift.py"
_spec = importlib.util.spec_from_file_location("check_rates_drift", _SCRIPT)
assert _spec is not None and _spec.loader is not None
drift = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drift)

# Mirrors the shape of the published models-overview table: a row keyed
# "[Pricing](...)" and a row keyed "Claude API ID" with backticked ids.
FIXTURE_DOC = """
# Models overview

| Feature | Claude Fable 5 | Claude Sonnet 5 |
| :--- | :--- | :--- |
| [Pricing](https://example.com/pricing) | $10 / input MTok, $50 / output MTok | $2 / input MTok, $10 / output MTok |
| Claude API ID | `claude-fable-5` | `claude-sonnet-5` |
"""


def test_published_rates_parses_fixture_table() -> None:
    pub = drift.published_rates(FIXTURE_DOC)
    assert pub == {
        "claude-fable-5": (10.0, 50.0),
        "claude-sonnet-5": (2.0, 10.0),
    }


def test_find_drift_clean_on_matching_rates() -> None:
    pub = drift.published_rates(FIXTURE_DOC)
    assert drift.find_drift(pub) == []


def test_find_drift_flags_missing_row() -> None:
    problems = drift.find_drift({"claude-newmodel-9": (7.0, 35.0)})
    assert len(problems) == 1
    assert "missing row" in problems[0]


def test_find_drift_flags_rate_mismatch() -> None:
    # Published claims Sonnet 4.6-style rates for Sonnet 5; shipped says $2/$10.
    problems = drift.find_drift({"claude-sonnet-5": (3.0, 15.0)})
    assert any("input drift" in p for p in problems)
    assert any("output drift" in p for p in problems)


def test_published_rates_raises_on_redirect_stub() -> None:
    """A moved doc URL returns a path stub with no table; parse must fail loud."""
    with pytest.raises(ValueError):
        drift.published_rates("/docs/en/models/overview.md")
