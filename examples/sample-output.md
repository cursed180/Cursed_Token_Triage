# Token Triage Report

_Window: 2026-04-01T09:00:00+00:00 → 2026-04-02T15:14:00+00:00_

## Totals

| Metric | Value |
| --- | --- |
| Total cost (USD) | $4.49 |
| Records | 75 |
| Input tokens | 20,740 |
| Cache write tokens | 627,100 |
| Cache read tokens | 351,900 |
| Output tokens | 40,500 |
| Family cost share | opus: 77.5%, sonnet: 22.1%, haiku: 0.3% |

## Top projects by cost

| # | Project | Cost (USD) | Records | Sessions | Cache reuse (read/write) |
| --- | --- | --- | --- | --- | --- |
| 1 | `/home/devuser/infra-scripts` | $2.21 | 14 | 1 | 0.83 |
| 2 | `/home/devuser/ai-coding-cli` | $1.27 | 35 | 1 | 0.78 |
| 3 | `/home/devuser/revenue-dashboard` | $0.99 | 18 | 1 | 0.07 |
| 4 | `/home/devuser/docs-site` | $0.01 | 8 | 1 | 2.00 |

## Hottest 5-hour windows

| # | Start | End | Duration (min) | Cost (USD) | Records | Models |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-04-02T11:00:00+00:00 | 2026-04-02T15:14:00+00:00 | 254.0 | $2.23 | 22 | claude-haiku-4-5, claude-opus-4-7 |
| 2 | 2026-04-01T09:00:00+00:00 | 2026-04-01T11:16:00+00:00 | 136.0 | $1.27 | 35 | claude-opus-4-7 |
| 3 | 2026-04-01T15:00:00+00:00 | 2026-04-01T16:25:00+00:00 | 85.0 | $0.99 | 18 | claude-sonnet-4-6 |

## Model breakdown

| Model | Family | Cost (USD) | Cost share | Calls | Call share |
| --- | --- | --- | --- | --- | --- |
| `claude-opus-4-7` | opus | $3.48 | 77.5% | 49 | 65.3% |
| `claude-sonnet-4-6` | sonnet | $0.99 | 22.1% | 18 | 24.0% |
| `claude-haiku-4-5` | haiku | $0.01 | 0.3% | 8 | 10.7% |

## Findings

### [HIGH] Opus calls with short output (likely Sonnet-fit)

**Evidence:**

- `call_count`: 35
- `estimated_cost_usd`: 1.27
- `threshold_output_tokens`: 256

**Recommendation:** Route short, decision-style turns to Sonnet 4.6 (5x cheaper input, 5x cheaper output at current rates). Reserve Opus for hard reasoning.

### [MEDIUM] Low cache-hit ratio on a high-spend project

**Evidence:**

- `project`: /home/devuser/revenue-dashboard
- `cache_read_tokens`: 16200
- `cache_write_tokens`: 216000
- `ratio`: 0.0700
- `project_cost_usd`: 0.9931

**Recommendation:** Each cache write costs 1.25x base input; reads cost 0.1x. A ratio below 1.0 means you're paying to fill caches that aren't being reused. Look for sessions that rebuild context frequently (frequent /clear, huge variable instructions).

### [MEDIUM] One session dominates spend

**Evidence:**

- `session_id`: infra-scripts/session-001
- `project`: /home/devuser/infra-scripts
- `session_cost_usd`: 2.21
- `share_of_total`: 0.4930

**Recommendation:** Sessions that grow unboundedly often re-pay cache writes as the context shifts. Break work into focused sessions; use /compact when a session crosses ~50% of its window.
