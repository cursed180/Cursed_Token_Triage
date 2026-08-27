"""CI-only drift check: shipped MODEL_RATES vs Anthropic's published pricing.

Fetches the models-overview doc, parses the pricing and model-ID rows, and
compares them against the built-in table. Runs in CI on a weekly schedule; it
is NOT part of the shipped package and never runs on a user's machine (the
package itself keeps its no-network guarantee, enforced by privacy_scrub.py).

Exit codes:
    0  table matches published pricing
    1  drift found (missing model row, or a rate mismatch)
    2  fetch or parse failure (also loud: a check that cannot run is not green)
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from token_triage.pricing import MODEL_RATES, RATES_AS_OF, normalize_model_id

DOC_URL = "https://platform.claude.com/docs/en/models/overview.md"
PRICE_RE = re.compile(r"\$([0-9.]+)\s*/\s*input MTok,\s*\$([0-9.]+)\s*/\s*output MTok")
# Documented rule: cache reads cost 10% of base input. Known exception shape:
# some legacy rates round off that rule (haiku-3 ships cache_read $0.03, the
# derived value is $0.025). Only models in the doc's comparison table are
# checked here, so a cache-read flag on a future model may be rounding, not
# drift - adjudicate against the pricing page before updating the table.
CACHE_READ_MULTIPLIER = 0.10
TOLERANCE = 1e-6


def fetch_doc(url: str = DOC_URL) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "token-triage-rates-drift/1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def _row_cells(doc: str, row_key_pattern: str) -> list[str] | None:
    """Return the cells of the first markdown table row whose first cell matches."""
    for line in doc.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells and re.match(row_key_pattern, cells[0]):
            return cells[1:]
    return None


def published_rates(doc: str) -> dict[str, tuple[float, float]]:
    """Map normalized model id -> (input, output) USD/MTok from the doc table."""
    id_cells = _row_cells(doc, r"Claude API ID\b")
    price_cells = _row_cells(doc, r"\[?Pricing\]?")
    if not id_cells or not price_cells or len(id_cells) != len(price_cells):
        raise ValueError(f"could not parse doc table (ids={id_cells!r}, prices={price_cells!r})")
    out: dict[str, tuple[float, float]] = {}
    for raw_id, raw_price in zip(id_cells, price_cells, strict=True):
        model = normalize_model_id(raw_id.strip("`"))
        m = PRICE_RE.search(raw_price)
        if not model or not m:
            raise ValueError(f"unparseable cell pair: id={raw_id!r} price={raw_price!r}")
        out[model] = (float(m.group(1)), float(m.group(2)))
    return out


def find_drift(published: dict[str, tuple[float, float]]) -> list[str]:
    problems: list[str] = []
    for model, (pub_input, pub_output) in sorted(published.items()):
        rates = MODEL_RATES.get(model)
        if rates is None:
            problems.append(
                f"missing row: `{model}` is published at ${pub_input} / ${pub_output} "
                "but has no explicit MODEL_RATES entry (family fallback is not enough; "
                "see the Sonnet 5 incident on issue #1)"
            )
            continue
        if abs(rates.input - pub_input) > TOLERANCE:
            problems.append(
                f"input drift: `{model}` shipped ${rates.input}, published ${pub_input}"
            )
        if abs(rates.output - pub_output) > TOLERANCE:
            problems.append(
                f"output drift: `{model}` shipped ${rates.output}, published ${pub_output}"
            )
        expected_cache_read = pub_input * CACHE_READ_MULTIPLIER
        if abs(rates.cache_read - expected_cache_read) > TOLERANCE:
            problems.append(
                f"cache-read drift: `{model}` shipped ${rates.cache_read}, "
                f"expected ${expected_cache_read} (10% of published input)"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Also write the findings as a markdown issue body to this path.",
    )
    args = parser.parse_args(argv)

    try:
        doc = fetch_doc()
        published = published_rates(doc)
    except Exception as exc:  # any failure must be loud, not green
        message = f"rates drift check FAILED to run: {exc}"
        print(message, file=sys.stderr)
        if args.out:
            args.out.write_text(
                "The weekly rates drift check could not fetch or parse the published "
                f"pricing doc.\n\n```\n{exc}\n```\n\nSource: {DOC_URL}\n",
                encoding="utf-8",
            )
        return 2

    problems = find_drift(published)
    if not problems:
        print(
            f"OK: {len(published)} published models match MODEL_RATES (shipped as_of {RATES_AS_OF})"
        )
        return 0

    print(f"DRIFT: {len(problems)} problem(s) vs {DOC_URL}", file=sys.stderr)
    for p in problems:
        print(f"  - {p}", file=sys.stderr)
    if args.out:
        body = (
            f"The shipped rates table (as_of {RATES_AS_OF}) no longer matches the "
            f"published pricing at {DOC_URL}:\n\n"
            + "\n".join(f"- {p}" for p in problems)
            + "\n\nUpdate MODEL_RATES and RATES_AS_OF in `token_triage/pricing.py`.\n"
        )
        args.out.write_text(body, encoding="utf-8")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
