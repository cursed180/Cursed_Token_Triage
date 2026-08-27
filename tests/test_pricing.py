from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from token_triage.pricing import (
    FAMILY_FALLBACK,
    MODEL_RATES,
    RATES_AS_OF,
    ModelRates,
    cost_of,
    family_of,
    load_rates_override,
    lookup_rates,
    normalize_model_id,
)


@pytest.mark.parametrize(
    "model, expected",
    [
        ("claude-opus-4-7", "opus"),
        ("claude-OPUS-4-7", "opus"),
        ("claude-sonnet-4-6-20260101", "sonnet"),
        ("claude-haiku-4-5", "haiku"),
        ("gpt-4", None),
    ],
)
def test_family_of(model: str, expected: str | None) -> None:
    assert family_of(model) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("claude-opus-4-7", "claude-opus-4-7"),
        ("claude-opus-4-7-20260101", "claude-opus-4-7"),
        ("claude-opus-4-7[1m]", "claude-opus-4-7"),
        ("Claude-Opus-4-7", "claude-opus-4-7"),
    ],
)
def test_normalize_model_id(raw: str, expected: str) -> None:
    assert normalize_model_id(raw) == expected


def test_lookup_rates_known_model() -> None:
    rates = lookup_rates("claude-opus-4-7")
    assert rates is not None
    assert rates.input == 5.0
    assert rates.output == 25.0


def test_lookup_rates_dated_suffix() -> None:
    rates = lookup_rates("claude-sonnet-4-6-20260315")
    assert rates is not None
    assert rates.input == 3.0


def test_lookup_rates_unknown_family_falls_back() -> None:
    # An unseen Opus variant should still get Opus rates.
    rates = lookup_rates("claude-opus-99")
    assert rates is not None
    assert rates.input == MODEL_RATES["claude-opus-4-7"].input


def test_lookup_rates_unknown_model_returns_none() -> None:
    assert lookup_rates("gpt-4") is None


def test_cost_of_opus_47() -> None:
    # 100 input + 5000 5m write + 4000 read + 200 output on Opus 4.7
    # = (100*5 + 5000*6.25 + 4000*0.5 + 200*25) / 1e6
    # = (500 + 31250 + 2000 + 5000) / 1e6 = 38750/1e6 = 0.03875
    cost = cost_of(
        model="claude-opus-4-7",
        input_tokens=100,
        cache_write_5m_tokens=5_000,
        cache_write_1h_tokens=0,
        cache_read_tokens=4_000,
        output_tokens=200,
    )
    assert cost == pytest.approx(0.03875)


def test_cost_of_unknown_model_returns_zero() -> None:
    assert (
        cost_of(
            model="weird-model",
            input_tokens=1_000_000,
            cache_write_5m_tokens=0,
            cache_write_1h_tokens=0,
            cache_read_tokens=0,
            output_tokens=1_000_000,
        )
        == 0.0
    )


def test_load_rates_override(tmp_path: Path) -> None:
    rates_path = tmp_path / "rates.json"
    rates_path.write_text(
        json.dumps(
            {
                "claude-opus-4-7": {
                    "input": 1.0,
                    "cache_write_5m": 1.25,
                    "cache_write_1h": 2.0,
                    "cache_read": 0.10,
                    "output": 5.0,
                }
            }
        )
    )
    table = load_rates_override(rates_path)
    rates = table["claude-opus-4-7"]
    assert isinstance(rates, ModelRates)
    assert rates.input == 1.0
    # Other defaults are still present.
    assert table["claude-sonnet-4-6"].input == 3.0


def test_load_rates_override_rejects_non_object(tmp_path: Path) -> None:
    rates_path = tmp_path / "rates.json"
    rates_path.write_text("[]")
    with pytest.raises(ValueError):
        load_rates_override(rates_path)


def test_load_rates_override_missing_field(tmp_path: Path) -> None:
    rates_path = tmp_path / "rates.json"
    rates_path.write_text(json.dumps({"claude-opus-4-7": {"input": 1.0}}))
    with pytest.raises(ValueError):
        load_rates_override(rates_path)


# ---- Fable 5 / Mythos 5 / Opus 4.8 pricing regression tests ----
# These models have no opus/sonnet/haiku token in their id, so they bypass the
# family fallback and must be listed explicitly in MODEL_RATES.  The bug #11
# fixed is that they silently priced at $0; these tests lock that fix in.


@pytest.mark.parametrize(
    "model",
    ["claude-fable-5", "claude-mythos-5"],
)
def test_fable_mythos_have_no_family(model: str) -> None:
    """family_of returns None for Fable/Mythos — documents why explicit rates are required."""
    assert family_of(model) is None


def test_opus_48_has_opus_family() -> None:
    """claude-opus-4-8 carries the opus family token so the family fallback would work,
    but an explicit entry is still present for precision."""
    assert family_of("claude-opus-4-8") == "opus"


@pytest.mark.parametrize(
    "model, expected_input, expected_output",
    [
        ("claude-fable-5", 10.0, 50.0),
        ("claude-mythos-5", 10.0, 50.0),
        ("claude-opus-4-8", 5.0, 25.0),
    ],
)
def test_frontier_model_lookup_returns_rates(
    model: str, expected_input: float, expected_output: float
) -> None:
    """lookup_rates must not return None for explicitly-listed frontier models."""
    rates = lookup_rates(model)
    assert rates is not None
    assert rates.input == expected_input
    assert rates.output == expected_output


@pytest.mark.parametrize(
    "model",
    ["claude-fable-5", "claude-mythos-5", "claude-opus-4-8"],
)
def test_frontier_model_cost_is_nonzero(model: str) -> None:
    """cost_of must meter non-zero for frontier models (the #11 bug class)."""
    cost = cost_of(
        model=model,
        input_tokens=1_000_000,
        cache_write_5m_tokens=0,
        cache_write_1h_tokens=0,
        cache_read_tokens=0,
        output_tokens=1_000_000,
    )
    assert cost > 0.0


# ---- Current-generation rows + as-of date (issue #1) ----


def test_rates_as_of_is_iso_date() -> None:
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", RATES_AS_OF)


@pytest.mark.parametrize(
    "model, expected_input, expected_output, expected_cache_read",
    [
        ("claude-opus-5", 5.0, 25.0, 0.50),
        ("claude-sonnet-5", 2.0, 10.0, 0.20),
    ],
)
def test_current_generation_lookup_returns_exact_rates(
    model: str, expected_input: float, expected_output: float, expected_cache_read: float
) -> None:
    rates = lookup_rates(model)
    assert rates is not None
    assert rates.input == expected_input
    assert rates.output == expected_output
    assert rates.cache_read == expected_cache_read


def test_sonnet_5_does_not_inherit_fallback_rates() -> None:
    """Without an explicit row, the sonnet family fallback would price Sonnet 5 at
    Sonnet 4.6 rates ($3 / $15), a 50% overestimate. Lock the exact row in."""
    rates = lookup_rates("claude-sonnet-5")
    assert rates is not None
    assert rates.input != FAMILY_FALLBACK["sonnet"].input
    assert rates.input == 2.0
