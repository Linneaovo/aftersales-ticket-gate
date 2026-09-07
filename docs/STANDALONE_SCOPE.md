# 单仓范围

本仓是否做完，以本页为准。联调失败不推翻这里的结论。

## 范围内

| 能力 | 证据位置 |
|------|----------|
| 规则意图 | `data/intent_rules.json`、剧本 |
| 主路径五条策略 | ROLE / CONFLICT / PARTS / SLA / DEGRADE |
| 站长确认 | 批准 / 拒绝 / 退回 |
| 配件预核 | 台账可改库存做对照 |
| Fixture 知识源 | `knowledge_port=fixture` |
| 本仓落箱 | `file_outbox` · `GET /outbox` |
| 决策快照 | HITL / 批准路径可校验 |
| 演示鉴权 | 写路径须显式 Key；单仓 `/health.linkage_claim=none` |
| Standalone scorecard | `data/eval/standalone_scorecard.json` |

## 范围外

ERP 派工 · 真 WMS/SSO · 本仓 LLM · 本仓自建向量库 · 生产审计中台

## 完成标准（不依赖 `:8001`）

- [x] `.env.standalone` / `COPILOT_RUNTIME_MODE=standalone`
- [x] 缺料：门禁 → 站长批准 → outbox 有记录
- [x] 冲突 / 脱敏场景可演示
- [x] `standalone_scorecard.json` 中 `all_ok=true`
- [x] CI 含 HITL / intent / standalone scorecard
- [x] `python scripts/demo_preflight.py --standalone` 通过

```bash
copy .env.standalone .env
python scripts/reset_demo_state.py
python scripts/demo_preflight.py --standalone
python scripts/build_governance_scorecard.py --profile standalone
```

改意图规则后请重跑 `python scripts/run_intent_eval.py`。HITL / intent 指标来自离线金标。

## 联调（可选）

见 [DUAL_REPO.md](DUAL_REPO.md)。联合包须 `live_verified=true` 才可声称真模型联调。
