#!/usr/bin/env python3
"""校验评测产物 git_sha 与当前 HEAD 一致（防代码变了报告仍是旧的）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARTIFACTS = (
    ROOT / "data" / "eval" / "hitl_gate_report.json",
    ROOT / "data" / "eval" / "standalone_scorecard.json",
    ROOT / "data" / "eval" / "governance_scorecard.json",
    ROOT / "data" / "eval" / "l1_linkage_report.json",
    ROOT / "data" / "eval" / "joint_evidence_pack.json",
)


def main() -> int:
    from app.eval.ssot import resolve_git_sha

    head = resolve_git_sha()
    if not head:
        print("[SKIP] not a git repo or git unavailable")
        return 0
    errs: list[str] = []
    for path in ARTIFACTS:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errs.append(f"{path.name}: unreadable ({exc})")
            continue
        recorded = data.get("git_sha")
        if not recorded:
            # 联合包 / L1 报告若无 sha：仅警告（可能本机未装 git）；有 sha 则必须匹配
            if path.name in {"joint_evidence_pack.json", "l1_linkage_report.json"}:
                print(f"[WARN] {path.name}: missing git_sha（建议再生以钉版本）")
                continue
            errs.append(f"{path.name}: missing git_sha — regenerate with CI scripts")
        elif recorded != head:
            errs.append(f"{path.name}: git_sha={recorded} ≠ HEAD={head}")
        # 防伪：旧快照不得静默自称 L2 live
        if path.name == "joint_evidence_pack.json":
            tier = data.get("evidence_tier")
            if data.get("mode") == "from_artifacts" and (
                data.get("live_verified") or tier == "L2"
            ):
                errs.append(
                    f"{path.name}: from_artifacts 不得 live_verified/L2（evidence_tier={tier!r}）"
                )
            if tier == "L1" and data.get("live_verified"):
                errs.append(f"{path.name}: L1 不得 live_verified=true")
        if path.name == "l1_linkage_report.json" and data.get("live_verified"):
            errs.append(f"{path.name}: L1 报告不得 live_verified=true")
    if errs:
        for e in errs:
            print(f"[FAIL] {e}")
        print("hint: python scripts/run_hitl_gate_eval.py && python scripts/build_governance_scorecard.py --profile standalone")
        return 1
    print(f"[OK] eval artifacts git_sha={head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
