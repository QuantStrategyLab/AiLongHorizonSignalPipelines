# AiLongHorizonSignalPipelines

[English](README.md) | [简体中文](README.zh-CN.md)

QuantStrategyLab 的研究型长周期 AI shadow signal artifact 仓库。

本仓库不下单、不保存券商凭证，也不拥有实盘仓位策略。它只负责准备、校验、保存和回放长周期 AI shadow signal。任何未来的下游使用，都必须经过单独评审，并由确定性插件或策略显式消费。

## 仓库定位

这是一个 research artifact repository，不是 agent runner、模型网关、执行服务或策略插件仓。

本仓库的职责是让点时研究证据可复现：

- 构建当前市场 context bundle
- 创建带日期的 GitHub Issue 供 operator 审阅
- 保存 schema-valid 的 shadow AI signal artifacts
- 保存 `signal_history` 供未来 walk-forward replay
- 围绕已保存 artifacts 提供确定性 replay 工具

`CodexAuditBridge` 仍然是唯一的模型 provider bridge/runner，负责模型 API、跨仓写权限和 PR/Issue 自动化。未来如果要接入实盘或通知系统，应在积累足够 shadow evidence 后，另建确定性插件 contract。

## 边界

本仓库负责：

- 长周期 AI context bundle 示例和生成工具
- shadow signal JSON schema 约束
- `latest_signal.json` 校验工具
- 向 `QuantStrategyLab/CodexAuditBridge` 交接 issue/workflow
- 可 replay 的 artifact 记录

本仓库不负责：

- 券商 API 访问
- 下单
- 实盘组合配置
- `UsEquityStrategies` 中的确定性策略规则
- `QuantStrategyPlugins` 中的运行时插件执行
- 模型 provider API keys
- Codex/OpenAI/Anthropic provider routing
- source repo 写权限的 GitHub App token minting
- Telegram 或券商侧运行时通知

## 当前状态

本仓库处于 shadow research accumulation mode。第一条已保存的点时 artifact 是：

```text
data/output/signal_history/2026-05-28.json
```

近期工作重点：

- 保持月度 workflow 健康
- 持续积累 `signal_history/*.json`
- 只 replay 已保存 artifacts，不让模型重新生成历史判断
- 在任何下游插件集成前，先提升 context 质量并积累证据

在 `signal_history` 积累出足够 walk-forward evidence 之前，不应把输出接入运行时仓位或通知系统。

## 运行模式

1. 月度 workflow 根据当前市场价格构建 point-in-time context bundle。
2. workflow 创建或更新带日期的 long-horizon shadow-signal issue，并把 context bundle 嵌入 issue 作为审阅证据。
3. issue 被 dispatch 到 `QuantStrategyLab/CodexAuditBridge`，任务类型是 `long_horizon_signal_shadow`。
4. `CodexAuditBridge` 优先运行 self-hosted Codex；只有在配置允许时才使用 OpenAI 或 Anthropic API fallback。
5. 所有 AI 生成的 artifact 必须保持 `mode=shadow`，并通过本地 schema validation。
6. 下游系统在单独的确定性 policy engine 显式消费前，只能把 artifact 当作 advisory context。

## GitHub 配置

模型 API key 集中在 `CodexAuditBridge`；不要把 `OPENAI_API_KEY` 或 `ANTHROPIC_API_KEY` 放到本仓库。

本仓库只需要 bridge workflow dispatch 凭证：

- 推荐：`CROSS_REPO_GITHUB_APP_ID` variable 和 `CROSS_REPO_GITHUB_APP_PRIVATE_KEY` secret，且该 GitHub App 对 `CodexAuditBridge` 有 Actions write 权限
- fallback：`CODEX_AUDIT_DISPATCH_TOKEN` secret，具备 dispatch bridge workflow 的权限

已配置的非 secret variables：

- `SELFHOSTED_CODEX_REVIEW_REPOSITORY=QuantStrategyLab/CodexAuditBridge`
- `SELFHOSTED_CODEX_REVIEW_PROVIDER=auto`
- `CROSS_REPO_GITHUB_APP_ID=3250578`

## 通知策略

`.github/workflows/dispatch_shadow_signal.yml` 创建的 GitHub Issue 是当前 operator notification channel。Issue 使用 `long-horizon-shadow` label，按日期去重，并接收 `CodexAuditBridge` 的审计回帖或 artifact PR。

当前阶段不要添加 Telegram、券商或 runtime plugin 通知。这些应在 shadow signal 晋级为确定性插件 contract 后，由下游系统负责。

## 本地验证

校验示例 artifact：

```bash
python scripts/validate_latest_signal.py examples/latest_signal.example.json
```

从本地价格文件构建 context bundle：

```bash
python scripts/build_context_bundle.py \
  --prices examples/price_history.example.csv \
  --symbols QQQ \
  --output data/output/context_bundle/latest_context_bundle.json
```

不传 `--prices` 时，脚本会通过 Yahoo chart endpoint 下载默认 universe 的近期日线价格，并写出月度 shadow issue 使用的 point-in-time context bundle。定时 workflow 使用 `--allow-download-errors`，所以外部数据源失败时仍会创建 operator issue，并把失败原因写入 context。

校验已 promoted 的 latest artifact：

```bash
python scripts/validate_latest_signal.py
```

运行合成 overlay replay：

```bash
python scripts/backtest_signal_overlay.py \
  --prices examples/price_history.example.csv \
  --signals examples/signal_history \
  --symbol QQQ
```

这个 replay 只测试确定性的 risk-reducing overlay。它不调用 AI model，也不把示例结果当作生产证据。

从现有 QuantStrategyLab 价格文件抽取紧凑 replay 输入：

```bash
python scripts/extract_price_history.py \
  --source ../UsEquitySnapshotPipelines/data/output/tqqq_growth_income_real_full_archive_2026-05-26/price_history.csv \
  --target data/input/qqq_price_history.csv \
  --symbols QQQ
```

然后用已保存的 shadow signals replay：

```bash
python scripts/backtest_signal_overlay.py \
  --prices data/input/qqq_price_history.csv \
  --signals data/output/signal_history \
  --symbol QQQ \
  --output data/output/tmp/replay_summary.json
```

price loader 同时支持本仓库的紧凑 `date,symbol,close` schema，以及现有 QuantStrategyLab 的 `symbol,as_of,close` schema。

## Artifact Contract

latest artifact 路径：

```text
data/output/latest_signal.json
```

历史副本路径：

```text
data/output/signal_history/YYYY-MM-DD.json
```

所有 artifacts 必须保持 shadow-only。它们不能编码券商订单、目标数量或实盘 allocation override。

## Replay Contract

历史验证必须 replay 已保存 signal artifacts，而不是让模型重新生成过去的判断。当前示例 policy 有意保持保守：

- 没有 active signal：保持 baseline exposure
- `confidence < 0.55`：no-op
- `risk_off`：降到 `0.5`
- `mixed`：降到 `0.8`
- 严重 risk flags，例如 `liquidity_stress`，把 exposure cap 到 `0.6`
- overlay 永远不能把 exposure 提高到 baseline 以上

## 许可证

本仓库使用 MIT License。详见 [LICENSE](LICENSE)。
