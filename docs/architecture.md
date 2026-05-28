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
- `QuantStrategyPlugins` may later read promoted artifacts as sidecar context.
- Platform repositories remain unchanged.

## Not Recommended

- Giving AI broker credentials.
- Parsing free text into orders.
- Letting AI change strategy thresholds, max leverage, universe membership, or
  execution mode.
- Re-generating old AI judgments during replay instead of replaying stored
  artifacts.

## Validation Strategy

The current minimum check is schema validation for `latest_signal.json`. Future
promotion should add replay tests that consume stored artifacts without calling
model APIs.

## Risk Notes

The artifact is research evidence, not a trading instruction. Missing evidence,
expired artifacts, low confidence, or schema failures should default to no-op in
any downstream consumer.
