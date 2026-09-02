# enterprise-rag ↔ Copilot 字段契约（Live 联调）

> **CONTRACT_VERSION = `2026-08-29.1`**（与 `app/tools/rag_contract.py`、RAG `/health.consumer_contract_version_supported` 对齐）  
> Copilot 消费 RAG HTTP 响应；**离线 FakeRag 必须模拟同字段**，否则 pytest 与 Live 分叉。  
> **可执行校验**：`app/tools/rag_contract.py` · `tests/test_rag_contract.py`（ask/draft/submit/inbox）。  
> `app/eval/rag_response_contract.py` 仅为旧 import 兼容再导出。  
> **消费字段钉扎表**：`data/eval/contract_consumer_fields.json`（breaking 须升版本；见 `app/eval/contract_fields.py`）。

## `/knowledge-bases/{kb}/ask` 响应

| 字段 | Copilot 消费方 | 期望 |
|------|----------------|------|
| `answer` | 质检措辞检测、摘要 | string |
| `sources` | POL-GROUND-01 | 非空 list 为佳 |
| `grounded` | POL-GROUND-01 | bool；冲突题 false 时 Copilot 软化为 force_hitl |
| `grounding_score` | POL-GROUND-01 阈值 0.35 | float |
| `blocked` / `block_reason` | POL-GROUND-02 硬拒 | acl_denied / chitchat / prompt_injection |
| `conflicts` | POL-CONFLICT-01 + conflict_bundle | 冲突题应非空或 intent=conflict_review |
| `work_order` | 仅 `fault_dispatch` + 可 draft 角色采纳 | **knowledge_only 不应携带** |
| `request_id` | rag_linkage_detail | string |

## `/work-orders/draft|submit|inbox`

| 端点 | Copilot 节点 | 说明 |
|------|----------------|------|
| `POST /work-orders/draft` | work_order | fault_dispatch 且无内联 draft |
| `POST /work-orders/submit` | submit | 站长 approve 后；destination=rag_mock_inbox；可选 `X-Copilot-Submit-Token`（RAG `SUBMIT_REQUIRE_COPILOT_TOKEN=1` 时业务路径必填，`contract_probe` 除外） |

演示硬门验收（默认关）：`demo_strict_submit.env.example` → 重启 `:8001` → `python scripts/demo_strict_submit_check.py`（或 `live_integration_manual.py --require-submit-token`）。
| `GET /work-orders/inbox` | API proxy | 证明 mock 闭环；默认 `lane=all` |

### submit 归属（E4 L2 · RAG **持久化**）

| 字段 | 业务路径 | 契约探针 |
|------|----------|----------|
| `source` | `copilot_hitl` | `contract_probe` |
| `submitted_by` | `copilot` | `contract_probe` |
| `run_id` | Copilot run_id | 可选 |
| `decision_certificate_phase` | `resolved` | `probe` |

- RAG inbox **落盘并回读**上述字段；缺省 → `legacy_unspecified`（不进 `lane=business`）。  
- 过滤：`lane=business|probe|all`（**默认 all**）或 `source=` 精确值。  
- 区分业务单与探针单**不依赖** `note` 前缀。

## submit 后 feedback

`POST /knowledge-bases/{kb}/feedback` — rating up/down 由 Copilot 根据 degraded/force_hitl 决定。  
**B6**：请求可带 `run_id`；result 须含合法 `sources`（可空数组）。  
回读：`GET /knowledge-bases/{kb}/feedback?run_id=`（advisory，不挡 `portfolio_claimable`）。  
脚本：`python scripts/check_feedback_roundtrip.py`（可选 `--live`）。

## Live 联调检查

```bash
curl http://127.0.0.1:8002/health   # rag_mode=live · rag_contract_version
curl http://127.0.0.1:8001/health   # consumer_contract_version_supported
python scripts/live_integration_manual.py
```

P2 → `waiting_hitl` + POL-CONFLICT-01；P4 → `succeeded` + 无 work_order_draft。
