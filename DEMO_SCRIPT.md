# 演示路径（约 6～8 分钟）

双仓说明：[docs/DUAL_REPO.md](docs/DUAL_REPO.md)（片头需含知识层）  
本仓说明：[docs/OVERVIEW.md](docs/OVERVIEW.md) · 范围：[docs/STANDALONE_SCOPE.md](docs/STANDALONE_SCOPE.md)

开单门禁编排，不替代 ERP 派工。Standalone 落本仓 outbox；L1/L2 联调可落 RAG mock inbox。

> **片头**：3 分钟内应出现知识仓 UI / `/ask` 证据，或说明「本段仅 L1 契约桩 ask」。避免只有 Copilot 门禁单镜。

## Part 0 · 联调片头（≤90s · 含知识层）

| 步骤 | 内容 |
|------|------|
| 分工一句 | 知识层负责检索/生成；本仓负责开单门禁（检索可信 ≠ 允许开单） |
| ask | 真 RAG `:8501` **或** L1 stub `POST /ask` 契约形回答 |
| 门禁 | Copilot 缺料 → HITL → inbox `source=copilot_hitl` |
| 证据分层 | 出示 L1 artifact /（若有）L2 `live_verified` — 口播勿混层 |

## Part A · 单仓（主 · 约 6 分钟 · 无 :8001）

```bash
copy .env.standalone .env
start_standalone.cmd
# 已含 reset；若长跑后 persistence 脏：python scripts\reset_demo_state.py && python scripts\demo_preflight.py --standalone
```

| 步骤 | 内容 | 时长 |
|------|------|------|
| health | `runtime_mode=standalone` · 顶栏「单仓演示」· **当前状态条**可读 | 40s |
| P1 | 侧栏「跑主线剧本」或缺料问句 →「提交报修」→ 状态条变「待站长确认」 | 2min |
| 批准 | 人设切站长 → 勾选确认层 → 批准 → Outbox | 1.5min |
| 弱口语（可选） | 故意含糊一句，看低置信或人确 | 30s |
| P9/P10（可选） | 非 H103：浏阳渗油 / 望城缺料 | 1min |
| P8（可选） | 冲突脱敏 | 1min |

## Part B · L1 契约联调（默认可复现 · ≤2 分钟 · 无 GPU）

```bash
run_l1_linkage.cmd
# 或：docker compose -f docker-compose.joint.yml up --build -d
#     docker compose -f docker-compose.joint.yml exec api python scripts/run_l1_linkage.py
```

看 `data/eval/l1_linkage_report.json`：`evidence_tier=L1` · `l1_verified=true` · **`live_verified=false`**。  
口播：**CI 证明 HTTP 契约与提交归属，不证明检索质量。**

## Part C · L2 真模型联调（可选加分 · ≤2 分钟）

| 台 | 讲 | 不讲 |
|----|----|------|
| RAG `:8501` | ACL、冲突并列、有据 draft | 站长 HITL、缺料台账、证书 |
| Copilot | 门禁批准 → mock inbox | 检索公式、金标 MRR |

```bash
copy .env.demo .env
python scripts\demo_preflight.py --require-rag --smoke-run --contract
python scripts\build_joint_evidence_pack.py --live
```

确认联合包 `evidence_tier=L2` 且 `live_verified=true`。  
联调失败不否定 Part A。不要把离线 `compare_report` 或 L1 报告当 L2。

假联调彩排：`python scripts\rehearse_rag_failure.py`  
说明：开发可开 fallback；Live 锁 `RAG_AUTO_FALLBACK=0`；单仓用显式 Standalone。

---

## 细节提示

- P1：draft 推荐泵且 stock=0 → **POL-PARTS-01** → **站长待办** → 批准 → Outbox（主路径）
- P1b：有库存对照 → `ready_for_chief`、**不**进站长待办、**不落箱**；勿当主演示终点
- 批准后：Standalone 看 `GET /outbox`；联调看 inbox；均为非生产单
- P8：冲突不仲裁；配件角色可见脱敏
- A-07：裸链漏人确 vs Copilot 强制人确（口头说明即可）
