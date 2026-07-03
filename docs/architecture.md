# Architecture

## Current Architecture Understanding

QuantStrategyLab already separates strategy math, snapshot generation, runtime
execution, and broker adapters. This repository adds a research-only signal context
pipeline without changing that production boundary.

This repository is deliberately narrower than `AIAuditBridge`. It owns
research inputs, validation, saved artifacts, and replay harnesses. It does not
own model provider routing, API keys, GitHub App write orchestration, live
notifications, or execution behavior.

## Main Design Pressure

LLM output is not naturally deterministic or backtestable. The repository must
therefore preserve every generated artifact and keep AI output away from live
order routing.

## Recommended Low-Risk Shape

- `ResearchSignalContextPipelines` stores context examples, schema, validation,
  replay tooling, and shadow artifacts.
- `AIAuditBridge` owns provider routing and API keys.
- GitHub Issues are the first operator notification layer for monthly shadow
  signal runs.
- The scheduled workflow builds the market context bundle before dispatching the
  bridge and embeds that bundle into the issue, because the bridge reads the
  source repository ref plus issue content.
- `QuantStrategyPlugins` may later read promoted artifacts as sidecar context.
- Platform repositories remain unchanged.

## Lifecycle

The current lifecycle is accumulation-first:

1. Build a point-in-time context bundle.
2. Ask `AIAuditBridge` to review it and produce a shadow-only artifact when
   evidence is sufficient.
3. Save both `latest_signal.json` and dated `signal_history/YYYY-MM-DD.json`.
4. Replay only saved artifacts against later prices.
5. Consider a deterministic plugin only after enough walk-forward evidence
   exists.

## Not Recommended

- Giving AI broker credentials.
- Parsing free text into orders.
- Letting AI change strategy thresholds, max leverage, universe membership, or
  execution mode.
- Re-generating old AI judgments during replay instead of replaying stored
  artifacts.
- Sending runtime Telegram or broker-facing notifications directly from this
  research repository before a deterministic plugin contract exists.
- Duplicating `AIAuditBridge` provider fallback or cross-repository write
  logic inside this repository.

## Validation Strategy

The current minimum checks are schema validation and deterministic overlay
replay. Replay consumes stored signal artifacts from `signal_history` and maps
them through a fixed risk-reducing policy. It must never ask a model to recreate
old judgments.

The first overlay harness intentionally measures only:

- final equity
- total return
- maximum drawdown
- average exposure
- exposure turnover

This is enough to identify whether the stored AI context would have reduced
risk or created unacceptable opportunity cost before any runtime integration.

The replay harness can read either compact `date,symbol,close` CSV files or the
existing QuantStrategyLab `symbol,as_of,close` price-history files. Large source
files should stay in their owning strategy repositories or object storage; this
repository only stores small extracted replay inputs when needed for research.

## Risk Notes

The artifact is research evidence, not a trading instruction. Missing evidence,
expired artifacts, low confidence, or schema failures should default to no-op in
any downstream consumer. Current promoted signal artifacts must use the
`1-3 years` horizon and provide enough theme or symbol coverage for Advisor to
distinguish a genuine missing long-horizon signal from an ingestion gap.

## Cross-Sector Theme Taxonomy

The long-horizon context must not be limited to the current hot AI trade.  The
stable research universe now uses a static, versioned theme taxonomy stored in:

```text
config/theme_taxonomy.csv
config/symbol_theme_exposure.csv
```

The taxonomy intentionally covers multiple durable sectors:

- AI compute, HBM/memory, foundry and AI server infrastructure
- data-center power, utilities, grid transition and nuclear optionality
- cybersecurity
- defense and aerospace
- energy security and hydrocarbons
- financial and market infrastructure
- healthcare policy
- consumer platforms, industrial automation, EV/auto, and crypto infrastructure

Theme membership is static research context.  A symbol is not added to a theme
just because it is hot this month.  Monthly AI output may express `theme_bias`
and optional `symbol_bias`; both can use structured values with bias,
confidence, linked themes, rationale, and risk flags. Downstream consumers must
keep that output shadow-only and replay saved artifacts point-in-time.

This is the anti-overfit boundary:

1. Define universe and theme exposure before looking at future returns.
2. Save every AI theme judgment as an artifact.
3. Replay only saved artifacts; never regenerate old model judgments.
4. Treat theme and symbol bias as context, not as execution or allocation.

## Horizon Boundary

This repository should not directly produce short-term recommendations. Short-term (`1-10 trading days`) catalyst handling belongs to `PoliticalEventTrackingResearch` plus deterministic Advisor rules. `theme_momentum_snapshot.json` is explicitly a medium-horizon (`2-12 weeks`) theme context artifact, while `latest_signal.json` and `signal_history/*.json` remain long-horizon (`1-3 years`) AI shadow context. `QuantAdvisorResearch` is the final composition layer for short/medium/long recommendation buckets.

## Theme Momentum Snapshot

A cross-sector theme ranking is produced separately from the static taxonomy.
The snapshot uses fixed windows rather than tuning to recent winners:

- 12-1 month momentum: 252 trading-day lookback, skipping the latest 21 trading days
- 6-1 month momentum: 126 trading-day lookback, skipping the latest 21 trading days
- 3 month momentum: 63 trading-day recent trend
- breadth: share of priced theme members with positive 3 month returns
- risk penalty: 63 day realized volatility and 126 day drawdown

Output path convention:

```text
data/output/theme_momentum_snapshot.json
```

The artifact is point-in-time medium-horizon research context.  It ranks themes and highlights
strong members inside a theme, but it does not encode short-term recommendations,
orders, target weights, or execution policy.  Future replay must consume saved
snapshots rather than recomputing old theme ranks with revised constituents or revised weights.

## Repository Name Decision

`ResearchSignalContextPipelines` is the canonical name. The short/medium/long
final recommendation buckets live in `QuantAdvisorResearch`; this repository
provides reusable research context artifacts, including medium-horizon theme
momentum and long-horizon AI shadow context.
