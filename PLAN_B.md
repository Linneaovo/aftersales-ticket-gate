# Plan B：知识仓不可用时怎么演示

`:8001` 不可达或现场网络受限时，不必强行联调。

## 1. 先讲分工（约 30 秒）

- 知识仓：检索、权限、草稿、inbox
- 本仓：门禁与站长确认
- 默认编排走 LangGraph；fallback 只在异常时用

## 2. 看健康检查

```bash
curl http://127.0.0.1:8002/health
```

- `rag_mode=unreachable` 且未开自动兜底 → 说明没有静默假联调
- 若走了容灾路径，UI 应有降级提示

## 3. 回放一次成功 trace

事先在单仓或联调环境跑通 P1，再回放：

```bash
python scripts/replay_trace.py --latest
```

按节点说明：路由 → 知识 → 质检 → 草稿 → 配件 → 站长确认。

## 4. 离线回归

```bash
python -m pytest -q -m "not integration"
python scripts/smoke_with_rag.py --offline
```

单仓主路径仍可独立成立；联调失败不否定单仓完成度。
