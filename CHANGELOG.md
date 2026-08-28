# Changelog

## 0.2.0-demo (2026-08-27)

### 修复

- `empty_state.intent` 默认空字符串，避免 supervisor 跳过 `classify_intent` 导致技师提单不进 HITL
- fault 路径：`quality` 单次 + draft 后 `quality_draft` 增量复检（P1-1）
- `api_key_fp` 指纹落库与 reload 恢复（P1-5）

### 面试/答辩加固（P0）

- 默认 `RAG_AUTO_FALLBACK=0`，`BLOCK_RUNS_WHEN_NOT_LIVE=1`（`.env.demo`）
- `POST /runs` 在 live 要求下 RAG 不可达返回 503，禁止静默 DemoRag
- 统一对外命名：开单协同 / 门禁编排（非 ERP 派工）
- 演示鉴权、mock 收件箱、配件台账口径文档化
- `docs/ORAL_SCRIPT.md` 口述稿 + `demo_preflight.py --require-rag`
- A-07 `baseline_http_only` 模式 + 报告 `baseline_intent_mode` 字段
- P5b 无 hints 缺料剧本 + `playbooks` linkage 校验
- `app/tools/eval_stub.py` 统一 eval/test RAG stub

### 可信度（P1）

- Supervisor 意图仅首次计算，HITL resume 不覆盖
- 持久化 health 可操作 repair 提示
- 冲突策略文档 `docs/CONFLICT_POLICIES.md`
- 双项目边界 `docs/DUAL_PROJECT_BOUNDARY.md`
- UI：A-07 / inbox 摘要表、配件台账来源标注、侧边栏 health 一行摘要
- `service_ticket.reporter_role` 叙事字段

### 工程 polish（P2）

- `__version__` → `0.2.0-demo`
- `/metrics` Prometheus 风格 counter（`run_total` / `hitl_wait_total`）
- 演示 Key 外置 `data/demo_keys.json`
- `PartsLedgerClient` 抽象 + `HttpPartsLedger` 占位（当前 `JsonLedger` 实现）

## 0.1.0

- 初始 LangGraph 开单协同 + enterprise-rag 联调
