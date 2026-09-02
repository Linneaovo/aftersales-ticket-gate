# Plan B：RAG 不可用时的容灾演示

当 `:8001` 不可达或现场网络受限时，按以下顺序讲架构，**不必强行 live 联调**。

## 1. 架构白板（30 秒）

- **enterprise-rag**：知识与权限真相（ask / retrieve / draft / inbox）
- **Copilot**：Policy-as-Code 门禁编排（POL-*）+ 站长 HITL
- 生产路径：**langgraph**；fallback 仅 LangGraph 异常容灾

## 2. 健康检查叙事

```bash
curl http://127.0.0.1:8002/health
```

- `rag_mode=unreachable` + `RAG_AUTO_FALLBACK=0` → 诚实说明未静默假联调
- `engine_degraded=true` → 展示 UI 显眼降级条（fallback 路径）

## 3. Trace 回放（本机导出）

演示前在 live / standalone 环境跑 P1，导出 trace（产物默认 gitignore，不作仓内钉扎）：

```bash
python scripts/replay_trace.py --latest
# 或
curl http://127.0.0.1:8002/runs/{run_id}/trace > data/eval/plan_b_trace.json
```

Streamlit「导出 Trace JSON」或播放录屏，逐步讲解：supervisor → rag → quality → work_order → parts → hitl。

## 4. 离线回归证据

```bash
python -m pytest -q -m "not integration"
python scripts/smoke_with_rag.py --offline
```

说明：

- **离线用例**（`pytest -m "not integration"`，FakeRag；条数见 `app/eval/ssot.py`）验证 **LangGraph 编排与 POL 门禁**；全量 collect 含 integration 标记（CI 仍 FakeRag；Live integration 须 `.env.demo`）
- **Live 验收**以演示前手动脚本为准：`demo_preflight --require-rag --smoke-run`、`live_integration_manual.py`、`live_function_test.py`
- Portfolio：**仅** `python scripts/build_joint_evidence_pack.py --live` → `live_verified=true`  
  （`--from-artifacts` 仅历史摘要，Plan B 不可当当场联调）
- **勿混称「全绿」**：以 `data/eval/live_*.json` 内 `passed/total` 为准
- A-07：`compare_report.json` B01 = **离线对照**，非 Live 验收
