# scripts

## 日常

| 脚本 | 用途 |
|------|------|
| `demo_preflight.py --standalone` | 单仓启动前检查 |
| `reset_demo_state.py` | 清空演示状态 |
| `build_governance_scorecard.py --profile standalone` | 生成 standalone scorecard |
| `run_hitl_gate_eval.py` / `run_intent_eval.py` | 离线门禁 / 意图评测 |

## 联调与排障（可选）

| 脚本 | 用途 |
|------|------|
| `rag_contract_stub.py` | **L1** 契约 RAG HTTP 桩（:8001） |
| `run_l1_linkage.py` / `../run_l1_linkage.cmd` | **L1** Compose/本机契约联调验收 → `l1_linkage_report.json` |
| `run_responsibility_chain_verify.py` | **L2** 四层责任链 + 可选 `--pack` |
| `run_responsibility_chain.cmd` | 一键 Live 责任链 + 证据包 |
| `run_joint_verify.py` | V1–V3 矩阵 + 宣称规则 |
| `demo_preflight.py --require-rag --matrix` | 预检并转入上述矩阵；`--pack-matrix` 连带证据包 |
| `build_joint_evidence_pack.py` | 联合证据包；`evidence_tier`+`live_verified`；`--from-artifacts` 永不可称 L2 |
| `live_*` / `*_contract_check.py` | Live 契约与冒烟 |
| `rehearse_rag_failure.py` / `build_joint_failure_drill.py` | 失败演练 |
| `mock_parts_wms.py` | 本地配件 HTTP mock |

口径：Standalone 绿 ≠ L1 ≠ L2；L1 证契约不证检索；仅 L2 `live_verified=true` 可称本机 Live；token 为演示归属非生产鉴权；Plan B/from_artifacts 不得冒充联调。

其余 `check_*` 为仓库一致性校验，供 CI 或发版前使用。

## 可选 / 非日常

| 脚本 | 用途 |
|------|------|
| `intent_weight_sensitivity.py` | 意图权重敏感性（产出 gitignore，非验收钉扎） |
| `list_file_outbox.py` | CLI 便利；API 已有 `GET /outbox` |
| `replay_trace.py` / `rehearse_rag_failure.py` | 演示/容灾辅助 |
