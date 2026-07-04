"""Per-million-token pricing for Claude API models, plus cost computation.

Rates are USD per million tokens. Sourced from Anthropic's public pricing page;
update or override via ``--rates rates.json`` for Bedrock / Vertex / negotiated tiers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelRates:
    input: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float
    output: float


# Canonical model -> rates. Family fallback handles versions not listed here.
MODEL_RATES: dict[str, ModelRates] = {
    # Frontier tier -- Fable 5 / Mythos 5 ($10 / $50). These have no
    # opus/sonnet/haiku token in their name, so they do NOT hit FAMILY_FALLBACK;
    # if they aren't listed explicitly they silently price at $0.
    "claude-fable-5": ModelRates(10.0, 12.5, 20.0, 1.00, 50.0),
    "claude-mythos-5": ModelRates(10.0, 12.5, 20.0, 1.00, 50.0),
    # Opus 4.5+ tier ($5 / $25)
    "claude-opus-4-8": ModelRates(5.0, 6.25, 10.0, 0.50, 25.0),
    "claude-opus-4-7": ModelRates(5.0, 6.25, 10.0, 0.50, 25.0),
    "claude-opus-4-6": ModelRates(5.0, 6.25, 10.0, 0.50, 25.0),
    "claude-opus-4-5": ModelRates(5.0, 6.25, 10.0, 0.50, 25.0),
    # Older Opus 4 tier ($15 / $75)
    "claude-opus-4-1": ModelRates(15.0, 18.75, 30.0, 1.50, 75.0),
    "claude-opus-4": ModelRates(15.0, 18.75, 30.0, 1.50, 75.0),
    # Sonnet 4 family
    "claude-sonnet-4-6": ModelRates(3.0, 3.75, 6.0, 0.30, 15.0),
    "claude-sonnet-4-5": ModelRates(3.0, 3.75, 6.0, 0.30, 15.0),
    "claude-sonnet-4": ModelRates(3.0, 3.75, 6.0, 0.30, 15.0),
    # Haiku
    "claude-haiku-4-5": ModelRates(1.0, 1.25, 2.0, 0.10, 5.0),
    "claude-haiku-3-5": ModelRates(0.80, 1.0, 1.6, 0.08, 4.0),
    "claude-haiku-3": ModelRates(0.25, 0.30, 0.50, 0.03, 1.25),
}

# Family fallback when an unseen variant shows up (e.g. dated suffixes).
FAMILY_FALLBACK: dict[str, ModelRates] = {
    "opus": MODEL_RATES["claude-opus-4-7"],
    "sonnet": MODEL_RATES["claude-sonnet-4-6"],
    "haiku": MODEL_RATES["claude-haiku-4-5"],
}

# Tiering for the "Opus-when-Sonnet-fits" heuristic.
MODEL_FAMILY_RANK: dict[str, int] = {"haiku": 1, "sonnet": 2, "opus": 3}


def family_of(model: str) -> str | None:
    """Return ``opus`` / ``sonnet`` / ``haiku`` for a model id, else ``None``."""
    m = model.lower()
    for fam in ("opus", "sonnet", "haiku"):
        if fam in m:
            return fam
    return None


def normalize_model_id(model: str) -> str:
    """Strip dated suffixes like ``-20260101`` or ``[1m]`` so lookups generalize."""
    m = model.lower().strip()
    m = re.sub(r"\[[^\]]+\]$", "", m)  # drop trailing [1m] etc.
    m = re.sub(r"-\d{8}$", "", m)  # drop trailing -YYYYMMDD
    return m


def lookup_rates(model: str, table: dict[str, ModelRates] | None = None) -> ModelRates | None:
    """Look up rates for a model id, falling back to family rates."""
    table = table if table is not None else MODEL_RATES
    norm = normalize_model_id(model)
    if norm in table:
        return table[norm]
    fam = family_of(norm)
    if fam:
        return FAMILY_FALLBACK.get(fam)
    return None


def load_rates_override(path: Path) -> dict[str, ModelRates]:
    """Load a JSON file mapping model id -> {input, cache_write_5m, cache_write_1h, cache_read, output}.

    Merges over the default ``MODEL_RATES`` table (override wins on conflict).
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"rates file {path} must be a JSON object")
    merged = dict(MODEL_RATES)
    for model, rate in raw.items():
        if not isinstance(rate, dict):
            raise ValueError(f"rates entry for {model!r} must be an object")
        try:
            merged[normalize_model_id(model)] = ModelRates(
                input=float(rate["input"]),
                cache_write_5m=float(rate["cache_write_5m"]),
                cache_write_1h=float(rate["cache_write_1h"]),
                cache_read=float(rate["cache_read"]),
                output=float(rate["output"]),
            )
        except KeyError as exc:
            raise ValueError(f"rates entry for {model!r} missing key {exc}") from exc
    return merged


@dataclass(frozen=True)
class CostBreakdown:
    """Per-bucket USD costs for one assistant turn."""

    input_cost_usd: float
    cache_write_cost_usd: float  # 5m + 1h combined
    cache_read_cost_usd: float
    output_cost_usd: float

    @property
    def total(self) -> float:
        return (
            self.input_cost_usd
            + self.cache_write_cost_usd
            + self.cache_read_cost_usd
            + self.output_cost_usd
        )


def cost_breakdown_of(
    *,
    model: str,
    input_tokens: int,
    cache_write_5m_tokens: int,
    cache_write_1h_tokens: int,
    cache_read_tokens: int,
    output_tokens: int,
    rates_table: dict[str, ModelRates] | None = None,
) -> CostBreakdown:
    """Compute per-bucket USD costs for one assistant turn."""
    rates = lookup_rates(model, rates_table)
    if rates is None:
        return CostBreakdown(0.0, 0.0, 0.0, 0.0)
    per_million = 1_000_000
    return CostBreakdown(
        input_cost_usd=input_tokens * rates.input / per_million,
        cache_write_cost_usd=(
            cache_write_5m_tokens * rates.cache_write_5m
            + cache_write_1h_tokens * rates.cache_write_1h
        )
        / per_million,
        cache_read_cost_usd=cache_read_tokens * rates.cache_read / per_million,
        output_cost_usd=output_tokens * rates.output / per_million,
    )


def cost_of(
    *,
    model: str,
    input_tokens: int,
    cache_write_5m_tokens: int,
    cache_write_1h_tokens: int,
    cache_read_tokens: int,
    output_tokens: int,
    rates_table: dict[str, ModelRates] | None = None,
) -> float:
    """Compute total USD cost for one assistant turn given per-bucket token counts."""
    return cost_breakdown_of(
        model=model,
        input_tokens=input_tokens,
        cache_write_5m_tokens=cache_write_5m_tokens,
        cache_write_1h_tokens=cache_write_1h_tokens,
        cache_read_tokens=cache_read_tokens,
        output_tokens=output_tokens,
        rates_table=rates_table,
    ).total
