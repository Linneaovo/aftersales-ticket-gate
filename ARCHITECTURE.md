# 报修开单门禁 Copilot · 架构说明

## 1. 系统定位

| 层 | 组件 | 职责 |
|---|---|---|
| 展示层 | Streamlit (:8502) | 人设切换、剧本、HITL、本仓 Outbox /（可选）RAG inbox、Trace |
| 行动层 | FastAPI + LangGraph (:8002) | 编排、POL 门禁、质检、人确、SubmitDestination |
| 知识源端口 | Fixture **或** enterprise-rag (:8001) | Standalone=契约形 Fixture；Live=HTTP 检索/draft |
| 推理 | Ollama（仅 Http RAG 侧） | 本仓不直连 LLM |

**本仓不做：** 向量库、文档入库、本仓 LLM、生产 ERP 派工。  
**本仓做：** Supervisor–Worker、POL-*、冲突不作裁决、站长 HITL、配件预核、Decision Snapshot、可插拔落箱。  
**提交终点：** `file_outbox`（Standalone 默认）或 `rag_mock_inbox`（Joint 加分）· `is_production_ticket=false`。  
入口：[docs/OVERVIEW.md](docs/OVERVIEW.md) · 自立：[docs/STANDALONE_SCOPE.md](docs/STANDALONE_SCOPE.md)。

### 双端口（自立核心）

```text
┌─────────────────────────────────────────────┐
│  Copilot 产品面                               │
│  Intent → POL/Quality → Parts → HITL → Cert │
│            ↓                                  │
│  SubmitDestination                            │
│  • file_outbox（Standalone 主路径）            │
│  • rag_mock_inbox（Joint 加分）               │
└─────────────────────────────────────────────┘
         │ KnowledgePort
         ├─ Fixture（DEMO_OFFLINE / knowledge_port=fixture）
         └─ HttpRagAdapter（:8001 · Live 加分）
```

`/health` 暴露：`runtime_mode` · `knowledge_port` · `submit_destination` · `standalone_scorecard_ok` · `mode_warnings`（错配则 status degraded）。

### 验收分层

| 层 | 含义 |
|----|------|
| **Standalone** | 无 `:8001`；`standalone_scorecard` · `preflight --standalone` |
| pytest FakeRag/Fixture | 离线编排；collect 见 `app/eval/ssot.py`；**≠ Live** |
| Live / `joint_evidence_pack` | **加分**；须 `live_verified=true` |
| CI | 不验 :8001；`live-linkage.yml` 默认关 |

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
| `rag_result` | 知识源 `/ask` 形响应（Fixture 或 Http RAG） |
| `conflict_bundle` | 冲突束；`policy=no_arbitration` |
| `critic_report` | 质检结果；`force_hitl`（质检侧，≠ 角色矩阵） |
| `parts_check` | 本地 JSON 台账预核 |
| `work_order_draft` / `work_order_submit` | 草稿 / 落箱结果 |
| `hitl` | 人确；`decision=approve|reject|return` |
| `submit_eligible` | 提交门禁汇总 |
| `trace_events` | 节点级 trace |
| `engine` / `execution_path` | langgraph / fallback |
| `work_order_state` | intake / drafting / pending_chief / submitted |
| `rag_offline_mode` / public `knowledge_port` | fixture vs http |

状态图类型：**`StateGraph(CopilotState)`**。

### 提交端口（SubmitDestination）

| 实现 | 配置 `SUBMIT_DESTINATION` | 说明 |
|------|---------------------------|------|
| `FileOutboxDestination` | `file_outbox`（`.env.standalone`） | 本仓 `data/outbox/{run_id}.json`；`GET /outbox` |
| `RagMockInboxDestination` | `rag_mock_inbox`（`.env.demo`） | HTTP → RAG mock inbox |

统一字段：`is_production_ticket=false` · `idempotency_key=run_id` · `source=copilot_hitl`。门禁未通过不得调用 destination。

### 治理证据

| 产物 | 入口 |
|------|------|
| Standalone 范围 / DoD | `docs/STANDALONE_SCOPE.md` |
| Standalone Scorecard | `build_governance_scorecard.py --profile standalone` |
| Full / Joint Scorecard | `build_governance_scorecard.py`（默认 full） |
| 联合 synergy | `app/eval/synergy_checks.py`（加分 claimable） |
| 故障三幕 | `scripts/build_joint_failure_drill.py` |

## 4. 持久化模型

| 存储 | 文件 | 用途 |
|---|---|---|
| Run 快照 | `data/runs.db` | API / HITL 续跑前加载 |
| HITL checkpoint | `data/checkpoints.db` | interrupt → resume |
| Trace | `data/traces/{run_id}.jsonl` | 回放 |
| Outbox | `data/outbox/*.json` | Standalone 落箱；reset 一并清理 |

**HITL resume** 需要 runs.db + checkpoints.db 同 `run_id`。  
**清理：** `python scripts/reset_demo_state.py`（含 outbox）。

**persist_mode：** `slim`（默认）/ `full`。api_key 落库 `__redacted__`。

## 5. HITL interrupt / resume 时序

```text
1. POST /runs → graph.invoke → need_hitl
2. hitl_node → interrupt → waiting_hitl + checkpoint
3. POST /runs/{id}/hitl (demo-chief) → Command(resume=…)
4. supervisor → submit（file_outbox 或 rag_mock_inbox）→ end
```

## 6. 降级路径

| 条件 | 行为 |
|---|---|
| Standalone | 不要求 Live；显式 Fixture |
| RAG `/health` degraded（Live） | POL-DEGRADE-01；禁 auto_submit |
| Live 下 RAG 不可达 | 503（禁静默 Fixture） |
| LangGraph 异常 | ENGINE_STRICT 默认失败；容灾须显式关严格 |

## 7. 外部 RAG 接口（Live 可选）

`/health` · `/ask` · `retrieve` · `/work-orders/draft|submit|inbox` · `/feedback` · `/metrics`

## 8. 剧本规格

`data/playbooks/*.json`：`expect_status` / `expect_hitl_reasons` 等。  
离线：`tests/test_playbooks.py`；API：`POST /playbooks/{id}/validate`。

## 9. Policy-as-Code（主线 5 条）

POL-ROLE-01 · POL-CONFLICT-01 · POL-PARTS-01 · POL-SLA-01 · POL-DEGRADE-01  
完整目录：`GET /policies` · `app/policy/rules_catalog.py`

## 10. ACL 双层（联调时）

| 层 | 负责方 |
|---|---|
| L1 Copilot | 关键词 intent（acl_probe） |
| L2 RAG | `/ask` blocked → POL-GROUND-02 |

## 11. 意图词表

`data/intent_rules.json` · `app/domain/intent_rules.py`（重启生效）。

## 12. 结构化日志

每个 graph 节点经 `_append_trace()` 写入 trace JSONL 与 stdout（`copilot.nodes`）：

`run_id=… node=… ok=… latency_ms=… policy_ids=…`

配置：`app/logging_config.py`。

## 13. 测试分层

| 层级 | 位置 | 说明 |
|---|---|---|
| Policy/节点 | `tests/test_core.py` | fallback + 抽样 |
| Standalone | `tests/test_standalone_mode.py` | Fixture + file_outbox · HITL→outbox |
| LangGraph e2e | `tests/test_langgraph_e2e.py` | interrupt/resume |
| 剧本 | `tests/test_playbooks.py` | 与 POST /runs 一致 |
| HTTP | `tests/test_api.py` | TestClient + FakeRag |
| Live | `tests/test_integration_live.py` | `@pytest.mark.integration`，CI 跳过 |
| Standalone 验收 | `demo_preflight.py --standalone` | 无 :8001 |
| Live 验收 | `scripts/live_*.py` | 加分；本机 :8001+:8002 |

## 14. 部署与并发约束（生产化前必读）

| 约束 | 现状 | 生产化方向 |
|------|------|------------|
| **Uvicorn worker** | 演示/答辩 **单 worker**（`--workers 1`） | 多 worker 须 Postgres/Redis checkpointer + 共享 runs 存储 |
| **SQLite** | `runs.db` + `checkpoints.db` 本机文件 | 并发写会锁竞争；Docker 用 named volume 持久化 |
| **HITL resume** | 同 `run_id` 的 runs 快照 + LangGraph checkpoint 成对 | 丢 checkpoint → `ENGINE_STRICT=1` 下 failed |
| **Docker** | `docker-compose.yml` Standalone 双服务 | 不含 RAG；联调仍本机 `.env.demo` + :8001 |

```bash
docker compose up --build -d
docker compose exec api python scripts/reset_demo_state.py
docker compose exec api python scripts/demo_preflight.py --standalone
```

**禁止**在未改 checkpointer 的情况下 `--workers 2+`：SQLite checkpoint 与内存 graph 缓存非跨进程安全。
