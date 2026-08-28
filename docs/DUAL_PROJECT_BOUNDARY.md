# 双项目职责边界（enterprise-rag × Copilot）

> 面试口径：**1+1>2 在治理层，不在问答层**。

| 能力 | enterprise-rag (:8001) | Copilot (:8002) |
|------|------------------------|-----------------|
| 向量检索 / 生成 | ✅ Ollama + 向量库 | 调用 HTTP |
| citations / conflicts | ✅ 产出 | 消费、展示 |
| 工单 draft 字段 | ✅ `/work-orders/draft` | 编排何时 draft |
| mock 收件箱 | ✅ `/work-orders/submit` → `/inbox` | 站长批准后 submit |
| 站长人确 (HITL) | ❌ | ✅ LangGraph interrupt |
| 配件预核 | ❌ | ✅ 本地演示台账 |
| POL 门禁 / 角色 | ❌ | ✅ Policy-as-Code |
| 意图分类（规则） | 可选（RAG 内） | ✅ 调度层 `classify_intent` |
| LLM inference | ✅ | ❌（仅调 RAG） |

## A-07 对比要点

裸工具链 `would_submit_without_hitl=true`；Copilot 强制 `waiting_hitl` + `POL-ROLE-01`。见 `data/eval/compare_report.json` · B01。

## 三层架构（答辩 PPT）

```
┌─────────────────┐
│  ERP / CRM      │  ← 虚线框，未实现（派工/排班/实时库存）
└────────┬────────┘
         │ 未来对接
┌────────▼────────┐
│ Copilot 门禁层   │  LangGraph · 质检 · HITL · POL-*
└────────┬────────┘
         │ HTTP
┌────────▼────────┐
│ enterprise-rag  │  知识 · 生成 · mock inbox
└─────────────────┘
```

## 仍不可宣称

- ERP 派工调度、技师排班、实时 WMS 库存
- 企业生产统一认证（当前为演示 API Key 映射）
- 端到端替代售后系统
