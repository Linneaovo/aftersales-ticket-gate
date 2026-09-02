# Changelog

## 0.2.20-demo (2026-09-01)

### 缺口①②：双仓协同说明 + L1 可复现联调

- **G1**：`docs/DUAL_REPO.md` 双仓说明；README / OVERVIEW 标明检索在 `enterprise-rag`；DEMO 片头含知识层
- **G2**：证据分层 L0/L1/L2（`app/eval/evidence_tier.py`）；`--from-artifacts` 永不可称 L2
- **L1**：`scripts/rag_contract_stub.py` + `docker-compose.joint.yml` + `run_l1_linkage` + `.github/workflows/linkage-l1.yml`
- 口径：L1 证 HTTP 契约与归属，不证检索；仅 L2 `live_verified=true`；`test_live_contract` = schema ≠ HTTP Live
- 文档入口更名：`INTERVIEW_ENTRY` → `OVERVIEW`，`PORTFOLIO_ENTRY` → `DUAL_REPO`

## 0.2.19-demo (2026-08-30)

### 评审落地（口径 / 演示）

- `__version__` 与 CHANGELOG 对齐为 **0.2.19-demo**
- UI：`ready_for_chief` 改对照路径说明；站长待办 caption 区分 P1 / P1b
- README / DEMO_SCRIPT：演示前 `reset_demo_state` + `preflight --standalone` SOP

### 学生向能力补强（不改门禁语义）

- 意图：弱口语词表/规则补强；held-out 全过；新增 `intent_failure_notes.md`
- 场景：扩展剧本 P9 浏阳渗油、P10 望城缺料；站/工地别名补浏阳/望城/宁乡
- UI：站长人设下 `waiting_hitl` 待办列表
- ENTRY：人工智能专业定位 + 三个可指认设计点
- DoD：本机 `demo_preflight --standalone` 通过

## 0.2.18-demo (2026-08-30)

### 文档与表达收敛（降 AI 套话，不改门禁语义）

- 计划/清单/口述草稿迁入 `docs/_internal/`；对外入口收束为 ENTRY / SCOPE / DEMO / FORWARD
- README、DEMO、UI、preflight 文案去掉「毕业/加分」等包装腔；评测说明改为普通工程口吻
- playbook/台账说明缩短并指向 `SYNTHETIC_DATA_PROVENANCE.md`；intent held-out 增补非 H103 样例

## 0.2.17-demo (2026-08-30)

### Standalone 硬化（W1–W5）

- **W1**：`start_standalone` 自动 preflight；CI 跑 HITL/intent/standalone scorecard；`/health.mode_warnings`；preflight 遇 warnings 失败；`checkpoint_exists` 兼容 MemorySaver
- **W2**：HITL goldset ≥25；阈值 recall≥0.92 / false≤0.08；scorecard 诚实 note + `false_hitl_cost_proxy`
- **W3**：intent held-out 挂入 standalone scorecard（required）；弱口语演示节拍
- **W4**：`docs/FORWARD_LOOKING.md`；命名收口（门禁台 vs 知识治理台）
- **W5**：UI/DEMO 首屏 ≥6min 自立路径；反证「Fixture≠MRR」

## 0.2.16-demo (2026-08-29)

### 单仓自立（Standalone First）

- **S0**：`STANDALONE_SCOPE` · POC/ENTRY/BOUNDARY/DUAL 双轨 DoD（Joint=加分）
- **S1–S2**：`runtime_mode` / `knowledge_port=fixture|http` · `GET /outbox` · `.env.standalone` · `start_standalone.cmd`
- **S3**：`build_governance_scorecard.py --profile standalone` → `standalone_scorecard.json`；`preflight --standalone`
- **S4–S5**：威胁模型补 Fixture/outbox；DEMO_SCRIPT Part A/B；UI 门禁台文案
- S4–S5 补缺：ARCHITECTURE 双端口、ORAL 自立 30 秒、Fixture 谱系、HITL→file_outbox e2e + `/outbox` API 测
- **pytest SSOT**：离线 **302** / 全量 **310**

## 0.2.15-demo (2026-08-29)

### B6 feedback 按 run_id 回读（advisory）

- Copilot：feedback result 补齐 `sources` + 显式 `run_id`；`list_feedback_by_run_id`
- RAG：`GET /feedback?run_id=`；持久化 `run_id`
- `scripts/check_feedback_roundtrip.py`；**不挡** `portfolio_claimable`
- **pytest SSOT**：离线 **293** / 全量 **301**

## 0.2.14-demo (2026-08-29)

### B4 / A4 / A5 收尾

- **B4**：`joint_failure_drill` v2 增 `retrieve_only_forces_hitl` / `low_grounding_no_silent_submit` / `probe_lane_isolation`；503 探针 `manual:true` 防假绿
- **A4**：`format_submit_error` 稳定字段；FileOutbox `list_tickets` + `scripts/list_file_outbox.py`；未批准 `submit_gate_blocked`
- **A5**：`validate_certificate`；威胁模型指针同步 acl_matrix / drill
- **pytest SSOT**：离线 **292** / 全量 **300**

## 0.2.13-demo (2026-08-29)

### B5 / B7 联仓硬化

- **B5**：`rag_eval_index` 正式读取 sibling `enterprise-rag/.../evaluation_baseline.json`（sample_count / headline / ACL 抽样 / 参数指纹）；`copilot_claims_mrr=false`，禁止综合分
- **B7**：`acl_matrix` L1/L2/短路三格；`synergy_checks.acl_l1_or_l2` 升格 **required**（F8）；`scripts/run_acl_matrix.py`
- **pytest SSOT**：离线 **288** / 全量 **296**

## 0.2.12-demo (2026-08-29)

### 验收说明

- W1a–W2（O1–O6）已在本版落地；RAG 仓另含 O7/O8（helpers 测量 + L2/L3 分层）
- 联调严档：`start_all` → RAG `start_demo`（demo_env 开 submit token）+ Copilot `.env.demo`

### W2 · O4/O5/O6 证据与主路径诚实

- **O4**：`/health` 仅在 `rag_mode=live` 且本轮探测成功时透出当场 `joint_evidence_live_verified`；否则清 false + `stale_vs_runtime`
- **O5**：`ENGINE_STRICT=1` 下 HITL 无 checkpoint → `failed`（`checkpoint_missing`），禁止默默 fallback
- **O6**：`build_joint_evidence_pack --live` 要求 RAG/Copilot 契约版本一致，否则不可 `live_verified`/`claimable`

### W1b · O2 submit 严档 + O3 契约热路径

- **O2**：联调 A档经 RAG `demo_env` 默认 `SUBMIT_REQUIRE_COPILOT_TOKEN=1`；`demo_preflight --require-rag` 检查门闩与双边 token；`start_all` 优先 `start_demo.cmd`
- **O3**：`CONTRACT_VALIDATE=strict`；`validate_ask` 要求 `grounded`；禁止 sources 推断 grounded=true；ask 契约失败 → `contract_gate_incomplete` + POL-DEGRADE；draft/submit 契约失败抛错
- 口径：demo token ≠ 企业鉴权；仅消除无 token 默认直写业务箱

## 0.2.11-demo (2026-08-29)

### 修订计划落地 · A / C.2

- **A**：`joint_evidence_pack` `--live` 再生；`check_pytest_ssot` + `test_live_pack_acceptance_layers_match_ssot` 防 pack↔ssot 再漂
- **C.2**：`demo_strict_submit.env.example` + `scripts/demo_strict_submit_check.py`（硬门开→一红一绿；未开则 SKIP）；`live_integration_manual.py --require-submit-token`
- **C.2 实测**：本机曾开闸验收 `all_ok=true`（红 403 / 探针 200 / 绿 approve→inbox），随后 `SUBMIT_REQUIRE_COPILOT_TOKEN=0` 恢复日常
- **pytest SSOT**：离线 **269** / 全量 **277**

## 0.2.10-demo (2026-08-29)

### Phase 6 · playbook 双次回放稳定性

- `app/eval/replay_stability.py`：证书/门禁稳定字段 fingerprint（不含 run_id）
- `tests/test_playbook_replay_stability.py`：FakeRag 对全部 playbook 各跑两次，断言 `policy_ids` / HITL layers / 证书关键字段一致
- **pytest SSOT**：离线 collect **261** / 全量 **269**

## 0.2.9-demo (2026-08-29)

### E4 L3 演示级 submit 硬门（默认关）

- **RAG**：`SUBMIT_REQUIRE_COPILOT_TOKEN` + `COPILOT_SUBMIT_TOKEN`；开启后业务路径须 `X-Copilot-Submit-Token`，`contract_probe` 除外；`/health` 暴露开关标志
- **Copilot**：`COPILOT_SUBMIT_TOKEN`（`.env.demo` 已配）；业务 submit 自动带 header
- **pytest SSOT**：离线 collect **251** / 全量 **259**

## 0.2.8-demo (2026-08-29)

### E4 L2 跨仓 inbox 归属 + 契约版本互证

- **E4 L2**：联调断言探针/业务 `source` 由 RAG 持久化；`live_integration_manual` / `joint_evidence_pack` 校验 `copilot_hitl`+`run_id`
- **契约互证**：`demo_preflight --require-rag|--contract` 比对 RAG `consumer_contract_version_supported` ↔ `CONTRACT_VERSION=2026-08-29.1`
- **文档**：`RAG_COPILOT_CONTRACT` / `DUAL_PROJECT_BOUNDARY` / `ENGINEERING_OPTIMIZATION` 同步 L2 ✅

## 0.2.7-demo (2026-08-29)

### E1–E6 工程优化（主路径抗漂移）

- **E1**：`check_parts` 强制清缓存；`/health` 台账指纹；`POST /admin/reload-ledger`；preflight 核对 sha256
- **E2**：`data/parts_live_allowlist.json` + `check_parts_live_align.py`；缺料+未知并存钉死 01+02；`--live` P1 须含 `POL-PARTS-01`
- **E3**：联调包 `parts_gate_ab.offline|live` 分栏；`parts_gate_ab_live_ok`；禁止 stub 冒充 Live
- **E4**：业务 submit 带 `submitted_by=copilot` / `source=copilot_hitl`；探针标 `contract_probe`
- **E5**：`CONTRACT_VERSION=2026-08-29.1`；health/preflight 可追溯
- **E6**：`GET /playbooks?lane=core|extended` 默认 core

## 0.2.6-demo (2026-08-29)

### G0–G2 联调证据与对外口径闭环

- **G0**：`--live` 证据包 `live_verified`/`portfolio_claimable`；重启 :8002 后 P1 回 `POL-PARTS-01`；`--from-artifacts` 强制 `claimable=false`
- **G1**：`live_rag_contract_check` / preflight `--contract`；`--live` 强制 `parts_gate_ab`；A-07=`compare_report` 离线；对外入口仅 OVERVIEW
- **G2**：对外统一「报修开单」；联调台主线 P1/P8/证书，班组·雨季·finance 进扩展；inbox 所有权固化；SSOT collect **242/250**

## 0.2.5-demo (2026-08-28)

### 面试官 P0/P1 硬伤修补

- **领域层 HITL**：`apply_hitl` 强制站长 Key（非仅 FastAPI）；单测覆盖非站长 PermissionError
- **缺料可解释**：台账 `_demo_note` + `ledger_kind`；P1=rag_draft / P1b=有货对照；force hints 剧本标注 demo_honesty
- **口语**：覆盖「星沙那边车子抬臂慢，客户催得紧」；低置信走 POL-INTENT-01 叙事
- **证据包**：`live_verified` / `portfolio_claimable`；artifacts-only 禁止当当场联调
- **mock 终点**：证书/API/UI 明确 `not_erp_dispatch` + `is_production_ticket=false`（非生产开单系统）
- **降噪**：天气 POL 默认关；证书 `assurance=state_snapshot_not_tamper_proof`；answer 词表仅无 draft 件时启用；ROLE_MATRIX 去掉话术 path_hint 膨胀

## 0.2.4-demo (2026-08-28)

### 优化清单落地（面试专业度 / 1+1>2）

- **文档入口**：`docs/OVERVIEW.md`；README/ORAL/DEMO/BOUNDARY/DUAL/PACKAGING/eval README 口径对齐
- **数字 SSOT**：离线 pytest collect≈214（`-m "not integration"`）；淘汰文档中 162/207 过时数字
- **叙事**：知识治理台 vs 开单联调台；主线 P1→P8→A-07；主推五条 POL；熔断/WEATHER/fallback 降级不进电梯稿
- **证据**：`scripts/build_joint_evidence_pack.py` → `joint_evidence_pack.json`；UI 展示 Decision Certificate
- **姊妹仓**：enterprise-rag `INTERVIEW_PITCH` 增加 1+1 交叉口径
- 明确不做：Copilot 内 LLM/Multi-Agent、真 ERP/WMS/SSO、Redis、默认 Rerank

## 0.2.3-demo (2026-08-28)

### 68 分清单落地

- 删 `gates.evaluate_submit_eligible` 未使用 `sla` 死变量；SLA 仅读 `service_ticket`
- `can_create_draft` ↔ `ROLE_MATRIX.can_draft` 单源（消矩阵双轨）
- 文档/口述测试条数 192/194 → collect≈207
- 真联调交叉口径：`rag_client_mode=live`，勿只甩 `rag_linkage`
- Streamlit 横幅瘦身；linkage 非 live 时降级为 warning

## 0.2.2-demo (2026-08-28)

### 80 分评审本轮（#8/#10/#11 + 口径）

- 删除 `ROLE_MATRIX.force_hitl_on_dispatch` 同义空转；唯一提交权=`can_submit_direct` ↔ `gates.can_submit`
- POL-ROLE-01 增量说清：非站长 `auto_submit` → HITL 强制人确（相对 can_submit）
- A-07 负例：`would_submit_without_hitl` 公式可非 0；非站长 auto_submit 不计误开单
- 口述/README/Streamlit：A-07「0=门禁统计非写死」；Portfolio 勿混贴 compare_report；标题强化联调台

## 0.2.1-demo (2026-08-28)

### 面试扣分点落地（P0/P1）

- 验收分层写死：pytest FakeRag ≠ Live；CI 不验 :8001；Live=`live_*.json`+`script_version`
- ORAL_SMOKE 去「派人上门」调度话术 → 报修开单；目录名 dispatch 标注历史路径
- Live 证据契约：`app/eval/live_contract.py`；条数/version 不一致 → `/health.live_eval_stale`
- mock 终点主动声明：`destination=rag_mock_inbox` · `is_production_ticket=false`
- 技术叙事纠偏：关键词 intent + 规则 critic；P1 固定 POL-PARTS-01
- 虚构热线 `000-DEMO-5600`；文档瘦身（INTERVIEW/ORAL/DEMO/BOUNDARY）
- `live-linkage.yml` 保持 `if: false`，注释明确「本机契约」
- 残留清理：`compare_report` 重生成、replay 电话同步、Streamlit 验收分层横幅、ARCHITECTURE 验收分层
- 工程诚实：A-07 `misdispatch_risk_copilot` 改计数（禁写死）；`parts_node` 不再覆盖 `master_data_authority`
- `ROLE_MATRIX` 角色字段接线 gates/HITL；`hints_source` 进 trace 且 public_view 保留

## 0.2.0-demo (2026-08-27)

### 修复

- `empty_state.intent` 默认空字符串，避免 supervisor 跳过 `classify_intent` 导致技师提单不进 HITL
- fault 路径：`quality` 单次 + draft 后 `quality_draft` 增量复检（P1-1）
- `api_key_fp` 指纹落库与 reload 恢复（P1-5）

### 演示与联调加固（P0）

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
