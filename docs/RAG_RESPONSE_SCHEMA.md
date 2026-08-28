# enterprise-rag 最小响应契约（Copilot 侧约定）

> **Live 联调完整版**见 [RAG_COPILOT_CONTRACT.md](RAG_COPILOT_CONTRACT.md)（含 P2/P4 分叉说明）。

Copilot 通过 `app/tools/rag_normalize.py` 对齐 RAG 响应；**normalize 只处理已知字段差异**，未知字段忽略。

## `/ask` 最小 schema

```json
{
  "answer": "string（必填）",
  "sources": [{"chunk": {"source": "string", "text": "string"}, "score": 0.0}],
  "grounded": true,
  "grounding_score": 0.85,
  "blocked": false,
  "block_reason": null,
  "conflicts": [],
  "request_id": "string",
  "work_order": {}
}
```

| 字段 | 用途 |
|------|------|
| `answer` | 质检 grounding、摘要展示 |
| `sources` | 引用计数、质检 |
| `grounded` / `grounding_score` | POL-DEGRADE 触发 |
| `conflicts` | conflict_bundle（不作裁决） |
| `work_order` | 可选内联草稿，跳过二次 draft |

## `/work-orders/draft` 最小 schema

```json
{
  "ok": true,
  "draft": {
    "ticket_type": "fault",
    "machine_model": "SY215C",
    "fault_codes": ["H103"],
    "recommended_parts": ["液压泵总成"]
  }
}
```

## `/work-orders/submit` 最小 schema

```json
{
  "ok": true,
  "ticket_id": "T-xxx"
}
```

## 版本约定

- RAG 新增字段：Copilot 透传或忽略，不破坏现有流程
- RAG 重命名字段：在 `rag_normalize.py` 增加 alias 映射并补测试
- 答辩前双方确认 `demo-kb` 语料与上述字段可用
