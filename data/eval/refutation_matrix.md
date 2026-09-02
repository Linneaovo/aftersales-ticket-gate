# 反证矩阵（门禁可证伪）

| # | 操纵 | 期望 | 命令 / 测例 |
|---|------|------|-------------|
| 1 | 主缺料件 stock: 0→N | 不再触发 POL-PARTS-01 | `parts_gate_ab` case B / `test_ledger_hot_reload_same_process` |
| 2 | stock: N→0 | 恢复 POL-PARTS-01 | `parts_gate_ab` case A / `scripts/parts_gate_ab_test.py` |
| 3 | 从 ledger 删 Live 件号 | align 红 或 PARTS-02 可观测 | `scripts/check_parts_live_align.py` |
| 4 | RAG ACL 主题（薪酬等） | L1 rejected 或 L2 blocked | `acl_matrix`（L1/L2/短路）/ playbook `p3_acl_salary` |
| 5 | 空 hints | 不假缺料 | `test_empty_hints_no_false_shortage` |
| 6 | ledger_degraded | POL-PARTS-02 | `test_ledger_degraded_flag_forces_parts_02_layer` |
| 7 | 缺料+未知件并存 | PARTS-01+02 同在 | `test_shortage_plus_unknown_keeps_parts_01` |
| 8 | 机型不匹配 | model_mismatch / PARTS-02 | `test_machine_model_mismatch_blocks_as_ledger_layer` |
| 9 | 多件号部分缺料 | 缺料件仍触发 PARTS-01 | `test_partial_multi_part_shortage_keeps_parts_01` |
| 10 | Fixture 绿跑 | **不**证明检索 MRR / 语料质量 | Standalone Scope；MRR 只认 RAG 仓金标 |

```bash
python scripts/check_refutation_matrix.py
python scripts/parts_gate_ab_test.py
python scripts/check_parts_live_align.py
```
