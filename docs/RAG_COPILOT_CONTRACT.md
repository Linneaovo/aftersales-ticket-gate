# enterprise-rag ↔ Copilot 字段契约（Live 联调）

> Copilot 消费 RAG HTTP 响应；**离线 FakeRag 必须模拟同字段**，否则 pytest 与 Live 分叉。

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

## `/work-orders/draft|submit`

| 端点 | Copilot 节点 | 说明 |
|------|--------------|------|
| `POST /work-orders/draft` | work_order | fault_dispatch 且无内联 draft |
| `POST /work-orders/submit` | submit | 站长 approve 后；destination=rag_mock_inbox |
| `GET /work-orders/inbox` | API proxy | 证明 mock 闭环 |

## submit 后 feedback

`POST /knowledge-bases/{kb}/feedback` — rating up/down 由 Copilot 根据 degraded/force_hitl 决定。

## Live 答辩检查

```bash
curl http://127.0.0.1:8002/health   # rag_mode=live
python scripts/live_integration_manual.py
```

P2 → `waiting_hitl` + POL-CONFLICT-01；P4 → `succeeded` + 无 work_order_draft。
