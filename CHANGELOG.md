# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Explicit rate rows for `claude-opus-5` ($5 / $25) and `claude-sonnet-5`
  ($2 / $10). Sonnet 5 previously priced through the sonnet family fallback at
  Sonnet 4.6 rates ($3 / $15), a 50% overestimate (#1).
- `RATES_AS_OF` date on the built-in table, surfaced as `rates_as_of` in the
  JSON report and as a "Built-in rates as of" line in the markdown header (#1).
- Unpriced-model surfacing in the report itself: an `unpriced` flag per
  `model_breakdown` row, a top-level `unpriced_models` list in the JSON schema,
  and an "Unpriced models" markdown section. Additive - existing fields are
  preserved (#1).
- `--strict` CLI flag: exit code `3` when any model has calls but no rates
  entry, for CI gates that must not trust totals that understate spend (#1).
- Weekly `rates-drift` GitHub Actions job comparing the models in Anthropic's
  published comparison table against `MODEL_RATES`; files or updates a tracking
  issue on drift and on fetch/parse failure. CI-only - the shipped package
  still makes no network calls (#1).

- Per-bucket USD cost keys (`input_cost_usd`, `cache_write_cost_usd`,
  `cache_read_cost_usd`, `output_cost_usd`) in the `totals` section of the
  `token-triage/1` JSON schema.  Additive — all existing fields are preserved.
- `$0-meter guardrail`: when any model with recorded calls has no pricing table
  entry, `token-triage` now emits a warning to stderr.  Excludes models whose
  rates were explicitly set to zero via `--rates`.
- Pricing regression tests for Fable 5, Mythos 5, and Opus 4.8 — locking in
  the #11 fix that added explicit rate entries for models with no
  `opus`/`sonnet`/`haiku` family token in their id.

- `scripts/privacy_scrub.py` loads personal/namespace patterns from external
  user config (`~/.config/token-triage/scrub-patterns.{json,yaml}`) instead of
  hardcoding them in public source. If the config is absent the script still
  enforces DSN and network-import checks, but warns that personal patterns are
  disabled. Override the path with `TOKEN_TRIAGE_SCRUB_CONFIG`.
- Local pre-commit hooks for content scanning + commit-message check + author-email allowlist.
- Apache-2.0 `LICENSE` + `NOTICE`, and `CONTRIBUTING.md` with DCO sign-off terms.

### Changed

- README H1 alignment: `# token-triage` → `# Token Triage` (Title Case, matches sibling FOSS repo `# Personal Stats`). The Python package name (`token-triage`) is unchanged; references in install commands and code stay lowercase per pip convention.
- `--output` now refuses to overwrite an existing file unless `--force` is passed.
- `<synthetic>` turns (Claude Code's API-error entries: a populated `usage` block
  but all-zero tokens) are skipped at parse time — they carry no cost or analytical
  signal, and excluding them keeps the new `$0-meter guardrail` from false-firing on
  the unpriced `<synthetic>` pseudo-model. The skip is gated on the `<synthetic>`
  model id, **not** on all-zero tokens alone, so a real model that emits a zero-token
  turn (streaming abort, rate-limit reject) is retained and counted rather than
  silently dropped. `record_count` excludes only `<synthetic>` turns.

### Fixed

- Frontier models are now priced instead of silently metering at **$0**. Fable 5
  and Mythos 5 ($10 / $50) plus an explicit Opus 4.8 entry were added to the rate
  table; any model id without an `opus` / `sonnet` / `haiku` family token bypassed
  the family fallback and priced at zero, undercounting spend on those tiers.
- Report output is now written and streamed as UTF-8, so non-ASCII glyphs (for
  example the `→` in window-range labels) no longer crash on a legacy console
  code page. Previously `--output PATH` on Windows (cp1252) raised
  `UnicodeEncodeError`, and a redirected stdout had the same failure. `--rates`
  files are also read as UTF-8 rather than the platform default encoding.
- `--windows 0` no longer returns a spurious window; the list is correctly empty. This prevents the silent clobber that occurred when running token-triage twice with the same path. Previous behavior can be restored with `--force`.
- README/STUDY.md install instructions no longer point at PyPI, where the package doesn't exist yet. Both now install straight from GitHub (`pipx install git+https://github.com/cursed180/Cursed_Token_Triage.git`).

## [0.1.0] - 2026-05-08

### Added

- Initial release of `token-triage`.
- CLI entry point `token-triage` that parses Claude Code event logs from
  `~/.claude/projects/*.jsonl` and emits a ranked usage report.
- Built-in pricing for Claude Opus 4.x, Sonnet 4.x, and Haiku 4.x families,
  with a `--rates` JSON override for Bedrock / Vertex / negotiated tiers.
- Sliding 5-hour window analysis (account-scoped, ranked by USD cost).
- Top-projects ranking, model breakdown, per-project cache-hit ratio.
- Findings: opus-when-Sonnet-fits, low cache hit, single-session burn,
  single-tier routing.
- `--anon` mode that replaces project paths and session ids with stable
  opaque hashes for safe sharing.
- Privacy scrub script (`scripts/privacy_scrub.py`) running in CI and as a
  pre-commit hook; bans network-capable imports inside the package source.
- Synthetic sample fixtures and `examples/generate_sample.py` to regenerate
  the shipped `examples/sample-output.{md,json}`.
