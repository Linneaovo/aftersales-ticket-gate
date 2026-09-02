# 迁移与后续（一页）

未实现的能力用替换点说明；不表示已经对接主机厂或上线 ERP。

## 问题与对应机制

| 常见问题 | 本仓做法 | 合成数据如何验证 |
|----------|----------|------------------|
| 自动乱开单 | POL + HITL + 证书 | 改库存 / 剧本对照门禁 |
| 把检索当放行 | 知识源与开单权分离 | Fixture 与 HTTP 同契约 |
| 冲突被模型拍板 | 不仲裁 + 站长确认 | 冲突场景并列展示 |
| 假联调 | 显式 runtime_mode | Live 失败 vs Standalone 明示 fixture |
| 策略难追溯 | 策略目录版本 + lock | 改核心策略须 bump |

## 若接到真实系统

| 能力 | 现状 | 替换点 | 尽量不动 |
|------|------|--------|----------|
| 落箱 | file_outbox / mock inbox | 新的 SubmitDestination | POL / HITL / 证书语义 |
| 库存 | JSON / mock HTTP | PartsLedger → WMS | 缺料触发形状 |
| 角色 | demo Key | IdP 角色声明 | 权限矩阵含义 |
| 知识 | Fixture / 外仓 | 任意契约知识源 | 门禁不读向量库 |

## 私有化示意（未实现）

```text
内网工位 → Copilot API
         → 可选本地知识库
         → IdP 签发角色
         → CRM/开单适配器（替换 SubmitDestination）
```

demo Key 不是 SSO；证书声明为状态快照，不是防篡改审计件。

## 命名建议

- 本仓：报修开单门禁编排  
- 知识仓：知识治理（避免再叫一个「开单 Copilot」）
