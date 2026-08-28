# 售后开单协同 Copilot · 架构说明

## 1. 系统定位

| 层 | 组件 | 职责 |
|---|---|---|
| 展示层 | Streamlit (:8502) | 人设切换、剧本、HITL 按钮、Trace 查看 |
| 行动层 | FastAPI + LangGraph (:8002) | 编排、Policy 门禁、质检、人确、mock 开单 |
| 知识层 | enterprise-rag (:8001) | 检索、ACL、工单 draft/submit/inbox、feedback |
| 推理 | Ollama（RAG 侧） | Copilot 不直连；通过 RAG `/health` 与 answer 降级标记感知 |

**Copilot 不做：** 向量库、文档入库、LLM 生成、生产 ERP 派工。  
**Copilot 做：** Supervisor–Worker 状态机、POL-* 门禁、冲突不作裁决、站长 HITL、配件 JSON 预核。

## 2. LangGraph 状态机

```text
START → supervisor ─┬→ rag ────────────────┐
                    ├→ quality ────────────┤
                    ├→ work_order ─────────┤→ supervisor → …
                    ├→ parts ──────────────┤
                    ├→ human_confirm(hitl) ──┘
                    └→ submit → END
```

- **主引擎：** `engine=langgraph`（与 `POST /runs` 一致）
- **容灾引擎：** `engine=fallback` — 仅当 LangGraph interrupt/checkpoint 异常时逐步执行；**不是默认路径**

## 3. CopilotState 核心字段

| 字段 | 含义 |
|---|---|
| `raw_input` / `intent` | 用户输入 / 规则分类结果 |
| `service_ticket` | 机型、故障码、站点、二次进站、SLA |
| `rag_result` | enterprise-rag `/ask` 响应 |
| `conflict_bundle` | 冲突束；`policy=no_arbitration` |
| `critic_report` | 质检结果；`force_hitl` |
| `parts_check` | 本地 JSON 台账预核 |
| `work_order_draft` / `work_order_submit` | RAG mock 工单 |
| `hitl` | 人确状态；`decision=approve|reject|edit` |
| `submit_eligible` | 提交门禁汇总 |
| `trace_events` | 节点级 trace |
| `engine` | langgraph / fallback |
| `execution_path` | langgraph / fallback（审计用，与 engine_degraded 同看） |
| `work_order_state` | intake / drafting / pending_chief / submitted |

状态图类型：**`StateGraph(CopilotState)`**（不可用裸 `dict`，否则 checkpoint 合并会丢字段）。

## 4. 持久化模型

| 存储 | 文件 | 内容 | 用途 |
|---|---|---|---|
| Run 快照 | `data/runs.db` | 完整/ slim 状态 JSON | API 查询、HITL 续跑前加载 |
| HITL checkpoint | `data/checkpoints.db` | LangGraph SqliteSaver | interrupt → resume |
| Trace | `data/traces/{run_id}.jsonl` | 节点事件流 | 回放、排障 |

**依赖关系：** HITL resume 需要 **runs.db 有 waiting_hitl 记录** 且 **checkpoints.db 有同 thread_id（=run_id）checkpoint**。  
**清理：** `python scripts/reset_demo_state.py` 三者一并清除。  
**cancel：** `POST /runs/{id}/cancel` 标记 cancelled 并删除对应 checkpoint 线程。

**persist_mode：** `slim`（默认）截断 RAG answer/sources、work_order_draft 长文本；`full` 保留完整 payload。api_key 落库一律 `__redacted__`，load 时按 role 还原 demo key。

## 11. 结构化日志

每个 graph 节点经 `_append_trace()` 同时写入 trace JSONL 与 stdout 结构化日志（`copilot.nodes`）：

`run_id=… node=… ok=… latency_ms=… policy_ids=…`

配置入口：`app/logging_config.py`，FastAPI startup 调用 `setup_logging()`。

## 12. 测试分层

| 层级 | 位置 | 引擎 | 说明 |
|---|---|---|---|
| Policy/节点 | `tests/test_core.py` | fallback（快速）+ langgraph 抽样 | 与 spotlight 对照 |
| LangGraph e2e | `tests/test_langgraph_e2e.py` | langgraph | interrupt/resume |
| 剧本规格 | `tests/test_playbooks.py` | langgraph（7 条） | 与 POST /runs 一致 |
| HTTP 契约 | `tests/test_api.py` | langgraph via API | TestClient + FakeRag |
| Live 冒烟 | `tests/test_integration_live.py` | langgraph | `@pytest.mark.integration`，CI 跳过 |
| 真连 RAG | `scripts/smoke_with_rag.py` | langgraph | 输出 `smoke_report.json` |

## 5. HITL interrupt / resume 时序

```text
1. POST /runs → graph.invoke → supervisor 判定 need_hitl
2. hitl_node → interrupt(payload) → status=waiting_hitl，写 runs.db + checkpoint
3. POST /runs/{id}/hitl (demo-chief) → load_run → Command(resume={decision, note})
4. graph 续跑 → supervisor → submit 或 end
```

## 6. 降级路径

| 条件 | 行为 |
|---|---|
| RAG `/health` degraded | `POL-DEGRADE-01`；禁 auto_submit；强制人确 |
| RAG HTTP 失败 | `status=failed` |
| LangGraph 异常 | runner 自动降级 fallback 并逐步执行 |
| Ollama 不可用 | RAG answer 含「仅检索/ollama 不可用」→ 质检 force_hitl |

## 7. 外部 RAG 接口（只读调用）

`/health` · `/knowledge-bases/{kb}/ask` · `retrieve` · `/work-orders/draft|submit|inbox` · `/feedback` · `/metrics`

## 8. 剧本规格

`data/playbooks/*.json` 为可执行规格，字段：

- `expect_status` / `expect_intent`
- `expect_trace_prefix` / `expect_hitl_reasons`

验证入口：

- 离线：`tests/test_playbooks.py`
- API：`POST /playbooks/{id}/validate`
- 真连 RAG：`scripts/smoke_with_rag.py` → `data/eval/smoke_report.json`

## 9. Policy-as-Code（答辩主线 5 条）

| ID | 场景 |
|---|---|
| **POL-ROLE-01** | 技师提单须站长人确 |
| **POL-CONFLICT-01** | 冲突并列不作裁决 |
| **POL-PARTS-01** | 缺料须人确调拨 |
| **POL-SLA-01/02** | 二次进站 / 紧急首响 |
| **POL-DEGRADE-01** | RAG 降级禁 auto_submit |

完整目录：`GET /policies` · `app/policy/rules_catalog.py`

## 10. ACL 双层分工（双项目联动）

| 层 | 负责方 | 示例 |
|---|---|---|
| **L1 Copilot 调度** | 关键词 intent（`acl_probe`） | 「薪酬系数」→ 直接 rejected |
| **L2 RAG 语料 ACL** | enterprise-rag `/ask` blocked | 返回 `block_reason=acl_denied` → POL-GROUND-02 |

答辩 P3：先展示 L1 拒绝；若问 RAG 侧，说明 L2 在 live 语料拦截。

## 11. 意图词表

外置配置：`data/intent_rules.json`  
加载：`app/domain/intent_rules.py`  
修改词表后无需改 Python 代码（重启进程生效）。
