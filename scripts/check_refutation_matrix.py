#!/usr/bin/env python3
"""反证矩阵自动化：挂接已有 parts A/B + allowlist + ACL 剧本规格。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from app.eval.parts_gate_ab import run_parts_gate_ab
    from app.playbooks.validate import load_playbook

    errors: list[str] = []

    # 1+2：缺料开/关
    ab = run_parts_gate_ab()
    if not ab.get("all_ok"):
        errors.append(f"parts_gate_ab not all_ok: {ab}")
    else:
        print("[OK] refutation 1+2 parts_gate_ab A/B")

    # 3：allowlist ⊆ ledger
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_parts_live_align", ROOT / "scripts" / "check_parts_live_align.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    align = mod.check()
    if not align.get("ok"):
        errors.append(f"align: {align.get('errors')}")
    else:
        print("[OK] refutation 3 parts live align")

    # 4：ACL 剧本规格 + 双层矩阵产物
    p3 = load_playbook("p3_acl_salary")
    if p3.get("expect_status") != "rejected" and p3.get("expect_intent") != "acl_probe":
        # 兼容：status rejected 或 intent acl_probe
        if p3.get("expect_intent") != "acl_probe" and "reject" not in str(p3.get("expect_status")):
            errors.append(f"p3 ACL spec weak: {p3.get('expect_status')} / {p3.get('expect_intent')}")
        else:
            print("[OK] refutation 4 p3 ACL spec")
    else:
        print("[OK] refutation 4 p3 ACL spec")

    acl_path = ROOT / "data" / "eval" / "acl_matrix.json"
    acl_ok = False
    if not acl_path.exists():
        errors.append("missing data/eval/acl_matrix.json — run scripts/run_acl_matrix.py")
    else:
        acl = json.loads(acl_path.read_text(encoding="utf-8"))
        mx = acl.get("matrix") or {}
        acl_ok = bool(
            acl.get("all_ok") and mx.get("l1_only") and mx.get("l2_only") and mx.get("dual_short_circuit")
        )
        if not acl_ok:
            errors.append(f"acl_matrix not all_ok: {mx}")
        else:
            print("[OK] refutation 4 acl_matrix L1/L2/short-circuit")

    report = {
        "schema": "refutation_matrix_check/v1",
        "all_ok": not errors,
        "errors": errors,
        "parts_gate_ab_all_ok": bool(ab.get("all_ok")),
        "align_ok": bool(align.get("ok")),
        "acl_matrix_ok": acl_ok,
    }
    out = ROOT / "data" / "eval" / "refutation_matrix_check.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out} all_ok={report['all_ok']}")
    if errors:
        for e in errors:
            print(f"[FAIL] {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
