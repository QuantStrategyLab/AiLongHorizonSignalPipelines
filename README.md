# ResearchSignalContextPipelines

[Chinese README](README.zh-CN.md)

> ⚠️ Investing involves risk. This project does not provide investment advice and is for educational and research purposes only.

## What this project does

ResearchSignalContextPipelines is a **Research context pipeline** in the QuantStrategyLab ecosystem. It builds research signal context artifacts for medium-horizon themes and long-horizon AI shadow context.

## Who this is for

- Engineers and researchers who want to inspect, reproduce, or extend this part of the QuantStrategyLab stack.
- Operators who need a clear entry point before reading the deeper runbooks or workflow files.
- Reviewers who need to understand the repository purpose, safety boundary, and evidence requirements before enabling automation.

## Current status

Research-only artifact pipeline; outputs are context, not trade instructions.

## Repository layout

- `src/`: main library and runtime code.
- `tests/`: unit and contract tests.
- `docs/`: detailed design notes, runbooks, and evidence docs.
- `.github/workflows/`: CI, scheduled jobs, and deployment workflows.
- `scripts/`: operator scripts and local helpers.

## Quick start

From a fresh clone:

```bash
python -m pip install -e .
python -m pytest -q
```

If a command requires credentials, run it only after reading the relevant workflow or runbook and configuring secrets outside Git.

## Deployment and operation

Run the configured workflows or local commands to refresh artifacts. Review source coverage and artifact diffs before publishing downstream.

Prefer manual or dry-run execution first. Enable schedules or live execution only after logs, artifacts, permissions, and rollback steps are reviewed.

## Strategy performance and evidence

Not a trading strategy repository. Evidence quality is measured by source traceability, freshness, and downstream review usefulness.

README files are intentionally not a source of dated performance promises. Re-run the relevant tests, backtests, or pipeline jobs before relying on any result.

## Safety notes

- Never commit API keys, broker credentials, OAuth tokens, cookies, or account identifiers.
- Run new strategies and platform changes in dry-run or paper mode before any live execution.
- Review generated orders, artifacts, and logs manually before enabling schedules.

## Contributing

Keep changes small, reproducible, and covered by the narrowest useful tests. For strategy-facing changes, include the evidence artifact or command used to validate behavior.

## License

See [LICENSE](LICENSE) if present in this repository.
