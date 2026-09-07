#!/usr/bin/env python3
"""校验评测产物 git_sha 与当前 HEAD 一致（防代码变了报告仍是旧的）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# L0 CI 会再生这三份；git_sha 必须与 HEAD 一致
L0_REGENERATED = (
    ROOT / "data" / "eval" / "hitl_gate_report.json",
    ROOT / "data" / "eval" / "standalone_scorecard.json",
    ROOT / "data" / "eval" / "governance_scorecard.json",
)
# L1 / 联合包由 linkage 或本机 --live 生成；L0 作业不再生 → sha 漂移只 WARN
OPTIONAL_LINKAGE = (
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
    for path in L0_REGENERATED:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errs.append(f"{path.name}: unreadable ({exc})")
            continue
        recorded = data.get("git_sha")
        if not recorded:
            errs.append(f"{path.name}: missing git_sha — regenerate with CI scripts")
        elif recorded != head:
            errs.append(f"{path.name}: git_sha={recorded} ≠ HEAD={head}")
    for path in OPTIONAL_LINKAGE:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errs.append(f"{path.name}: unreadable ({exc})")
            continue
        recorded = data.get("git_sha")
        if not recorded:
            print(f"[WARN] {path.name}: missing git_sha（建议再生以钉版本）")
        elif recorded != head:
            print(
                f"[WARN] {path.name}: git_sha={recorded} ≠ HEAD={head} "
                "（L0 不再生；跑 linkage-l1 / build_joint_evidence_pack 更新）"
            )
        # 防伪：旧快照不得静默自称 L2 live（与 sha 是否匹配无关）
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
        print(
            "hint: python scripts/run_hitl_gate_eval.py && "
            "python scripts/build_governance_scorecard.py --profile standalone && "
            "python scripts/build_governance_scorecard.py"
        )
        return 1
    print(f"[OK] L0 eval artifacts git_sha={head}（L1/joint sha 漂移仅 WARN）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
