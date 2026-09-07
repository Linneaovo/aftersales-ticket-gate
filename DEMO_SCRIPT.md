# 演示路径（约 6～8 分钟）

双仓说明：[docs/DUAL_REPO.md](docs/DUAL_REPO.md) · 单仓范围：[docs/STANDALONE_SCOPE.md](docs/STANDALONE_SCOPE.md)

本仓演示开单门禁，不替代 ERP 派工。单仓落本仓 Outbox；联调可落 RAG mock inbox。

开场按路径选一句即可：

- **A 单仓**：本段用 Fixture，知识层在姊妹仓。
- **B L1**：出示契约桩回答，说明只验证接口与提交归属。
- **C L2**：出示真知识仓 UI / 回答，并确认联合包 `live_verified=true`。

不要把 A/B 说成真模型联调；也不要只演示本仓门禁却暗示已联调真 RAG。

## 联调开场（路径 B/C · ≤90 秒）

| 步骤 | 内容 |
|------|------|
| 分工 | 知识仓做检索与生成；本仓做开单门禁 |
| 知识侧 | 真 RAG `:8501`（C）或 L1 桩上的契约形回答（B） |
| 门禁 | 缺料 → 站长确认 → inbox（`source=copilot_hitl`） |
| 证据 | L1 报告 /（若有）L2 `live_verified`，分层说清 |

路径 A 跳过本节，直接进入单仓主路径。

## 单仓主路径（约 6 分钟 · 无 `:8001`）

```bash
copy .env.standalone .env
start_standalone.cmd
```

| 步骤 | 内容 | 约时 |
|------|------|------|
| 健康检查 | `runtime_mode=standalone` · `linkage_claim=none` · 顶栏「单仓演示」 | 40s |
| 缺料 | 侧栏跑缺料示例或提交缺料问句 → 「待站长确认」 | 2min |
| 批准 | 切站长 → 勾选确认 → 批准 → Outbox | 1.5min |
| 可选 | 含糊口语 / 浏阳渗油 / 望城缺料 / 冲突脱敏 | 1–2min |

长跑后若 persistence 异常：`python scripts\reset_demo_state.py` 后再 preflight。

## L1 契约联调（≤2 分钟 · 无 GPU）

```bash
run_l1_linkage.cmd
```

看 `data/eval/l1_linkage_report.json`：`l1_verified=true`，`live_verified=false`。  
说明：CI/Compose 证明接口与提交归属，不证明检索质量。`rag_mode=live` 只表示 HTTP 可达。

## L2 真模型联调（可选 · ≤2 分钟）

| 仓 | 讲 | 不讲 |
|----|----|------|
| RAG `:8501` | 权限、冲突并列、有据草稿 | 站长确认、缺料台账 |
| Copilot | 门禁批准 → mock inbox | 检索公式、金标分数 |

```bash
copy .env.demo .env
python scripts\demo_preflight.py --require-rag --smoke-run --contract
python scripts\build_joint_evidence_pack.py --live
```

确认联合包 `evidence_tier=L2` 且 `live_verified=true`。真 RAG 下 `/health.linkage_claim` 常见为 `http_live`，不要把它当成 L2 标签。联调失败不否定单仓主路径。

## 细节

- P1：推荐件库存为 0 → 缺料确认 → 批准 → Outbox / inbox（主路径）
- P1b：有库存对照，不进站长待办、不落箱，不要当主演示终点
- 调用须带 API Key；单据均为非生产单
- P8：冲突并列、配件角色可见脱敏
