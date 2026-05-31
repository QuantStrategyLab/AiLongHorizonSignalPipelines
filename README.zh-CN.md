# ResearchSignalContextPipelines

> ⚠️ 投资有风险，不构成投资建议，仅供学习交流用途。

[English](README.md) | [简体中文](README.zh-CN.md)

QuantStrategyLab 的研究型信号上下文 artifact 仓库。

当前 schema validation 要求新生成和 promoted 的 shadow signal artifact 使用 `1-3 years` 周期。较早的 pre-contract 历史 artifact 可以保留原始点时 horizon 文本，但不应再作为当前 `latest_signal.json` 推广。

本仓库不下单、不保存券商凭证，也不拥有实盘仓位策略。它只负责准备、校验、保存和回放研究信号上下文，包括中线主题动量和长周期 AI shadow signal。任何未来的下游使用，都必须经过单独评审，并由确定性插件或策略显式消费。

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
- 中线主题动量 taxonomy、symbol exposure 和 snapshot 生成工具
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

当前 promoted artifact 是：

```text
data/output/signal_history/2026-05-31.json
```

它使用长线 contract，并补充了 `theme_bias`、`symbol_theme_exposure` 和 `symbol_bias`，供 Advisor 判断长线背景是否可用。

近期工作重点：

- 保持周度主题动量 workflow 和月度 AI shadow workflow 健康
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


## 名称和周期边界

`ResearchSignalContextPipelines` 是这一层的正式仓库名。这个名字对应它现在的真实职责：维护可复用的研究上下文 artifact，包括中线主题动量和长线 AI shadow context。短线/中线/长线最终推荐仍由 `QuantAdvisorResearch` 生成，本仓库不直接输出最终推荐。


## 短中长线边界

本仓库不直接输出短线买卖推荐。周期分工保持如下：

- 短线（1-10 个交易日）：由 `PoliticalEventTrackingResearch` 的事件和 `QuantAdvisorResearch` 的确定性规则处理；AI 只可作为解释背景，不直接决定短线。
- 中线（2-12 周）：由本仓库的 `theme_momentum_snapshot.json` 提供 `medium_horizon_theme_context`，包括主题动量、主题广度和主题内强势标的。
- 长线（1-3 年）：由本仓库的 `latest_signal.json` / `signal_history/*.json` 提供 AI shadow context。

最终短线、中线、长线推荐统一由 `QuantAdvisorResearch` 合成，本仓库仍不下单、不配仓、不输出账户级建议。

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

所有 promoted latest artifacts 必须使用 `horizon: "1-3 years"`。为了支持 Advisor 的长线栏位，当前 artifact 应包含 `theme_bias`、`symbol_theme_exposure`，必要时用 `symbol_bias` 补充单个股票的长线背景。

所有 artifacts 必须保持 shadow-only。它们不能编码券商订单、目标数量或实盘 allocation override。

`candidate_bias` 和 `theme_bias` 支持两种写法。兼容旧的紧凑写法：

```json
{"MU": "watch"}
```

也支持更适合审计的结构化写法：

```json
{
  "MU": {
    "bias": "watch",
    "confidence": 0.55,
    "linked_themes": ["hbm_memory"],
    "rationale": "只作为 shadow context，不是交易指令。"
  }
}
```

`symbol_bias` 是可选字段，使用同样结构表达单个 symbol 的长线背景。下游 Advisor 只把这些字段当作上下文，仍然禁止订单、目标股数和组合权重。

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

## 跨板块主题 universe

本仓库现在不仅覆盖 AI 主题，也固定维护一个跨板块长期主题 taxonomy：

```text
config/theme_taxonomy.csv
config/symbol_theme_exposure.csv
```

覆盖方向包括 AI compute、HBM/存储、foundry/半导体政策、AI server、数据中心电力、网络安全、国防航天、能源安全、清洁电网、金融基础设施、医疗政策、消费平台、工业自动化、crypto 基础设施和 EV/汽车。

这些配置是长期研究上下文，不是热点追涨列表。月度 context bundle 会把主题暴露写入 `theme_context`，供 AI shadow review 使用；任何推荐或回测仍必须基于已保存 artifact，不能在回测时重新生成历史判断。

## 主题动量定时刷新

`.github/workflows/theme_momentum_snapshot.yml` 每周在 Advisor 发布前运行，生成 `data/output/theme_momentum_snapshot.json`。该 artifact 明确标记为 `medium_horizon_theme_context`，对应中线 2-12 周主题上下文。定时运行时如果快照有变化，会提交回仓库，供 `QuantAdvisorResearch` 读取点时 artifact。手工运行可以传 `prices_path`，使用可审计的本地价格 CSV，而不是临时下载。

Yahoo chart 下载仍然只是临时 fallback。使用本地价格 CSV 时，快照会记录来源和文件 hash。随机免费代理 IP 池不应进入稳定链路，因为它会增加 replay、数据质量和合规复核难度。

## 主题动量快照

跨板块主题 taxonomy 只是定义“股票属于哪些长期主题”。真正的排序由独立的主题动量快照完成，避免因为近期热门标的临时改 universe 或权重。

使用本地价格 CSV 生成快照：

```bash
python scripts/build_theme_momentum_snapshot.py \
  --prices data/input/theme_price_history.csv \
  --symbols MU,INTC,DELL,NVDA,VRT,UNH,XOM,JPM,LMT \
  --output data/output/theme_momentum_snapshot.json
```

不传 `--prices` 时脚本会通过 Yahoo chart endpoint 下载价格。默认允许部分 symbol 下载失败，失败标的会进入 `data_quality.missing_price_symbols`；如果需要严格模式，传 `--strict-downloads`。

快照会输出：

- `theme_ranks`：主题排名、动量分、breadth、风险惩罚和主题内 top symbols
- `methodology`：固定窗口和权重，便于后续 walk-forward replay
- `artifact_type`：`medium_horizon_theme_context`，表示中线主题上下文，不是短线 AI 推荐
- `horizon` / `horizon_window`：`medium` / `2-12 weeks`
- `policy`：明确这是研究排序，不允许下单或仓位分配
- `data_quality.coverage`：配置标的数、已有价格标的数、价格覆盖率和价格历史不足标的

当前固定窗口：

- `12-1m`：252 个交易日 lookback，跳过最近 21 个交易日
- `6-1m`：126 个交易日 lookback，跳过最近 21 个交易日
- `3m`：63 个交易日近期动量

主题排名只说明“哪些主题值得研究”，不是买入信号。进入 Advisor 推荐仍需要事件证据、来源质量和风险检查。
