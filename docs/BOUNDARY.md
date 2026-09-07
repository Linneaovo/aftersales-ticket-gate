# 项目边界

总入口：[README.md](../README.md) · 单仓范围：[STANDALONE_SCOPE.md](STANDALONE_SCOPE.md)

## 名称

**工程机械售后 · 报修开单门禁 Copilot**（EN: *After-Sales Ticket Gate Copilot*）

对外不叫「派工系统」。代码里的 `fault_dispatch`、目录名 `dispatch` 仅内部标识；技师排班、派工在 ERP，本仓不做。

## 演示数据是什么

| 数据 | 实际含义 |
|------|----------|
| `station_profile.json` | 演示用站务结构（班组、覆盖半径、工地别名） |
| `parts_ledger.json` | 剧本库存；改 stock 可对照缺料门禁 |
| `scripts/mock_parts_wms.py` | 本地 HTTP 伪台账，验证 HTTP 台账路径 |
| Fixture 知识源 | 契约形状的 ask/draft 响应，不是向量检索 |
| SLA 截止时间 | `intake + response_hours`，不是实时计时服务 |
| HITL 退回 | 终止本单并提示补件，不是在线改单编辑器 |

## 已实现

| 能力 | 说明 |
|------|------|
| 意图分流 | 关键词规则；低置信可进人确 |
| 知识源 | 单仓用 Fixture；联调用 HTTP 调 `:8001` |
| 策略门禁 | 主路径五条 + 目录中其余策略（`GET /policies`） |
| 鉴权 | 写路径须显式 API Key |
| 配件预核 | 本地 JSON，可选 mock WMS |
| 站长确认 | 批准 / 拒绝 / 退回 |
| 决策快照 | 记录策略版本与确认项（字段名仍兼容 `decision_certificate`） |
| 落箱 | 单仓 `file_outbox`；联调常用 RAG mock inbox |
| 评测 | `standalone_scorecard` 为主；联合证据包为加分 |

## 未实现

ERP/CRM 派工 · 生产 WMS/SSO · 本仓内 LLM · 多 worker 生产部署（演示固定单 worker）

## 运行配置

| 模式 | 做法 |
|------|------|
| 单仓 | `copy .env.standalone .env` |
| 联调（真 RAG） | `copy .env.demo .env`，且 `:8001` 已就绪 |
| 开发兜底 | 可临时 `RAG_AUTO_FALLBACK=1`（勿当作联调通过） |
| 伪 WMS | `python scripts/mock_parts_wms.py`，配置 `PARTS_LEDGER_URL` |
