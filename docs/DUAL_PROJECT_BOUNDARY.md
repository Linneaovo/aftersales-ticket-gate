# 双项目职责边界（enterprise-rag × Copilot）

> 面试口径：本仓可独立验收；与 RAG 的协同在治理层体现，不在问答层硬绑。
> 总入口：[OVERVIEW.md](OVERVIEW.md) · 自立：[STANDALONE_SCOPE.md](STANDALONE_SCOPE.md)

| 能力 | enterprise-rag (:8001 / UI :8501) | Copilot (:8002 / UI :8502) |
|------|------------------------|-----------------|
| 定位 | **知识治理台**（产品：售后知识治理 Copilot） | **开单门禁台**（产品：报修开单门禁 Copilot；可插拔知识源；非站长作业 App） |
| 向量检索 / 生成 | ✅ Ollama + 向量库 | Live 时调 HTTP；Standalone 用 Fixture |
| citations / conflicts | ✅ 产出 | 消费、展示；冲突不作裁决 |
| 工单 draft 字段 | ✅ `/work-orders/draft` | 编排何时 draft（Fixture 亦可给契约形 draft） |
| 落箱 | ✅ RAG mock inbox（Joint） | ✅ 本仓 `file_outbox`（Standalone 默认）或批准后调 RAG submit |
| 站长人确 (HITL) | ❌ | ✅ LangGraph interrupt |
| Decision Certificate | ❌（有 citations） | ✅ 行动审计证书 |
| 配件预核 | ❌ | ✅ 本地演示台账 |
| POL 门禁 / 角色 | ❌ | ✅ Policy-as-Code |
| 意图分类（规则） | 可选（RAG 内） | ✅ 编排层 `classify_intent`（关键词，非 LLM） |
| LLM inference | ✅ | ❌（不在本仓） |

## 演示分工（去重叠）

| 仓 | 主线（只讲这些） | 留给对方 |
|----|------------------|----------|
| Copilot **单仓（主）** | P1 缺料 → HITL → 本仓 outbox → 证书 | 检索公式 / 金标 |
| enterprise-rag（若同场） | 越权 ACL → 质保冲突并列 → 有据 draft | HITL / 缺料 / Certificate |
| **联调（可选）** ≤1–2min | draft → 门禁批准 → RAG mock inbox | — |

**Joint 全红不否定 Copilot Standalone 完成度。**

**inbox 所有权（Joint）**：RAG 提供 `/work-orders/submit|inbox`；**仅 Copilot 站长批准后**业务 submit（`source=copilot_hitl`）。RAG 侧直接 submit 须标 `source=contract_probe`。  
**Standalone**：业务落箱在本仓 `file_outbox`，经 `GET /outbox` 回读。

## A-07 对比要点

裸工具链 `would_submit_without_hitl=true`；Copilot 强制 `waiting_hitl` + `POL-ROLE-01`。见 `data/eval/compare_report.json` · B01（**离线对照，非 Live 验收**）。

## 架构示意

```
┌─────────────────┐
│  ERP / CRM      │  ← 虚线框，未实现
└────────┬────────┘
         │ 未来对接
┌────────▼────────┐
│ Copilot 门禁层   │  LangGraph · POL · HITL · Certificate · file_outbox
│ KnowledgePort   │  Fixture（自立）或 Http → RAG（加分）
└────────┬────────┘
         │ 可选 HTTP
┌────────▼────────┐
│ enterprise-rag  │  知识 · ACL · 生成 · citations · mock inbox
└─────────────────┘
```

## 仍不可宣称

- ERP 派工调度、技师排班、实时 WMS 库存
- 企业生产统一认证（当前为演示 API Key 映射）
- 端到端替代售后系统
- Copilot 内 LLM / Multi-Agent 自主
- 「离开 RAG 本仓不完整」（已由 Standalone Scope 否定）
