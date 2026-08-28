# 冲突与门禁策略对照表

> Copilot 侧 **Policy-as-Code**；RAG 侧产出 `conflicts` 束，Copilot **不作自动裁决**。

| 策略 ID | 行为 | 典型触发 | hard reject? |
|---------|------|----------|--------------|
| POL-CONFLICT-01 | `force_hitl` · 冲突并列展示 | RAG `conflicts` 非空 · `conflict_review` 意图 | 否 |
| POL-CONFLICT-02 | `force_hitl` · 单方裁决措辞检测 | 答案含「唯一正确」「必须按…」等 | 否 |
| POL-GROUND-01 | 开单/纯查询 hard reject；**冲突题** `force_hitl` | `grounded=false` / 无 sources | 冲突题否，其余是 |
| POL-GROUND-02 | hard reject | RAG `blocked`（ACL/注入/闲聊） | 是 |
| POL-ROLE-01 | `force_hitl` | 技师提报修单须站长人确 | 否 |
| POL-PARTS-01 | `force_hitl` | 配件台账 `shortage` | 否 |
| POL-SLA-01/02 | `force_hitl` | 二次进站 / 紧急 SLA | 否 |
| POL-DEGRADE-01 | `force_hitl` · 禁 auto_submit | RAG degraded | 否 |

## CONFLICT-01 vs CONFLICT-02

- **CONFLICT-01**：知识层返回多条并列口径（质保/制度冲突），UI 展示 `items` / `sources_pair`，等待站长判断。
- **CONFLICT-02**：生成结果出现「替用户裁决」措辞，质检 `force_hitl=True`，**不**进入 `rejected`（除非同时触发 POL-GROUND-02）。
- **GROUND-01 + 冲突题**：Live RAG 可能 `grounded=false`；冲突意图下改为 `force_hitl`，避免硬拒抢走站长人确。ACL/注入（GROUND-02）仍硬拒。

## 路由语义（`supervisor` → `_route_after_rag`）

- `critic.passed=False` 且非仅 `force_hitl` → `rejected`
- `force_hitl` + 冲突/缺料/角色 → `waiting_hitl`
- 站长 `approve` 后 → 可 `submit`（仍过 `evaluate_submit_eligible`）

## 回归

```bash
python scripts/smoke_with_rag.py --compare-live   # P2/P8 live
pytest tests/test_integration_live.py -m integration -k "p2 or p8"
```
