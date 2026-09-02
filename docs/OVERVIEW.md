# 项目说明

> 单独打开本仓只能验收**开单门禁控制面**；检索 / 生成在姊妹仓 **`enterprise-rag`**（售后知识治理 Copilot）。  
> 双仓说明：[DUAL_REPO.md](DUAL_REPO.md)。

> **名称**：工程机械售后 · 报修开单门禁 Copilot（EN: After-Sales Ticket Gate Copilot）  
> 本地目录 / 意图枚举里的 `dispatch` 为技术内部名；产品口径是「报修开单门禁」，不含 ERP 派工。  
> GitHub 建议仓库名：`aftersales-ticket-gate`。完成范围以 [STANDALONE_SCOPE.md](STANDALONE_SCOPE.md) 为准。

## 一句话说明

本仓库做售后报修开单前的门禁编排：规则意图、POL-* 策略、配件预核、站长确认（HITL）、决策快照（状态快照，非防篡改审计中台）。  
默认用 Fixture 知识源 + 本仓 `file_outbox` 即可跑通。  
不是 Multi-Agent 自主开单，也不是 ERP；`is_production_ticket=false`。

## 设计定位

重点是工业场景里 AI 落地的**控制与责任分配**（何时检索、何时拦单、何时必须人确），不是聊天生成或 Multi-Agent 自主决策。  
**知识仓已有**：向量检索、生成、citations、ACL、冲突并列。  
**本仓（控制面）**：POL、HITL、配件反证、Decision Snapshot。  
意图为可配置规则基线，可替换分类器而不改门禁契约（见 [intent_failure_notes.md](../data/eval/intent_failure_notes.md)）。

## 三个可指认设计点

1. **缺料门禁可反证**：改台账 stock，POL-PARTS 触发/不触发可对照（P1 / P1b）。  
2. **Standalone / L1 / L2 分离**：Fixture 可独立验收；L1 Compose 证契约；L2 才 `live_verified`。  
3. **冲突不仲裁 + 决策快照**：质保冲突并列给人确；Decision Snapshot 记录策略版本与确认层（`assurance=state_snapshot_not_tamper_proof`）。

## 联调时知识层同场

| 层 | 服务 | 作用 |
|----|------|------|
| 知识侧 | enterprise-rag `:8001` / UI `:8501`（或 L1 契约桩） | ACL、冲突并列、有据 draft / 契约形 ask |
| 开单门禁 | 本仓 `:8002` / UI `:8502` | 缺料门禁 → 确认 → 落箱 |

检索结果可信，不等于允许开单。L1/L2 失败不影响本仓 Standalone 是否完成。

## 建议演示顺序

| 路径 | 步骤 | 注意 |
|------|------|------|
| 联调主路径 | 知识仓 ask/draft → 门禁 HITL → inbox | 勿只演示 Streamlit 门禁单镜 |
| 本仓主路径 | 缺料场景 → HITL → outbox → 证书 | 不必展开检索公式 |
| L1 Compose | `run_l1_linkage` / CI artifact | 证契约，不证检索 |
| L2（若有） | `live_verified=true` 联合包 | 勿与 L1 混称 |

A-07 的对照报告是离线实验，不能当作 Live 联调证明。

## 验证怎么分层

| 层 | 含义 | 看哪里 |
|----|------|--------|
| Standalone | 不依赖 `:8001` | `standalone_scorecard` · `demo_preflight --standalone` |
| L0 pytest（FakeRag） | 离线编排回归，不是 HTTP 联调 | collect 见 `app/eval/ssot.py` |
| **L1** Compose 契约 | HTTP 契约 + 归属 | `l1_linkage_report.json` · `linkage-l1.yml` |
| **L2** Live / 联合包 | 真 RAG+模型 | 须 `evidence_tier=L2` 且 `live_verified=true` |
| CI | L0 + L1 默认绿；L2 workflow 默认关 | 无 runner 时勿强开 L2 |

`tests/test_live_contract.py`：只校验已入库 JSON schema，≠ 当场 HTTP Live。

## 主路径策略

`POL-ROLE-01` · `POL-CONFLICT-01` · `POL-PARTS-01` · `POL-SLA-01` · `POL-DEGRADE-01`  
版本写入 Decision Snapshot（`POLICY_CATALOG_VERSION`；schema 字段名仍为 `decision_certificate` 以兼容）。

## 范围边界（简）

- 使用：Fixture / file_outbox 或 mock inbox、JSON 台账、demo Key、关键词意图、Streamlit 联调台  
- 不做：ERP 派工、真 WMS/SSO、仓内 LLM、Multi-Agent 自主、把 L0/L1/快照说成 L2

## 文档

| 文档 | 说明 |
|------|------|
| [DUAL_REPO.md](DUAL_REPO.md) | 双仓协同说明 |
| [STANDALONE_SCOPE.md](STANDALONE_SCOPE.md) | 单仓完成范围 |
| [../DEMO_SCRIPT.md](../DEMO_SCRIPT.md) | 演示步骤 |
| [BOUNDARY.md](BOUNDARY.md) · [DUAL_PROJECT_BOUNDARY.md](DUAL_PROJECT_BOUNDARY.md) | 边界 |
| [FORWARD_LOOKING.md](FORWARD_LOOKING.md) | 迁移与后续 |
| [../data/eval/README.md](../data/eval/README.md) | 评测产物说明 |
| [../data/eval/intent_failure_notes.md](../data/eval/intent_failure_notes.md) | 意图失败分析 |
| [\_internal/](_internal/) | 内部备忘（计划/草稿），非对外说明 |
