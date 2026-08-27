"""Render a report dict (from ``analyze.build_report``) as JSON or Markdown."""

from __future__ import annotations

import json
from typing import Any


def render_json(report: dict[str, Any], *, indent: int = 2) -> str:
    return json.dumps(report, indent=indent, sort_keys=False)


def _fmt_usd(n: float) -> str:
    return f"${n:,.2f}"


def _fmt_int(n: int) -> str:
    return f"{n:,}"


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    totals = report.get("totals", {})
    lines.append("# Token Triage Report")
    lines.append("")
    if totals.get("first_event") and totals.get("last_event"):
        lines.append(f"_Window: {totals['first_event']} → {totals['last_event']}_")
        lines.append("")
    if report.get("rates_as_of"):
        lines.append(f"_Built-in rates as of: {report['rates_as_of']} (override with --rates)_")
        lines.append("")

    lines.append("## Totals")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Total cost (USD) | {_fmt_usd(totals.get('total_cost_usd', 0.0))} |")
    lines.append(f"| Records | {_fmt_int(totals.get('record_count', 0))} |")
    lines.append(f"| Input tokens | {_fmt_int(totals.get('input_tokens', 0))} |")
    lines.append(f"| Cache write tokens | {_fmt_int(totals.get('cache_write_tokens', 0))} |")
    lines.append(f"| Cache read tokens | {_fmt_int(totals.get('cache_read_tokens', 0))} |")
    lines.append(f"| Output tokens | {_fmt_int(totals.get('output_tokens', 0))} |")
    family_share = totals.get("family_cost_share") or {}
    if family_share:
        share_str = ", ".join(f"{fam}: {_fmt_pct(share)}" for fam, share in family_share.items())
        lines.append(f"| Family cost share | {share_str} |")
    lines.append("")

    lines.append("## Top projects by cost")
    lines.append("")
    if report.get("top_projects"):
        lines.append("| # | Project | Cost (USD) | Records | Sessions | Cache reuse (read/write) |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for idx, row in enumerate(report["top_projects"], start=1):
            lines.append(
                "| {idx} | `{project}` | {cost} | {recs} | {sessions} | {ratio:.2f} |".format(
                    idx=idx,
                    project=row["project"],
                    cost=_fmt_usd(row["cost_usd"]),
                    recs=_fmt_int(row["record_count"]),
                    sessions=_fmt_int(row["session_count"]),
                    ratio=row["cache_reuse"],
                )
            )
    else:
        lines.append("_No usage records found._")
    lines.append("")

    lines.append("## Hottest 5-hour windows")
    lines.append("")
    if report.get("hot_5h_windows"):
        lines.append("| # | Start | End | Duration (min) | Cost (USD) | Records | Models |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for idx, w in enumerate(report["hot_5h_windows"], start=1):
            lines.append(
                "| {idx} | {start} | {end} | {dur} | {cost} | {recs} | {models} |".format(
                    idx=idx,
                    start=w["start"],
                    end=w["end"],
                    dur=w["duration_minutes"],
                    cost=_fmt_usd(w["cost_usd"]),
                    recs=_fmt_int(w["record_count"]),
                    models=", ".join(w["models"]),
                )
            )
    else:
        lines.append("_No 5-hour windows with measurable cost._")
    lines.append("")

    lines.append("## Model breakdown")
    lines.append("")
    if report.get("model_breakdown"):
        lines.append("| Model | Family | Cost (USD) | Cost share | Calls | Call share |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for row in report["model_breakdown"]:
            lines.append(
                "| `{model}`{flag} | {family} | {cost} | {cs} | {calls} | {ks} |".format(
                    model=row["model"],
                    flag=" **(unpriced)**" if row.get("unpriced") else "",
                    family=row.get("family") or "—",
                    cost=_fmt_usd(row["cost_usd"]),
                    cs=_fmt_pct(row["cost_share"]),
                    calls=_fmt_int(row["call_count"]),
                    ks=_fmt_pct(row["call_share"]),
                )
            )
    else:
        lines.append("_No model breakdown available._")
    lines.append("")

    if report.get("unpriced_models"):
        lines.append("## Unpriced models")
        lines.append("")
        lines.append(
            "These models have calls but no entry in the rates table, so they are "
            "counted at $0.00 and the totals above understate real spend. "
            "Pass --rates to price them."
        )
        lines.append("")
        for row in report["unpriced_models"]:
            lines.append(f"- `{row['model']}`: {_fmt_int(row['call_count'])} call(s)")
        lines.append("")

    lines.append("## Findings")
    lines.append("")
    if report.get("findings"):
        for f in report["findings"]:
            lines.append(f"### [{f['severity'].upper()}] {f['title']}")
            lines.append("")
            evidence = f.get("evidence") or {}
            if evidence:
                lines.append("**Evidence:**")
                lines.append("")
                for k, v in evidence.items():
                    if isinstance(v, float):
                        rendered = f"{v:.4f}" if v < 1 else f"{v:.2f}"
                    else:
                        rendered = str(v)
                    lines.append(f"- `{k}`: {rendered}")
                lines.append("")
            lines.append(f"**Recommendation:** {f['recommendation']}")
            lines.append("")
    else:
        lines.append("_No waste patterns detected at this time. Nice routing._")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"
