# 双仓协作

知识层与开单门禁拆成两个仓库：单仓可先验收门禁；接上知识仓后再做联调。

| | 知识层 | 行动层（本仓） |
|--|--------|----------------|
| 本地目录 | `enterprise-rag` | `aftersales-dispatch-copilot` |
| GitHub | （姊妹仓） | [Linneaovo/aftersales-ticket-gate](https://github.com/Linneaovo/aftersales-ticket-gate) |
| 产品名 | 售后知识治理 Copilot | 报修开单门禁 Copilot |
| 职责 | 检索、生成、引用、权限过滤、冲突并列 | 门禁、站长确认、配件预核、提交归属 |
| 入口 | UI `:8501` · API `:8001` | UI `:8502` · API `:8002` · [README](../README.md) |

只克隆本仓时，只能验收开单门禁，不能把它说成完整的「检索生成系统」。知识仓答得靠谱，也不等于本仓允许开单。

## 能力对照

| 能力 | 知识仓 | 本仓 |
|------|--------|------|
| 向量检索 / 生成 | 有 | 联调时调 HTTP；单仓用 Fixture |
| 引用 / 冲突并列 | 产出 | 展示；冲突不替站长裁决 |
| 工单草稿字段 | `/work-orders/draft` | 决定何时要草稿 |
| 落箱 | mock inbox（联调） | 单仓 `file_outbox`；联调批准后也可写入 RAG inbox |
| 站长确认 | 无 | 有 |
| 配件预核 / 策略门禁 | 无 | 有 |
| 本仓内 LLM | — | 无 |

联调时业务提交应带 `source=copilot_hitl`；知识仓侧契约探测提交应标 `contract_probe`，与业务路径分开。

## 证据分层

| 层 | 含义 | 怎么跑 |
|----|------|--------|
| L0 | 离线编排回归 | `ci.yml` / pytest |
| L1 | HTTP 契约与提交归属（Compose 桩） | `linkage-l1.yml` · `run_l1_linkage.cmd` |
| L2 | 真知识仓 + 模型 | 本机 · 联合包 `live_verified=true` |

L1 不证明检索质量。`--from-artifacts` 或历史快照不是 L2。字段约定：`app/eval/evidence_tier.py`。

### 复现 L1

```bash
docker compose -f docker-compose.joint.yml up --build -d
docker compose -f docker-compose.joint.yml exec api python scripts/reset_demo_state.py
docker compose -f docker-compose.joint.yml exec api python scripts/run_l1_linkage.py
```

产物：`data/eval/l1_linkage_report.json`（`l1_verified=true`，`live_verified=false`）。

## 演示怎么分

| 场合 | 讲什么 | 留给对方 |
|------|--------|----------|
| 本仓单仓 | 缺料 → 站长确认 → outbox | 检索公式、金标 |
| 知识仓 | 越权拒答、冲突并列、有据草稿 | 站长确认、缺料台账 |
| 联调（短） | 草稿 → 门禁批准 → inbox | — |

联调全红不否定本仓单仓是否完成。

## 相关文档

| 文档 | 用途 |
|------|------|
| [../DEMO_SCRIPT.md](../DEMO_SCRIPT.md) | 演示步骤 |
| [RAG_COPILOT_CONTRACT.md](RAG_COPILOT_CONTRACT.md) | HTTP 契约 |
| [../data/eval/README.md](../data/eval/README.md) | 评测产物 |
| [_internal/LIVE_RUNNER.md](_internal/LIVE_RUNNER.md) | 可选 L2 runner |
