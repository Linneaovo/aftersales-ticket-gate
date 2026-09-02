# 角色 × 能力矩阵（演示 API Key）

> **对外口径**：演示 API Key 映射角色；生产接 SSO/ERP 账号 → `role` 映射表（`ROLE_CLAIM_HEADER` 占位）。

| 演示 Key | 角色 | 可 draft | 可 submit（`can_submit_direct`） | 冲突明细 | 典型路径 |
|----------|------|----------|----------------------------------|----------|----------|
| `demo-technician` | 技师 | ✅ | ❌（须站长） | 完整 | 检索→质检→草稿→配件→**人确** |
| `demo-parts` | 配件员 | ✅ | ❌ | **脱敏** | 同上，冲突只见摘要 |
| `demo-chief` | 站长 | ✅ | ✅ | 完整 | 可快路径提交（冲突/缺料仍可能人确） |
| `demo-finance` | 财务 | ❌ | ❌ | 完整 | 仅知识查阅 |
| `demo-hr` | 人事 | ❌ | ❌ | **脱敏** | 仅知识查阅 |
| `demo-key` | 通用 | ✅ | ❌ | 完整 | 同技师 |

**唯一权限字段（与 gates 单源）**：`can_draft` ↔ `can_create_draft`；`can_submit_direct` ↔ `can_submit`。  
已删除与 `can_submit` 对偶空转的 `force_hitl_on_dispatch`。  
非站长 `auto_submit` → 节点层 POL-ROLE-01 强制人确（相对 can_submit 的增量拦截）。

配置外置：`data/demo_keys.json`（代码内保留 default fallback）。

API：`GET /roles/matrix` · `GET /roles/path?role=technician&intent=fault_dispatch`  
（`fault_dispatch` = 历史意图枚举名，口头说「报修开单」，非派工。）
