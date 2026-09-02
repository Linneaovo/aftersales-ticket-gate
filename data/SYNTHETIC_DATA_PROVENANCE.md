# 合成数据说明

演示用主数据。数据来源与边界以本页为准；不表示已对接主机厂或经销商生产库。

| 数据 | 权威文件 | 消费者 | 是什么 | 不是什么 |
|------|----------|--------|--------|----------|
| 配件台账 | `data/parts_ledger.json` | `parts_ledger` / POL-PARTS-* | 门禁反证用库存 + WMS 风格字段 | 生产 WMS |
| Live 件号白名单 | `data/parts_live_allowlist.json`（**authority=copilot_data_parts_live_allowlist**） | `check_parts_live_align.py` · RAG `check_copilot_parts_allowlist.py` | H103 Live 推荐件单权威；RAG 只校验 | RAG 平行 allowlist / 生产订货系统 |
| 站务档案 | `data/station_profile.json` | `domain/station` | 站名/工地别名/班组演示 | CRM/排班中台 |
| 意图词表 | `data/intent_rules.json` | `classify_intent` | 可配置关键词分流 | 语义模型 |
| 演示 Key | `data/demo_keys.json` | `policy/gates` | 角色↔Key 白名单 | SSO/IdP |
| 剧本规格 | `data/playbooks/*.json` | playbook runner / tests | 可执行期望（status/HITL/POL） | 生产工单库 |
| 配件 answer 词 | `data/parts_answer_tokens.json` | hints（默认关） | answer 扫词可选源 | 默认主路径 |
| **Fixture 知识源** | `app/tools/rag_stub_base.py` · `demo_rag.py` | Standalone / CI | 契约形 ask/draft/conflicts/parts hints；`knowledge_port=fixture` | Live 联调证据 / 向量检索语料 |
| RAG 语料 | enterprise-rag demo-kb | HTTP `/ask` `/draft`（Joint） | ACL/冲突/手册件号语义 | 本仓不持有语料；非 Standalone 完形条件 |

### Fixture 谱系（Standalone）

| 输入 | 来源 | 门禁影响 |
|------|------|----------|
| `parts_hints` / playbook `parts_hints` | 剧本或 API（`ALLOW_DEMO_PARTS_HINTS`） | 驱动台账预核 → POL-PARTS-01/02 |
| Stub `conflicts` | 问句含冲突/质保等关键词时并列束 | POL-CONFLICT-01 |
| `grounded` / sources 形字段 | Stub 固定契约形 | 质检 / GROUND-*；与 Http 适配器同校验形状 |
| 落箱 | `SUBMIT_DESTINATION=file_outbox` | 批准后本仓 `data/outbox/{run_id}.json` |

**口径**：Fixture 证明门禁与编排可独立验收；不证明检索质量。检索质量认 RAG 仓金标（Joint 加分）。

**反证入口**：`data/eval/refutation_matrix.md` · `scripts/check_refutation_matrix.py` · 改 `parts_ledger` stock → 门禁翻转
