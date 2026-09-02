# 单仓范围（Standalone）

> 本仓是否做完，以本页为准。联调失败不推翻本页结论。

## 产品一句

可插拔知识源的售后报修开单门禁编排；默认 Fixture + `file_outbox` 即可演示与验收。  
外接知识库是可选适配，不是完成本仓的前提。

## 范围内

| 能力 | 证据 |
|------|------|
| 规则意图分流 | `data/intent_rules.json`、playbooks |
| 核心五条 POL | ROLE / CONFLICT / PARTS / SLA / DEGRADE |
| 分层 HITL | LangGraph interrupt；approve / reject / return |
| 配件预核 | parts ledger（可改库存做对照） |
| Fixture 知识源 | `knowledge_port=fixture`（显式离线，不是静默假联调） |
| 本仓落箱 | `SUBMIT_DESTINATION=file_outbox` · `GET /outbox` |
| 决策快照 | HITL 路径可校验 Decision Snapshot（不是防篡改审计中台） |
| Standalone Scorecard | `data/eval/standalone_scorecard.json`（脚本生成） |

## 范围外

ERP/CRM 派工 · 真 WMS/SSO · Copilot 内 LLM/Multi-Agent · 本仓自建向量库 · 生产审计中台

## 完成标准（可复现 · 不依赖 :8001）

- [x] `COPILOT_RUNTIME_MODE=standalone`（或 `.env.standalone`）
- [x] 缺料场景：POL-PARTS → 站长批准 → outbox 可见记录
- [x] 冲突/脱敏场景可演示
- [x] `standalone_scorecard.json`：`all_ok=true`
- [x] CI：HITL eval + intent eval + standalone scorecard
- [x] 本机：`python scripts/demo_preflight.py --standalone`（需 `:8002` + `.env.standalone`）
- [x] 本机：`/health` 无 `mode_warnings` 且 scorecard 标志为真（preflight 已验）
- [x] 介绍时可不提外仓名

改意图规则后须重跑 `python scripts/run_intent_eval.py`。  
HITL / intent 指标来自离线金标，不是线上 precision。

```bash
copy .env.standalone .env
python scripts/reset_demo_state.py
python scripts/demo_preflight.py --standalone
python scripts/build_governance_scorecard.py --profile standalone
```

## 附录：联调（可选）

- 联合证据包且 `live_verified=true`
- 契约版本一致；探针提交与业务路径隔离
