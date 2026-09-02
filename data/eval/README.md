# 评测产物说明

入口：[docs/OVERVIEW.md](../../docs/OVERVIEW.md) · 范围：[docs/STANDALONE_SCOPE.md](../../docs/STANDALONE_SCOPE.md)

## Standalone（不依赖 :8001）

| 产物 | 说明 |
|------|------|
| `standalone_scorecard.json` 且 `all_ok=true` | `build_governance_scorecard.py --profile standalone` |
| `demo_preflight.py --standalone` 退出 0 | 启动前检查 |
| `/health`：`runtime_mode=standalone` · `submit_destination=file_outbox` | 运行时自检 |

```bash
copy .env.standalone .env
python scripts/reset_demo_state.py
python scripts/demo_preflight.py --standalone
python scripts/build_governance_scorecard.py --profile standalone
```

## 联调（分层）

| 产物 | 层级 | 说明 |
|------|------|------|
| `l1_linkage_report.json` 且 `l1_verified=true` | **L1** | Compose 契约 HTTP；`live_verified` 必须 false |
| `joint_evidence_pack.json` 且 `evidence_tier=L2` 且 `live_verified=true` | **L2** | 须真 RAG+模型 `--live` |
| `live_verified=false` / `evidence_tier=artifacts` | — | 不能当作当场 Live |
| `compare_report.json` | L0 对照 | 离线，不是 Live |

再生：

```bash
# L1
docker compose -f docker-compose.joint.yml up --build -d
python scripts/run_l1_linkage.py

# L2
python scripts/build_joint_evidence_pack.py --live
```

SSOT 宣称矩阵：`app/eval/evidence_tier.py` · 双仓说明：`docs/DUAL_REPO.md`

HITL / intent 报告来自**离线闭集金标**（`metric_kind=offline_goldset`），**≠ 线上 precision/recall**，勿当作生产 SLA。  
见 scorecard 中 `hitl_gate_agreement.value.note=offline_goldset_not_production_precision` 与 `false_hitl_cost_proxy`（advisory）。

| 指标 | 含义 | 勿误读为 |
|------|------|----------|
| `should_hitl_recall` | 金标「应进人确」样本被门禁拦下的比例 | 线上漏拦率 |
| `false_hitl_rate` | 金标「不应人确」却进 waiting_hitl 的比例 | 站长真实工时浪费 |
| `leak_submit_count` | 应拦却 submit 的进程内断言 | 生产误开单数 |

金标入口：`data/eval/goldsets/hitl_gate_cases.jsonl` · 再生：`python scripts/run_hitl_gate_eval.py`  
意图失败形态见 [intent_failure_notes.md](intent_failure_notes.md)。

## 入库 vs 本地弱产物

| 类别 | 例子 | 说明 |
|------|------|------|
| **CI 钉扎（宜入库）** | `standalone_scorecard.json` · `hitl_gate_report.json` · `governance_scorecard.json` · `live_integration_manual.json` · `live_function_test.json` | `check_eval_git_sha` / `test_live_contract` 会校验 |
| **金标输入** | `goldsets/` · `intent_cases*.jsonl` · `cases.jsonl` · `contract_consumer_fields.json` | 源数据，勿当报告 |
| **弱生成物（gitignore）** | `intent_weight_sensitivity.json` · `plan_b_trace.json` · `replay_*.json` | 本机可选再生，不作验收钉扎 |

## 分层

1. Standalone — 本仓主验收  
2. L0 pytest FakeRag — 离线编排；collect 见 `app/eval/ssot.py`  
3. **L1** Compose 契约联调 — `linkage-l1.yml`（默认可复现）  
4. **L2** Live / 联合包 — self-hosted / 本机；须 `live_verified=true`  
5. CI — L0+L1 默认绿；L2 workflow 默认关
