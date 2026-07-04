# Token Triage — Field Study: One Month of Real Agentic Spend

**TL;DR:** Across 30 days and 34,533 assistant turns of real Claude Code usage, the
metered API-equivalent cost was **$11,737**. The surprise isn't the total — it's the
shape: **92.5% of every token processed was a cache *read*** (context re-read turn
after turn). The prompts I actually type are 0.17% of the workload. This study is
`token-triage` run against its own author's fleet — including the part where the tool
was lying to me.

## The corpus

| | |
|---|---|
| Window | 2026-05-25 → 2026-06-24 (30 days) |
| Source | Local Claude Code logs (`~/.claude/projects/*.jsonl`), 2 machines (desktop + handheld) |
| Assistant turns | 34,533 |
| Snapshot | 2026-06-24 (figures frozen; logs append live) |
| Billing | Primarily Claude Max — **dollars below are API-equivalent** (what this workload would meter to at published API rates), not an out-of-pocket bill |

## Where the money goes

**$11,737 / 30 days.** By token bucket — the exact, and most surprising, cut:

| Bucket | Tokens | Share of all tokens |
|---|---|---|
| Cache read (context re-read) | 6.77 B | **92.5%** |
| Cache write | 377.6 M | 5.2% |
| Output (generation) | 156.2 M | 2.1% |
| Input (prompts I write) | 12.6 M | **0.17%** |

The counter-intuitive part: **the prompt you type is a rounding error.** The cost of
agentic work is (1) the model generating output and (2) re-reading the accumulated
context on every single turn. Cache reads are cheap *per token* (0.1× input) — but at
6.8 billion of them, "cheap and enormous" beats "expensive and small."

And caching is working: per-project cache **reuse runs 6×–29×** (reads per write).
This isn't a cache-miss problem you fix with better breakpoints — it's a volume
problem. Long agentic sessions re-read a large, growing context thousands of times.
Average re-read ≈ **196K tokens per turn**. The hottest single 5-hour window cost
**$1,038** — one overnight agentic run.

## Top projects (category labels)

| Project | API-equiv cost | Turns | Sessions | Cache reuse |
|---|---|---|---|---|
| App monorepo | $2,693 | 8,675 | 41 | 24.5× |
| Knowledge base (vault) | $2,531 | 4,188 | 23 | 6.3× |
| Workspace root (mixed) | $2,371 | 7,691 | 48 | 20.6× |
| Eval harness | $1,649 | 5,880 | 35 | 23.6× |
| Knowledge base (notes) | $1,363 | 3,850 | 23 | 17.1× |
| Core engine | $1,111 | 4,145 | 18 | 29.2× |

The vault stands out: **lowest reuse (6.3×) on the second-highest spend** — the
signature of sessions that rebuild context often (frequent edits, large standing
instructions) instead of reusing a stable prefix.

## By model

| Model | API-equiv cost | Cost share | Calls |
|---|---|---|---|
| Opus 4.8 | $10,197 | 86.9% | 29,852 |
| Fable 5 | $1,213 | 10.3% | 2,995 |
| Opus 4.7 | $327 | 2.8% | 1,658 |

91% of calls run on a single tier (Opus). Which leads to the honest part.

## The part where the tool was lying to me

Running this study, I found `token-triage` was pricing **Fable 5 — my most expensive
model ($10/$50, 2× Opus) — at $0.** Fable's id carries no "opus/sonnet/haiku" token,
so it slipped past the family-fallback and metered to zero: 8.7% of my calls,
**$1,213/month, invisible.** With Fable zeroed the headline would have read **$10,524**, not the real **$11,737**.

I caught it only because the total didn't smell right against ground truth. Fixed it
(Fable 5 + Mythos 5 + an explicit Opus 4.8 entry; 94 tests green), and it's in the
tool now.

That's the product thesis in one bug: **a cost tool you don't sanity-check against
reality will confidently hand you a wrong number.** Pin your rates (`--rates`), and
distrust any bucket that reads $0.

## What's recoverable (projected)

Honest framing — these are levers the audit surfaces, not measured before/after:

- **$225/mo, mechanical, today.** 1,475 Opus calls produced ≤256 output tokens —
  short, decision-style turns that a cheaper tier handles at a fraction of the rate.
  The tool flags this automatically.
- **The big one is the context tax.** 92.5% of tokens are cache reads. Session
  hygiene — `/compact`, shorter focused sessions, leaner standing instructions —
  reduces re-read volume directly. (Not quantified here; it needs an A/B I haven't run.)
- **Visibility precedes savings.** The Fable fix "recovered" $1,213/mo of *accuracy*,
  not money — but you can't trim what you can't see.

## Methodology

- **Pricing:** Anthropic published API rates (Opus 4.5–4.8 $5/$25; Fable 5 $10/$50;
  cache write 1.25×/2× input, cache read 0.1×). Every turn is priced by the model id
  logged in *that* turn — no single-model assumption, so model changes mid-window are
  handled exactly.
- **Billing context:** primarily Claude Max, so figures are **API-equivalent** compute
  weight, not a bill. Pay-per-token overflow (a separate provider, used between Max
  resets) runs on infra not in this corpus and is excluded.
- **Scope / limits:** local interactive sessions only; scheduled cloud agents and
  remote/offload runs are not in local logs; local history reaches back ~30 days;
  `<synthetic>` system turns price at $0 (no real model).
- **Reproduce it on your own logs:** `pipx install git+https://github.com/cursed180/Cursed_Token_Triage.git && token-triage`.
  Nothing leaves your machine; add `--anon` before sharing a screenshot.

---

*One operator's 30 days. Run the audit on your own fleet — yours will surprise you in
a different place.*
