# 威胁模型（轻量）

> 演示 Key ≠ SSO。每行指向已有缓解与测试。

| 威胁 | 缓解 | 测试 / 证据 |
|------|------|-------------|
| 未知 API Key | `require_known_api_key` | `tests/test_api.py` 401 |
| 非站长 HITL / 直提 | chief key + `can_submit_direct` | `tests/test_role_pierce.py` |
| 直打 RAG submit 绕过 | `source=contract_probe` / submit token | `demo_strict_submit_*` · E4 · drill `probe_lane_isolation` |
| 注入 / 越权话术 | L1 intent + L2 RAG ACL | `acl_matrix` · P3 · `intent_cases` |
| 静默假联调 | `RAG_AUTO_FALLBACK=0` · Live 禁 Fixture | `joint_failure_drill`；`runtime_mode=live` |
| Fixture 冒充 Live | `COPILOT_RUNTIME_MODE` / `/health.knowledge_port` | Standalone 明示 `fixture`；Live `demo_mode_warning` |
| 直写 file_outbox 绕过 HITL | submit_node 门禁未过不调 destination | `test_submit_node_skips_destination_when_not_eligible` |
| RAG 降级仍直提 | POL-DEGRADE-01 | drill / standalone scorecard degrade 指标 |
| 降级提交无反馈闭环 | feedback `down` + run_id 回读 | `check_feedback_roundtrip`（advisory） |
| 证书被当司法审计 | `assurance=state_snapshot_not_tamper_proof` | `validate_certificate` · catalog lock |
| runs.db 指纹可逆 demo key | 生产须 session/token；演示 resume 从 fp 还原 | `store.restore_api_key_from_fingerprint` · 仅 demo_keys 小集合 |
