# 项目边界

> 总入口：[OVERVIEW.md](OVERVIEW.md) · 自立范围：[STANDALONE_SCOPE.md](STANDALONE_SCOPE.md)

## 对外名称

**工程机械售后 · 报修开单门禁 Copilot**（LangGraph 门禁编排）  
EN: *After-Sales Ticket Gate Copilot*

> 对外统一「报修开单门禁」；不叫「派工系统」。`fault_dispatch` / 目录 `dispatch` = **仅内部技术名**。技师派工、排班在 **ERP**，本仓不做。

## 学生数据诚实口径（必背）

| 数据 | 是什么 | 不是什么 |
|------|--------|----------|
| `station_profile.json` | 演示站务结构（班组/覆盖半径/工地别名） | 经销商 CRM / 主机厂主数据 |
| `parts_ledger.json` | 剧本库存 + WMS 风格字段；可改 stock 反证门禁 | 生产 WMS |
| `scripts/mock_parts_wms.py` | 本地 HTTP 伪台账，证明 `HttpPartsLedger` 路径 | 三一/中联真接口 |
| Fixture 知识源 | 契约形 ask/draft 响应（`knowledge_port=fixture`） | Live 联调证据 / 向量检索 |
| SLA 截止戳 | `intake_ts + response_hours` | 实时计时中台 |
| HITL `return` | 退回补件终止（不改 draft） | 在线改单编辑器 |

**拿不到真台账不影响过初面**：面试官要的是边界清晰 + 门禁可证伪，不是偷生产库。

## 验收分层（必背 · 数字 SSOT）

| 层 | 含义 |
|----|------|
| **Standalone** | 无 `:8001`；Fixture + `file_outbox` + `standalone_scorecard` |
| pytest FakeRag（离线） | 编排 + POL；**≠ Live 验收** |
| Live / joint pack | **加分**；pack 须 `live_verified=true` |
| CI | 永远 FakeRag；`live-linkage.yml` 默认 `if: false` |

## 已实现（PoC）

| 能力 | 说明 |
|------|------|
| 意图分流 | 规则表（关键词 + 低置信 `POL-INTENT-01`），Copilot 侧无 LLM |
| 知识源端口 | Fixture（Standalone 一等公民）或 HTTP → enterprise-rag `:8001`（Live 加分） |
| 规则质检 | POL-* Policy-as-Code（`POLICY_CATALOG_VERSION`） |
| 配件预核 | 本地 JSON / 可选 mock WMS HTTP |
| 站长人确 | LangGraph interrupt；approve / reject / **return（退回补件）** |
| Decision Snapshot | HITL/批准行动快照（schema=`decision_certificate`；非防篡改中台） |
| 提交端口 | `SubmitDestination`：Standalone 默认 `file_outbox`；Live 常用 `rag_mock_inbox`；`idempotency_key=run_id`；**非 ERP** |
| 本仓 Outbox | `GET /outbox` · `source=copilot_hitl` · `is_production_ticket=false` |
| 治理评测 | `standalone_scorecard`（主）· `governance_scorecard` / joint（加分） |

## 未实现 / 明确不做

ERP/CRM 派工 · 真 WMS/SSO · Copilot 内 LLM / Multi-Agent · Redis 多 worker

## 运行模式

| 模式 | 配置 |
|------|------|
| **单仓自立（主）** | `copy .env.standalone .env` → `COPILOT_RUNTIME_MODE=standalone` · `DEMO_OFFLINE=1` · `SUBMIT_DESTINATION=file_outbox` |
| **答辩 Live（加分）** | `copy .env.demo .env` → `REQUIRE_LIVE=1` · `RAG_AUTO_FALLBACK=0` · 通常 `rag_mock_inbox` |
| **开发试错** | 可临时 `RAG_AUTO_FALLBACK=1`（**勿当** Live / Portfolio） |
| **伪 WMS（可选）** | `python scripts/mock_parts_wms.py` + `PARTS_LEDGER_URL=http://127.0.0.1:8011` |
