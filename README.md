# 长株潭工程机械售后开单协同 Copilot（LangGraph 门禁编排）

**对外口径：开单协同 / 门禁编排** — 知识层 enterprise-rag · 行动层工单编排/质检/人确/mock 收件箱；**不含 ERP 派工调度，仅开单前置协同**。

知识层：enterprise-rag `:8001`（SY215 售后助手）  
行动层：本仓库 LangGraph Supervisor‑Worker（冲突不作裁决 · 站长人确 · mock 开单）

技术栈：**LangGraph 状态机 + Policy-as-Code 规则门禁**；生成与检索在 enterprise-rag（Ollama/向量库）。Copilot 仓库内无独立 LLM inference（除调 RAG HTTP）。

详细设计见 [ARCHITECTURE.md](ARCHITECTURE.md)。**面试边界一页纸**见 [docs/BOUNDARY.md](docs/BOUNDARY.md)。演示词见 [DEMO_SCRIPT.md](DEMO_SCRIPT.md)。双项目边界见 [docs/DUAL_PROJECT_BOUNDARY.md](docs/DUAL_PROJECT_BOUNDARY.md)。

## 定位（Policy-as-Code，非 Autonomous Agent）

- **不是**「让 LLM 自主派工」——而是 **POL-* 可版本化门禁** + 确定性 Supervisor 路由
- RAG 提供知识与 citations；Copilot 负责质检、缺料预核、冲突不作裁决、站长 HITL
- 生产路径仅 **langgraph**；fallback 仅 LangGraph 异常容灾（UI 显眼 `engine_degraded`）

## 快速开始

### 一键启动（推荐）

```text
start_all.cmd          → RAG :8001 + Copilot :8002 + UI :8502
```

> **演示/答辩必做**：`copy .env.demo .env`（锁 live 联调，禁止静默 DemoRag）。  
> 日常开发可用 `.env.example`（允许 `RAG_AUTO_FALLBACK=1`）。

### 答辩前 5 分钟

```text
copy .env.demo .env
python scripts\reset_demo_state.py
python scripts\demo_preflight.py --require-rag --smoke-run
curl http://127.0.0.1:8002/health   # rag_mode=live
python scripts\smoke_with_rag.py --compare-live
```

口述稿见 [docs/ORAL_SCRIPT.md](docs/ORAL_SCRIPT.md)。

### 分步启动

```text
1. 启动 enterprise-rag :8001（DEMO_MODE=1，demo-kb）
2. copy .env.demo .env   → 答辩模式（RAG_AUTO_FALLBACK=0）
3. start_copilot.cmd → :8002
4. start_ui.cmd → :8502
5. python scripts\reset_demo_state.py && curl http://127.0.0.1:8002/health
6. 真连冒烟：python scripts\smoke_with_rag.py --compare-live
```

```bash
.\.venv\Scripts\python.exe -m pytest -q
```

OpenAPI：http://127.0.0.1:8002/docs

## P1 业务背景（星沙 H103）

> 3 月 12 日星沙站客户来电：SY215C 动臂抬升缓慢，故障码 H103。技师张伟提单后，系统走检索→质检→配件预核→站长刘波人确；冲突口径并列展示、不作裁决。

## 执行引擎

| 引擎 | 说明 |
|---|---|
| **langgraph** | 默认；与 `POST /runs` 一致；SqliteSaver 支持 HITL interrupt/resume |
| **fallback** | 容灾；LangGraph 异常时逐步执行，**非默认路径** |

## 持久化

| 文件 | 用途 |
|---|---|
| `data/runs.db` | Run 快照 |
| `data/checkpoints.db` | LangGraph HITL checkpoint |
| `data/traces/*.jsonl` | 节点 trace |

答辩前：`python scripts\reset_demo_state.py` + `python scripts\demo_preflight.py` + `GET /persistence/audit`

### 双项目联动检查表

```text
curl http://127.0.0.1:8001/health          → RAG ok
curl http://127.0.0.1:8002/health          → rag_mode=live, demo_mode_warning=false
POST /runs (P1) → rag_linkage 含 ask+retrieve+draft
POST /hitl approve → POST /inbox 有 ticket
```

## 答辩 POL 主线（只讲 5 条）

POL-ROLE-01 · POL-CONFLICT-01 · POL-PARTS-01 · POL-SLA-01 · POL-DEGRADE-01（其余说扩展预留）

## 复用 RAG 接口

契约文档：[docs/RAG_RESPONSE_SCHEMA.md](docs/RAG_RESPONSE_SCHEMA.md)

`/health` · `/ask` · `/retrieve` · `/work-orders/draft|submit|inbox` · `/feedback`

## 差异点

- `conflict_bundle.policy=no_arbitration` + 站长 Key 人确  
- `service_ticket` / SLA / 二次进站门禁（POL-*）  
- 配件预核结构化：`shortage` + `suggested_action`（如「建议：经开调拨」）  
- 站点 alias 外置：`data/station_profile.json`  
- A-07：`POST /eval/compare?engine=langgraph` 漏人确/误开单 delta  
- API 脱敏：`GET /runs/{id}?view=public`  
- 提交后 feedback + RAG 收件箱回读  

### A-07 示例（compare_report.json · B01）

单工具链对「SY215C H103请报修处理」会 `would_submit_without_hitl=true`；Copilot 强制 `waiting_hitl` + `POL-ROLE-01`。详见 `data/eval/compare_report.json`。

## 剧本

P1 星沙 H103 · P2 冲突 · P3 越权 · P4 纯查询 · P5 缺料 · P6 闲聊 · P7 二次进站 · **P8 配件员冲突脱敏**

## 测试

- **145** 单元/集成（CI 离线 **145** + integration **6**；`pytest -q -m "not integration"` + FakeRag）
- **manual/nightly**：`scripts/smoke_with_rag.py --compare-live` → `data/eval/smoke_report.json`
- **offline baseline**：`scripts/smoke_with_rag.py --offline`（已提交样例 report，live 答辩前 regenerate）
- Live integration（可选）：`pytest -m integration`

对外可说：**离线回归 + 真连冒烟** 双层验证。

## 局限

演示 API Key；mock 收件箱（非 ERP 调度）；配件 JSON 台账；Policy 工作流引擎（非 Autonomous Agent）。
