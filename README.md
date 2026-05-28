# AiLongHorizonSignalPipelines

Research-only long-horizon AI signal artifact repository for QuantStrategyLab.

This repository does not place trades, store broker credentials, or own live
allocation policy. It prepares and validates shadow signal artifacts that can
later be consumed by sidecar plugins after a separate review and promotion
process.

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

## Operating Model

1. A workflow creates a long-horizon shadow-signal issue.
2. The issue is dispatched to `QuantStrategyLab/CodexAuditBridge` with task
   `long_horizon_signal_shadow`.
3. `CodexAuditBridge` tries self-hosted Codex first and uses its own OpenAI or
   Anthropic API fallback only when configured.
4. Any AI-generated artifact must remain `mode=shadow` and pass local schema
   validation.
5. Downstream runtimes must treat the artifact as advisory context only until a
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

## Local Validation

Validate the example artifact:

```bash
python scripts/validate_latest_signal.py examples/latest_signal.example.json
```

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
