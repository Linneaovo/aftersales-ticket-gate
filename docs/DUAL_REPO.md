# 双仓 · 售后知识治理 × 报修开单门禁

> 两层职责、两仓协作。CI 可复现 HTTP 契约联调；真模型联调为本机 / 夜间可选证据。

| 层 | 本地目录（路径） | 建议 GitHub 名 | 产品名 | 一句话分工 | 入口 |
|----|------|--------|--------|------------|------|
| **知识层** | `enterprise-rag` | `aftersales-knowledge-copilot` | 售后知识治理 Copilot | 检索 / 生成 / citations / ACL / 冲突并列 | 姊妹仓 README · UI `:8501` · `POST /ask` |
| **行动层** | `aftersales-dispatch-copilot` | `aftersales-ticket-gate` | 报修开单门禁 Copilot | POL 门禁 / HITL / 配件反证 / Decision Snapshot / submit 归属 | [README](../README.md) · [OVERVIEW](OVERVIEW.md) · UI `:8502` |

单独克隆本仓只能验收门禁控制面；检索与生成在 `enterprise-rag`。勿将本仓单独表述为完整「AI 检索生成」系统。

## 为何拆两仓

| | 知识层 | 行动层 |
|--|--------|--------|
| 问的问题 | 知识是否可看、是否冲突、草稿是否有据 | 谁能开单、缺料/冲突是否必须人确 |
| 模型相关 | 向量检索、生成、citations、ACL、冲突**并列不仲裁** | — |
| 控制面 | — | Policy-as-Code、HITL、配件反证、Certificate |
| 红线 | 不代替站长批准 | 不在仓内做 LLM 自主开单 / Multi-Agent |

**检索可信 ≠ 允许开单。**

## 证据分层

| 层 | 是什么 | 可证明 | 谁跑 |
|----|--------|--------|------|
| **L0** | FakeRag + pytest | 编排门禁回归 | 默认 CI `ci.yml` |
| **L1** | Compose 契约 HTTP 桩 + Copilot | HTTP 契约、submit 归属、draft→HITL→inbox | 默认 CI `linkage-l1.yml` · `docker-compose.joint.yml` |
| **L2** | 真 enterprise-rag + 模型 | `live_verified=true` 本机 Live | self-hosted / `live-linkage.yml` dispatch / 本机 |

- L1 **不证明**检索质量；检索认 L2 / RAG 金标。  
- `--from-artifacts` / 快照 → `evidence_tier=artifacts`，不能当作 L2。  
- 字段约定：`app/eval/evidence_tier.py`

## 联调演示主路径（含知识层）

1. 知识仓 `/ask` 或 UI `:8501`：有据回答 + citations（或 L1 stub 的契约形 ask）  
2. Copilot draft → 缺料 **POL-PARTS-01** → 站长 HITL  
3. 批准 → inbox `source=copilot_hitl`  
4. 证据：Standalone scorecard + L1 artifact +（若有）L2 `live_verified`

## 复现 L1

```bash
docker compose -f docker-compose.joint.yml up --build -d
docker compose -f docker-compose.joint.yml exec api python scripts/reset_demo_state.py
docker compose -f docker-compose.joint.yml exec api python scripts/run_l1_linkage.py
# data/eval/l1_linkage_report.json → evidence_tier=L1 · l1_verified=true · live_verified=false
```

Windows：`run_l1_linkage.cmd`

## 模块划分（对外表述）

> **售后双仓（知识治理 × 开单门禁）**  
> 模块 A：`enterprise-rag`（售后知识治理 Copilot）— 检索 / 生成 / ACL / 冲突并列  
> 模块 B：`aftersales-dispatch-copilot`（报修开单门禁 Copilot）— POL 门禁 / HITL / 配件反证 / 提交归属  
> 证据：CI L1 HTTP 契约联调；（可选）本机 L2 `live_verified`

宜写成**一个系统的两层**，不宜拆成两个互不相关的项目条目。

## 文档索引

| 文档 | 用途 |
|------|------|
| [OVERVIEW.md](OVERVIEW.md) | 本仓说明 |
| [DUAL_PROJECT_BOUNDARY.md](DUAL_PROJECT_BOUNDARY.md) | 双仓边界表 |
| [../DEMO_SCRIPT.md](../DEMO_SCRIPT.md) | 演示步骤 |
| [../data/eval/README.md](../data/eval/README.md) | 评测产物 |
| [RAG_COPILOT_CONTRACT.md](RAG_COPILOT_CONTRACT.md) | HTTP 契约 |
| [\_internal/LIVE_RUNNER.md](_internal/LIVE_RUNNER.md) | 可选 L2 self-hosted |
