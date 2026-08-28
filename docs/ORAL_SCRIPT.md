# 面试口述稿（30 秒 + 深挖应答）

> 包装清单见 [INTERVIEW_PACKAGING.md](INTERVIEW_PACKAGING.md)。RAG 字段契约见 [RAG_COPILOT_CONTRACT.md](RAG_COPILOT_CONTRACT.md)。

## 30 秒电梯词

「这是**长株潭工程机械售后开单协同 Copilot**（不是派工系统）：知识层是我本地 SY215 **enterprise-rag**（:8001），Copilot（:8002）用 **LangGraph Supervisor–Worker 状态机做门禁编排**——**规则质检**、缺料预核、冲突不作裁决、站长人确，批准后写入 **RAG mock 收件箱**。**不含 ERP 派工调度**，定位是演示级工业 PoC。」

## AI 分工（必背）

| 能力 | enterprise-rag | Copilot |
|------|----------------|---------|
| 向量检索 / 生成 | ✅ | HTTP 调用 |
| citations / conflicts | ✅ | 消费展示 |
| 意图 / 质检 / 门禁 | ❌ | ✅ **规则** + 状态机 |
| 站长 HITL | ❌ | ✅ interrupt |
| LLM inference | ✅ | ❌ |

## 高频追问标准答

**Q：是不是 Multi-Agent 自主派工？**  
A：不是。是 **deterministic Supervisor 路由 + Worker 节点**（rag/quality/parts/hitl/submit），Policy-as-Code 门禁，**不作派工调度**。

**Q：质检是不是 AI？**  
A：Copilot 侧是 **规则质检**（POL-GROUND/CONFLICT/DRAFT），消费 RAG 返回的 `grounded`/`conflicts`/`sources`；**不在 Copilot 里跑 LLM Critic**。

**Q：谁派给谁？**  
A：不做派工调度。做的是**开单前置协同**：检索→质检→草稿→配件预核→站长确认→mock 收件箱。

**Q：Copilot 用什么大模型？**  
A：Copilot 仓库**无 LLM**；生成在 RAG。Copilot 是 LangGraph + Policy-as-Code 规则。

**Q：提交成功是 ERP 单号吗？**  
A：否。是 RAG **mock 收件箱** 的 `ticket_id`，可 `GET /inbox` 回读证明联动。

**Q：库存准吗？**  
A：演示用**本地 JSON 台账** + 规则预核；生产接 WMS/ERP HTTP（接口已抽象）。

**Q：鉴权怎么做的？**  
A：演示 **API Key→角色** 映射；生产接 SSO claim→role 表（`ROLE_CLAIM_HEADER` 占位）。

**Q：RAG 挂了还能跑？**  
A：开发模式可 DemoRag fallback；**答辩必须 `.env.demo`**：`REQUIRE_LIVE=1`，RAG 不可达则 `POST /runs` **503**。可现场演示 fail→恢复。

**Q：A-07 对比什么意思？**  
A：裸链 `/ask→draft→submit` 无 HITL；Copilot 强制 `waiting_hitl` + POL 门禁。报告字段 `live_rag` 标明 offline/live，不混用。

**Q：为什么 quality 有 quality_draft？**  
A：RAG 后做一次检索质检；draft 字段就绪后做**增量 draft 复检**，避免重复进 quality 节点。

## 双项目 1+1>2（2 分钟）

治理在 Copilot，知识在 RAG。RAG 不给「能不能开单、谁批准」；Copilot 消费 RAG 的 grounded/conflicts 做**强制人确**，解决漏人确、误开单、冲突乱裁决。

## 不可宣称

ERP 派工、实时 WMS、企业生产 SSO、端到端替代售后系统、「Copilot 侧大模型推理」。
