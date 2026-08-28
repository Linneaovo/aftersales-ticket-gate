# 项目边界（面试一页纸）

## 对外名称

**长株潭工程机械售后开单协同 Copilot**（LangGraph 门禁编排）

> 不叫「派工系统」。技师派工、排班、路线规划在 **ERP**，本仓库不做。

## 已实现（PoC 范围）

| 能力 | 说明 |
|------|------|
| 意图分流 | 规则表（`data/intent_rules.json`），Copilot 侧无 LLM |
| 知识检索 | HTTP 调 enterprise-rag `:8001`（ask + retrieve） |
| 规则质检 | POL-GROUND / POL-CONFLICT / POL-DRAFT 等 |
| 工单草稿 | RAG `/work-orders/draft` 或 ask 内联 |
| 配件预核 | 本地 JSON 台账（可扩展 WMS HTTP） |
| 站长人确 | LangGraph interrupt + SQLite checkpoint |
| Mock 提交 | RAG `/work-orders/submit` → **mock 收件箱**（非 ERP 工单号） |
| 反馈闭环 | submit 后 `/feedback` 回写 RAG |

## 未实现（虚线框）

- ERP / CRM **派工调度**、技师排班、GPS、技能矩阵
- 实时 WMS / 生产库存
- 企业生产 SSO（演示为 demo API Key）
- Copilot 侧大模型推理（生成在 RAG 项目内）

## 双项目分工

```
enterprise-rag :8001  →  向量库、LLM、 citations、draft API、mock inbox
Copilot :8002         →  门禁编排、HITL、配件预核、trace、POL-*
```

## 运行模式（口述必区分）

| 模式 | 配置 | 说明 |
|------|------|------|
| **答辩 live** | `copy .env.demo .env` | 强制真连 :8001，`rag_client_mode=live` |
| **开发/CI** | `.env.example` + `RAG_AUTO_FALLBACK=1` | DemoRag 替身，可重复回归 |

## 技师 vs 站长（真实分工）

- **技师**：低危单可 `succeeded` + 草稿就绪（`work_order_state=ready_for_chief`），**不阻塞一线**
- **须站长 HITL**：缺料、冲突、二次进站、紧急 SLA、RAG 降级、**站名未识别**
- **须站长 Key 提交**：mock 收件箱 / 未来 ERP 接收入口

## 站名规则

- 从问句 alias 或 API `station` 字段解析
- **识别不到不默认星沙**，标空并触发 `POL-STATION-01` 人确
