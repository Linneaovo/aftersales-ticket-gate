# 角色 × 能力矩阵（演示 API Key）

> **对外口径**：演示 API Key 映射角色；生产接 SSO/ERP 账号 → `role` 映射表（`ROLE_CLAIM_HEADER` 占位）。

| 演示 Key | 角色 | 可 draft | 可 submit | 冲突明细 | 典型路径 |
|----------|------|----------|-----------|----------|----------|
| `demo-technician` | 技师 | ✅ | ❌（须站长） | 完整 | 检索→质检→草稿→配件→**人确** |
| `demo-parts` | 配件员 | ✅ | ❌ | **脱敏** | 同上，冲突只见摘要 |
| `demo-chief` | 站长 | ✅ | ✅ | 完整 | 可快路径提交（冲突/缺料仍可能人确） |
| `demo-finance` | 财务 | ❌ | ❌ | 完整 | 仅知识查阅 |
| `demo-key` | 通用 | ✅ | ❌ | 完整 | 同技师 |

配置外置：`data/demo_keys.json`（代码内保留 default fallback）。

API：`GET /roles/matrix` · `GET /roles/path?role=technician&intent=fault_dispatch`
