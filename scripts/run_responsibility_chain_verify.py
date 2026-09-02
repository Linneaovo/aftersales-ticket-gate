# -*- coding: utf-8 -*-
"""售后 AI 责任链四层验收（路线 A 王牌化入口）。

命题：检索可信 != 允许开单（知识 / 门禁 / 归属 / 证据）

用法（Live 全链，:8001 + :8002 联调档已起）：
  python scripts/run_responsibility_chain_verify.py
  python scripts/run_responsibility_chain_verify.py --pack

仅离线（L2 离线 A/B + L3 配置 + 无 L1 Live）：
  python scripts/run_responsibility_chain_verify.py --offline-only

产物：data/eval/responsibility_chain_report.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RAG_ROOT = ROOT.parent / "enterprise-rag"
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "eval" / "responsibility_chain_report.json"
PROPOSITION = "检索可信 != 允许开单"


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _run_l1(*, rag_base: str, require: bool) -> dict[str, Any]:
    script = RAG_ROOT / "scripts" / "responsibility_chain_knowledge_probe.py"
    if not script.is_file():
        return {"ok": False, "skipped": True, "reason": "missing RAG L1 script"}
    argv = [sys.executable, str(script), "--rag-base", rag_base]
    if require:
        argv.append("--require-live")
    proc = subprocess.run(argv, cwd=str(RAG_ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    l1_path = RAG_ROOT / "data" / "eval" / "responsibility_chain_l1.json"
    payload: dict[str, Any] = {"exit_code": proc.returncode, "stdout_tail": (proc.stdout or "")[-600:]}
    if l1_path.is_file():
        try:
            payload.update(json.loads(l1_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    payload["ok"] = proc.returncode == 0 and bool(payload.get("all_ok"))
    print(proc.stdout or proc.stderr or "")
    return payload


def _run_l2(*, live: bool, cop_base: str) -> dict[str, Any]:
    from app.eval.parts_gate_ab import run_parts_gate_ab, run_parts_gate_ab_live

    offline = run_parts_gate_ab()
    out_path = ROOT / "data" / "eval" / "parts_gate_ab.json"
    out_path.write_text(json.dumps(offline, ensure_ascii=False, indent=2), encoding="utf-8")
    offline_ok = bool(offline.get("all_ok"))
    print(f"[{'PASS' if offline_ok else 'FAIL'}] L2 gate offline A/B (stock flip -> POL-PARTS)")

    live_ab: dict[str, Any] = {"present": False, "all_ok": False, "skip_reason": "offline-only"}
    if live:
        live_ab = run_parts_gate_ab_live(base_url=cop_base)
        live_path = ROOT / "data" / "eval" / "parts_gate_ab_live.json"
        live_path.write_text(json.dumps(live_ab, ensure_ascii=False, indent=2), encoding="utf-8")
        live_ok = bool(live_ab.get("present") and live_ab.get("all_ok"))
        print(f"[{'PASS' if live_ok else 'FAIL'}] L2 gate live P1/P1b (shortage vs in-stock)")
    else:
        live_ok = True  # not required offline

    ok = offline_ok and (live_ok if live else True)
    return {
        "ok": ok,
        "offline": {"all_ok": offline_ok, "cases": (offline.get("cases") or {})},
        "live": live_ab,
    }


def _run_l3_l4(*, rag_base: str, offline_only: bool, pack: bool) -> dict[str, Any]:
    live = not offline_only
    mod = _load_script("run_joint_verify")
    old_argv = sys.argv
    argv = ["run_joint_verify.py", "--rag-base", rag_base]
    if offline_only:
        argv.append("--offline-only")
    if pack and not offline_only:
        argv.append("--pack")
    try:
        sys.argv = argv
        code = mod.main()
    finally:
        sys.argv = old_argv

    matrix_path = ROOT / "data" / "eval" / "joint_verify_matrix.json"
    matrix: dict[str, Any] = {}
    if matrix_path.is_file():
        try:
            matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            matrix = {}

    pack_path = ROOT / "data" / "eval" / "joint_evidence_pack.json"
    pack_body: dict[str, Any] = {}
    if pack_path.is_file():
        try:
            pack_body = json.loads(pack_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pack_body = {}

    l3_ok = bool(matrix.get("live_matrix_ok")) if not offline_only else bool(
        (matrix.get("checks") or {}).get("V3_no_silent_fallback", {}).get("ok")
    )
    if offline_only:
        l3_ok = bool(matrix.get("required_ok"))

    l4_ok = bool(pack_body.get("live_verified") and pack_body.get("portfolio_claimable")) if (pack and live) else (
        l3_ok if live else True
    )

    return {
        "L3_ownership": {
            "ok": l3_ok,
            "matrix_required_ok": matrix.get("required_ok"),
            "checks": matrix.get("checks"),
            "exit_code": code,
        },
        "L4_evidence": {
            "ok": l4_ok,
            "live_verified": pack_body.get("live_verified"),
            "portfolio_claimable": pack_body.get("portfolio_claimable"),
            "pack_ran": pack and not offline_only,
        },
        "joint_verify_exit": code,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Four-layer responsibility chain verify")
    parser.add_argument("--rag-base", default="http://127.0.0.1:8001")
    parser.add_argument("--cop-base", default="http://127.0.0.1:8002")
    parser.add_argument("--offline-only", action="store_true")
    parser.add_argument("--pack", action="store_true", help="Live: also build joint evidence pack")
    args = parser.parse_args()

    live = not args.offline_only
    report: dict[str, Any] = {
        "schema": "responsibility_chain/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "proposition": PROPOSITION,
        "mode": "live" if live else "offline",
        "layers": {},
        "claim_rules": {
            "standalone_ne_live": True,
            "live_claim_requires_live_verified": True,
            "token_is_demo_ownership": True,
        },
    }

    print("== responsibility chain verify ==")
    print(f"proposition: {PROPOSITION}")

    if args.offline_only:
        report["layers"]["L1_knowledge"] = {"ok": True, "skipped": True, "reason": "offline-only"}
    else:
        report["layers"]["L1_knowledge"] = _run_l1(rag_base=args.rag_base, require=True)

    report["layers"]["L2_gate"] = _run_l2(live=live, cop_base=args.cop_base)
    l34 = _run_l3_l4(rag_base=args.rag_base, offline_only=args.offline_only, pack=args.pack)
    report["layers"]["L3_ownership"] = l34["L3_ownership"]
    report["layers"]["L4_evidence"] = l34["L4_evidence"]

    layer_ok = {k: bool(v.get("ok")) for k, v in report["layers"].items()}
    report["layer_ok"] = layer_ok
    report["all_ok"] = all(layer_ok.values())
    report["claimable_live"] = bool(
        live and report["all_ok"] and report["layers"]["L4_evidence"].get("live_verified")
    )

    if report["claimable_live"]:
        report["suggested_claim"] = "本机 Live 责任链验收通过（四层 + live_verified）"
    elif report["all_ok"] and live:
        report["suggested_claim"] = "四层矩阵绿；加 --pack 且 live_verified 后可宣称 Live"
    elif report["all_ok"]:
        report["suggested_claim"] = "离线责任链配置/门禁绿；Live 须去 --offline-only 重跑"
    else:
        report["suggested_claim"] = "责任链未全绿；勿宣称王牌/Live"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}")
    print(f"layers: {layer_ok}")
    print(f"suggested_claim: {report['suggested_claim']}")
    print(f"=== CHAIN {'OK' if report['all_ok'] else 'FAIL'} ===")
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
