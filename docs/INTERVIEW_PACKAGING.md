# 面试包装清单（长沙集成商 / 甲方技术面）

## 必须使用的对外名称

- ✅ **售后开单协同 Copilot** / **门禁编排**
- ❌ AI 派工系统 / 智能调度 / 替代 ERP

## 必须说清的三件事

1. **Supervisor–Worker 状态机**（LangGraph），不是「自主 Multi-Agent」
2. **规则质检**（Policy-as-Code + RAG grounding 字段），不是 Copilot 内 LLM Critic
3. **mock 收件箱**（RAG submit），不是 ERP 工单号

## 必须 Live 演示的证据

- `GET /health` → `rag_mode=live`
- `rag_linkage`: ask → draft/submit → feedback
- P1 缺料 HITL + P2 冲突不作裁决 + P4 纯查询 succeeded
- 1 条剧本外口语：`POST /runs`（见 `ORAL_SMOKE_QUESTIONS` 末条）

## 主动承认的局限（抢答）

| 局限 | 一句话 |
|------|--------|
| 不做派工 | dispatch_status=not_in_scope，调度在 ERP |
| 配件库存 | 演示 JSON；生产 `HttpPartsLedger` |
| 意图分流 | Copilot 侧关键词规则；语义在 RAG ask |
| 离线测试 | FakeRag 回归；答辩以 Live 脚本为准 |

## 禁止宣称

ERP 派工、实时 WMS、企业生产 SSO、Copilot 侧大模型推理、「统一向量中台」（仅为 HTTP 编排分工）。

## 优化清单落地状态（答辩前自检）

| 项 | 状态 |
|----|------|
| 口播「开单协同」非派工 | ✅ `ORAL_SCRIPT.md` / README |
| finance 内联工单 POL-ROLE-02 | ✅ `nodes.py` + `test_finance_rejects_inline_rag_work_order` |
| P4 无 draft 校验 | ✅ `expect_no_work_order_draft` + runner |
| 18 条长沙口语 intent | ✅ `ORAL_SMOKE_QUESTIONS` + `test_intent_oral.py` |
| GET /runs 鉴权 | ✅ `main.py` + `test_read_runs_rejects_unknown_key_when_required` |
| Live P2/P4/口语脚本 | ✅ `live_integration_manual.py` / `live_function_test.py` |
| RAG 字段契约 | ✅ `RAG_COPILOT_CONTRACT.md` |
| trace 回放（120s 备用） | ✅ `scripts/replay_trace.py` |
| Live 证据 JSON | 跑通后见 `data/eval/live_*.json` |
