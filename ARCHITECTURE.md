# 架构说明

入口：[README.md](README.md) · 单仓范围：[docs/STANDALONE_SCOPE.md](docs/STANDALONE_SCOPE.md)

## 分层

| 层 | 组件 | 职责 |
|----|------|------|
| 展示 | Streamlit `:8502` | 人设、剧本、站长确认、Outbox / inbox、trace |
| 编排 | FastAPI + LangGraph `:8002` | 意图、质检、门禁、人确、落箱 |
| 知识源 | Fixture 或 `enterprise-rag` `:8001` | 单仓用契约形 Fixture；联调用 HTTP |
| 生成模型 | 仅在知识仓侧（如 Ollama） | 本仓不直连 |

主路径：意图 → 知识草稿 → 质检 → 配件预核 →（必要时）站长确认 → 决策快照 → 落箱。  
落箱终点：`file_outbox`（单仓）或 `rag_mock_inbox`（联调）。单据均为非生产单。

```text
Copilot
  Intent → Quality → Parts → HITL → Snapshot → SubmitDestination
                         ↑
                   KnowledgePort
              Fixture  或  HTTP(:8001)
```

`/health` 主要字段：`runtime_mode`、`knowledge_port`、`submit_destination`、`linkage_claim`、`persistence_ok`。  
写路径须带 API Key。`GET /playbooks` 只回角色提示，不回明文 key。

## 编排状态机

```text
START → router ─┬→ rag ────────────────┐
                ├→ quality ────────────┤
                ├→ work_order ─────────┤→ router → …
                ├→ parts ──────────────┤
                ├→ human_confirm ──────┘
                └→ submit → END
```

路由按规则决定下一节点（确定性规则路由），不是多智能体协商。  
默认引擎：`langgraph`。`fallback` 仅在 interrupt/checkpoint 异常时启用，不是日常路径。

## 状态字段（摘录）

| 字段 | 含义 |
|------|------|
| `raw_input` / `intent` | 输入 / 规则分类 |
| `service_ticket` | 机型、故障码、站点、SLA 等 |
| `rag_result` | 知识源回答 |
| `conflict_bundle` | 冲突束（并列、不裁决） |
| `parts_check` | 配件预核 |
| `work_order_draft` / `work_order_submit` | 草稿 / 落箱结果 |
| `hitl` | 人确决策 |
| `trace_events` | 节点级 trace |

类型：`StateGraph(CopilotState)`。

### 落箱

| 实现 | 配置 | 说明 |
|------|------|------|
| `FileOutboxDestination` | `file_outbox` | `data/outbox/{run_id}.json` · `GET /outbox` |
| `RagMockInboxDestination` | `rag_mock_inbox` | HTTP 写入 RAG mock inbox |

统一：`is_production_ticket=false`，`idempotency_key=run_id`，业务源 `source=copilot_hitl`。门禁未过不得落箱。

## 持久化

| 存储 | 用途 |
|------|------|
| `data/runs.db` | 运行快照 |
| `data/checkpoints.db` | 站长确认前后的续跑 |
| `data/traces/{run_id}.jsonl` | 回放 |
| `data/outbox/*.json` | 单仓落箱 |

续跑需要 runs 与 checkpoint 同 `run_id`。清理：`python scripts/reset_demo_state.py`。  
演示固定单 worker；未改存储前不要 `--workers 2+`。

## 站长确认时序

```text
1. POST /runs → 进入 waiting_hitl 并落 checkpoint
2. POST /runs/{id}/hitl（站长 Key）→ 续跑
3. 提交到 file_outbox 或 rag_mock_inbox → 结束
```

## 降级与联调

| 条件 | 行为 |
|------|------|
| 单仓 | 显式 Fixture，不要求 `:8001` |
| 联调且知识仓降级 | 收紧自动路径（POL-DEGRADE-01） |
| 联调且知识仓不可达 | 返回 503，不静默改用 Fixture |
| LangGraph 异常 | 默认失败；容灾须显式关闭严格模式 |

联调接口（知识仓）：`/health`、知识库 ask、retrieve、工单 draft/submit/inbox 等。契约见 [docs/RAG_COPILOT_CONTRACT.md](docs/RAG_COPILOT_CONTRACT.md)。

## 策略与意图

主路径五条：ROLE / CONFLICT / PARTS / SLA / DEGRADE。完整目录：`GET /policies`。  
意图词表：`data/intent_rules.json`（改后需重启进程）。

## 测试与验收

| 类型 | 位置 |
|------|------|
| 节点 / 策略 | `tests/test_core.py` 等 |
| 单仓模式 | `tests/test_standalone_mode.py` |
| 剧本 | `tests/test_playbooks.py` |
| HTTP | `tests/test_api.py`（FakeRag） |
| 集成 | `tests/test_integration_live.py`（CI 默认跳过） |
| 单仓 preflight | `demo_preflight.py --standalone` |
| 联调 | `scripts/live_*.py`、`build_joint_evidence_pack.py --live` |

Docker 单仓：

```bash
docker compose up --build -d
docker compose exec api python scripts/reset_demo_state.py
docker compose exec api python scripts/demo_preflight.py --standalone
```
