# AiLongHorizonSignalPipelines

Research-only long-horizon AI signal artifact repository for QuantStrategyLab.

This repository does not place trades, store broker credentials, or own live
allocation policy. It prepares and validates shadow signal artifacts that can
later be consumed by sidecar plugins after a separate review and promotion
process.

## Repository Role

This is a research artifact repository, not an agent runner, model gateway,
execution service, or strategy plugin repository.

Its job is to keep point-in-time research evidence reproducible:

- build current-market context bundles
- create dated GitHub Issues for operator review
- store schema-valid shadow AI signal artifacts
- preserve `signal_history` for future walk-forward replay
- provide deterministic replay tooling around saved artifacts

`CodexAuditBridge` remains the only bridge/runner for model providers and
cross-repository write automation. Future live or notification behavior belongs
in a separate deterministic plugin after the shadow artifacts have enough
evidence.

## Boundary

This repo owns:

- long-horizon AI context bundle examples
- shadow signal JSON schema expectations
- validation tooling for `latest_signal.json`
- issue/workflow handoff to `QuantStrategyLab/CodexAuditBridge`
- replay-ready artifact records for later research review

This repo does not own:

- broker API access
- order placement
- live portfolio allocation
- deterministic strategy rules in `UsEquityStrategies`
- runtime plugin execution in `QuantStrategyPlugins`
- API keys for model providers
- Codex/OpenAI/Anthropic provider routing
- GitHub App token minting for source repository writes
- Telegram or broker-facing runtime notifications

## Current Status

This repository is in shadow research accumulation mode. The first saved
point-in-time artifact is `data/output/signal_history/2026-05-28.json`.

Near-term work should focus on:

- keeping the monthly workflow healthy
- accumulating saved `signal_history/*.json` artifacts
- replaying only saved artifacts, not regenerated historical AI judgments
- improving context quality before any downstream plugin integration

Do not promote the output into runtime allocation or notifications until the
saved artifact history has enough walk-forward evidence to justify a separate
plugin contract.

## Operating Model

1. A monthly workflow builds a point-in-time context bundle from current market
   prices.
2. The workflow creates or updates a dated long-horizon shadow-signal issue and
   embeds the context bundle as review evidence.
3. The issue is dispatched to `QuantStrategyLab/CodexAuditBridge` with task
   `long_horizon_signal_shadow`.
4. `CodexAuditBridge` tries self-hosted Codex first and uses its own OpenAI or
   Anthropic API fallback only when configured.
5. Any AI-generated artifact must remain `mode=shadow` and pass local schema
   validation.
6. Downstream runtimes must treat the artifact as advisory context only until a
   separate deterministic policy engine explicitly consumes it.

## GitHub Configuration

The model API keys are centralized in `CodexAuditBridge`; do not add
`OPENAI_API_KEY` or `ANTHROPIC_API_KEY` to this repository.

This repository needs only dispatch credentials for the bridge workflow:

- preferred: `CROSS_REPO_GITHUB_APP_ID` variable and
  `CROSS_REPO_GITHUB_APP_PRIVATE_KEY` secret with Actions write permission on
  `CodexAuditBridge`
- fallback: `CODEX_AUDIT_DISPATCH_TOKEN` secret with permission to dispatch the
  bridge workflow

Configured non-secret variables:

- `SELFHOSTED_CODEX_REVIEW_REPOSITORY=QuantStrategyLab/CodexAuditBridge`
- `SELFHOSTED_CODEX_REVIEW_PROVIDER=auto`
- `CROSS_REPO_GITHUB_APP_ID=3250578`

## Notification Policy

The GitHub issue created by `.github/workflows/dispatch_shadow_signal.yml` is the
initial operator notification channel. It is labeled `long-horizon-shadow`,
deduplicated by date, and receives the CodexAuditBridge result as comments or a
focused PR.

Do not add Telegram, broker, or runtime plugin notifications at this stage. Those
belong downstream only after the signal graduates from shadow research to a
deterministic plugin contract.

## Local Validation

Validate the example artifact:

```bash
python scripts/validate_latest_signal.py examples/latest_signal.example.json
```

Build a context bundle from a local price file:

```bash
python scripts/build_context_bundle.py \
  --prices examples/price_history.example.csv \
  --symbols QQQ \
  --output data/output/context_bundle/latest_context_bundle.json
```

Without `--prices`, the script downloads recent daily prices for the default
universe through Yahoo's chart endpoint and writes a point-in-time context bundle
for the monthly shadow issue. The scheduled workflow uses
`--allow-download-errors`, so external data-source failures still create an
operator issue with the failure recorded instead of silently skipping the run.

Validate the promoted latest artifact when it exists:

```bash
python scripts/validate_latest_signal.py
```

Run the synthetic overlay replay:

```bash
python scripts/backtest_signal_overlay.py \
  --prices examples/price_history.example.csv \
  --signals examples/signal_history \
  --symbol QQQ
```

The replay tests a deterministic risk-reducing overlay only. It does not call
AI models and does not treat the example as production evidence.

Extract compact real-price input from an existing QuantStrategyLab price file:

```bash
python scripts/extract_price_history.py \
  --source ../UsEquitySnapshotPipelines/data/output/tqqq_growth_income_real_full_archive_2026-05-26/price_history.csv \
  --target data/input/qqq_price_history.csv \
  --symbols QQQ
```

Then replay stored shadow signals against those prices:

```bash
python scripts/backtest_signal_overlay.py \
  --prices data/input/qqq_price_history.csv \
  --signals data/output/signal_history \
  --symbol QQQ \
  --output data/output/tmp/replay_summary.json
```

The price loader accepts both this repository's compact `date,symbol,close`
schema and the existing QuantStrategyLab `symbol,as_of,close` schema.

## Artifact Contract

The latest artifact path is:

```text
data/output/latest_signal.json
```

Historical generated copies can be stored under:

```text
data/output/signal_history/YYYY-MM-DD.json
```

All artifacts must remain shadow-only. They cannot encode broker orders, target
quantities, or live allocation overrides.

## Replay Contract

Historical validation should replay stored signal artifacts instead of asking a
model to re-create old judgments. The current example policy is intentionally
conservative:

- no active signal: keep baseline exposure
- `confidence < 0.55`: no-op
- `risk_off`: reduce exposure to `0.5`
- `mixed`: reduce exposure to `0.8`
- severe risk flags such as `liquidity_stress` cap exposure at `0.6`
- the overlay never increases exposure above the baseline
