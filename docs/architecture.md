# Architecture

## Current Architecture Understanding

QuantStrategyLab already separates strategy math, snapshot generation, runtime
execution, and broker adapters. This repository adds a research-only AI signal
pipeline without changing that production boundary.

## Main Design Pressure

LLM output is not naturally deterministic or backtestable. The repository must
therefore preserve every generated artifact and keep AI output away from live
order routing.

## Recommended Low-Risk Shape

- `AiLongHorizonSignalPipelines` stores context examples, schema, validation,
  and shadow artifacts.
- `CodexAuditBridge` owns provider routing and API keys.
- GitHub Issues are the first operator notification layer for scheduled shadow
  signal runs.
- The scheduled workflow builds the market context bundle before dispatching the
  bridge and embeds that bundle into the issue, because the bridge reads the
  source repository ref plus issue content.
- `QuantStrategyPlugins` may later read promoted artifacts as sidecar context.
- Platform repositories remain unchanged.

## Not Recommended

- Giving AI broker credentials.
- Parsing free text into orders.
- Letting AI change strategy thresholds, max leverage, universe membership, or
  execution mode.
- Re-generating old AI judgments during replay instead of replaying stored
  artifacts.
- Sending runtime Telegram or broker-facing notifications directly from this
  research repository before a deterministic plugin contract exists.

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
any downstream consumer.
