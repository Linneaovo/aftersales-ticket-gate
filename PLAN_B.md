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

## 3. Trace 回放（预录）

演示前在 live 环境跑 P1，导出 trace：

```bash
curl http://127.0.0.1:8002/runs/{run_id}/trace > data/eval/plan_b_trace.json
```

或直接打开已提交的 **`data/eval/plan_b_trace.json`**（P1 预录）。

Streamlit「导出 Trace JSON」或播放录屏，逐步讲解：supervisor → rag → quality → work_order → parts → hitl。

## 4. 离线回归证据

```bash
python -m pytest -q -m "not integration"
```

说明：**142 用例（离线 136 + integration 6）全绿** + **manual smoke_with_rag**（见 `data/eval/smoke_report.json`）= 离线 + 真连双层验证。

预录 trace：`data/eval/plan_b_trace.json`（P1 星沙 H103，RAG 挂也能讲架构）。

## 5. A-07 指标（有图有真相）

打开 `data/eval/compare_report.json`，贴 **B01** case：单工具链 would_submit vs Copilot waiting_hitl。
