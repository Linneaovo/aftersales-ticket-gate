# -*- coding: utf-8 -*-
"""双仓联动验证矩阵（V1–V3）+ 宣称规则打印。

用法（两边服务已起，Copilot 为 .env.demo 联调档）：
  python scripts/run_joint_verify.py
  python scripts/run_joint_verify.py --pack          # 额外尝试 --live 证据包
  python scripts/run_joint_verify.py --offline-only  # 仅配置/降级场景，不要求 :8001

宣称规则：
  - Standalone 绿 ≠ Live 绿
  - 仅 joint_evidence_pack.live_verified=true 可宣称本机 Live
  - token/source 为演示归属约定，非生产鉴权
  - Plan B / from_artifacts 不得冒充联调证据
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "eval" / "joint_verify_matrix.json"
RAG_BASE = "http://127.0.0.1:8001"
COP_BASE = "http://127.0.0.1:8002"


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _print_claim_rules() -> None:
    print("\n=== claim rules (do not mix) ===")
    print("  Standalone green => only claim: gate repo independently accepted")
    print("  design/contract  => only claim: linkage design landed")
    print("  live_verified    => may claim: local Live linkage passed")
    print("  token/source     => demo ownership, NOT production auth")
    print("  Plan B/artifacts => narrative only, NOT live evidence")
    print("  Joint all-red    => does not void Standalone; cannot replace Live")


def _check_v3_config(report: dict[str, Any]) -> bool:
    """V3：RAG 不可达时不得静默假联调（读 .env.demo + 可选 failure drill）。"""
    drill_mod = _load_script("build_joint_failure_drill")
    drill = drill_mod.build_drill(probe_live=False)
    scenes = {s.get("id"): s for s in (drill.get("scenes") or []) if isinstance(s, dict)}
    rag_deg = scenes.get("rag_degraded") or {}
    rag_unreach = scenes.get("rag_unreachable") or {}
    env_ok = bool(rag_unreach.get("ok"))
    degrade_ok = bool(rag_deg.get("ok")) if rag_deg else True
    ok = env_ok and degrade_ok
    report["checks"]["V3_no_silent_fallback"] = {
        "ok": ok,
        "rag_unreachable_config_ok": env_ok,
        "rag_degraded_ok": degrade_ok,
        "detail": "env.demo RAG_AUTO_FALLBACK=0 + REQUIRE_LIVE/BLOCK；drill rag_degraded",
    }
    # 落盘 drill 供 synergy 回读
    drill_path = ROOT / "data" / "eval" / "joint_failure_drill.json"
    drill_path.write_text(json.dumps(drill, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{'PASS' if ok else 'FAIL'}] V3 no silent fallback (unreachable={env_ok} degraded={degrade_ok})")
    return ok


def _check_v1_v2_live(report: dict[str, Any], *, rag_base: str) -> tuple[bool, bool]:
    """V1 无 token 拒业务 submit；V2 probe 不进 business lane（contract check）。"""
    import httpx

    try:
        rh = httpx.get(f"{rag_base.rstrip('/')}/health", timeout=10.0)
    except Exception as exc:  # noqa: BLE001
        report["checks"]["V1_no_token_reject"] = {"ok": False, "error": f"RAG unreachable: {exc}"}
        report["checks"]["V2_probe_not_business"] = {"ok": False, "error": f"RAG unreachable: {exc}"}
        print(f"[FAIL] V1/V2 skipped — RAG unreachable: {exc}")
        return False, False

    if rh.status_code != 200:
        report["checks"]["V1_no_token_reject"] = {"ok": False, "status": rh.status_code}
        report["checks"]["V2_probe_not_business"] = {"ok": False, "status": rh.status_code}
        print(f"[FAIL] V1/V2 — RAG health HTTP {rh.status_code}")
        return False, False

    body = rh.json() if rh.content else {}
    from app.tools.rag_contract import CONTRACT_VERSION

    supported = body.get("consumer_contract_version_supported")
    ver_ok = supported == CONTRACT_VERSION
    report["checks"]["contract_version"] = {
        "ok": ver_ok,
        "rag": supported,
        "copilot": CONTRACT_VERSION,
    }
    print(
        f"[{'PASS' if ver_ok else 'FAIL'}] contract version "
        f"RAG={supported!r} Copilot={CONTRACT_VERSION!r}"
    )
    if not ver_ok:
        report["checks"]["V1_no_token_reject"] = {"ok": False, "blocked_by": "contract_version"}
        report["checks"]["V2_probe_not_business"] = {"ok": False, "blocked_by": "contract_version"}
        return False, False

    gate_on = bool(body.get("submit_require_copilot_token"))
    token_cfg = bool(body.get("copilot_submit_token_configured"))
    report["checks"]["submit_gate"] = {
        "ok": gate_on and token_cfg,
        "submit_require_copilot_token": gate_on,
        "token_configured": token_cfg,
    }
    if not gate_on or not token_cfg:
        print(
            "[FAIL] RAG submit gate off — 用 start_demo/demo_env 开 "
            "SUBMIT_REQUIRE_COPILOT_TOKEN=1 并重启 :8001"
        )
        report["checks"]["V1_no_token_reject"] = {"ok": False, "blocked_by": "submit_gate_off"}
        report["checks"]["V2_probe_not_business"] = {"ok": False, "blocked_by": "submit_gate_off"}
        return False, False
    print("[PASS] RAG submit gate on (business needs token)")

    # V2 via live_rag_contract_check（含 probe lane 隔离）
    contract_mod = _load_script("live_rag_contract_check")
    crep = contract_mod.check(rag_base)
    v2_ok = bool(crep.get("all_ok"))
    report["checks"]["V2_probe_not_business"] = {
        "ok": v2_ok,
        "errors": crep.get("errors"),
        "source": "live_rag_contract_check",
    }
    print(f"[{'PASS' if v2_ok else 'FAIL'}] V2 probe not in business lane (contract check)")

    # V1 via demo_strict_submit_check（无 token 403 + 绿路径）
    strict_mod = _load_script("demo_strict_submit_check")
    code = strict_mod.main()
    strict_path = ROOT / "data" / "eval" / "demo_strict_submit_check.json"
    strict = {}
    if strict_path.is_file():
        try:
            strict = json.loads(strict_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            strict = {}
    checks = strict.get("checks") or {}
    red = checks.get("red_no_token_403") or {}
    v1_ok = code == 0 and bool(strict.get("all_ok")) and bool(red.get("ok"))
    report["checks"]["V1_no_token_reject"] = {
        "ok": v1_ok,
        "strict_all_ok": strict.get("all_ok"),
        "red_ok": red.get("ok"),
        "source": "demo_strict_submit_check",
    }
    print(f"[{'PASS' if v1_ok else 'FAIL'}] V1 no-token business submit rejected")
    return v1_ok, v2_ok


def _check_allowlist(report: dict[str, Any]) -> bool:
    align_mod = _load_script("check_parts_live_align")
    align = align_mod.check()
    ok = bool(align.get("ok"))
    report["checks"]["parts_allowlist"] = {
        "ok": ok,
        "errors": align.get("errors"),
        "part_nos": len(align.get("part_nos") or []),
    }
    print(f"[{'PASS' if ok else 'FAIL'}] parts allowlist <-> ledger")

    rag_script = ROOT.parent / "enterprise-rag" / "scripts" / "check_copilot_parts_allowlist.py"
    if rag_script.is_file():
        import subprocess

        proc = subprocess.run(
            [sys.executable, str(rag_script)],
            cwd=str(rag_script.parent.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        rag_ok = proc.returncode == 0
        report["checks"]["rag_allowlist_cross"] = {
            "ok": rag_ok,
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-400:],
        }
        print(f"[{'PASS' if rag_ok else 'FAIL'}] RAG<->Copilot allowlist cross-check")
        ok = ok and rag_ok
    else:
        report["checks"]["rag_allowlist_cross"] = {
            "ok": True,
            "skipped": True,
            "reason": "enterprise-rag script missing",
        }
        print("[SKIP] RAG allowlist cross-check (sibling script not found)")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Joint linkage verify matrix V1–V3")
    parser.add_argument("--rag-base", default=RAG_BASE)
    parser.add_argument("--cop-base", default=COP_BASE)
    parser.add_argument(
        "--offline-only",
        action="store_true",
        help="只跑 V3 配置 + allowlist；不碰 :8001 Live 探针",
    )
    parser.add_argument(
        "--pack",
        action="store_true",
        help="矩阵通过后跑 build_joint_evidence_pack --live",
    )
    parser.add_argument("--skip-allowlist", action="store_true")
    args = parser.parse_args()

    report: dict[str, Any] = {
        "schema": "joint_verify_matrix/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "offline_only" if args.offline_only else "live_matrix",
        "checks": {},
        "claim_rules": {
            "standalone_green": "门禁仓可独立验收",
            "design_only": "协同设计已落地（未验证 Live）",
            "live_verified_required": "本机 Live 联调通过",
            "token_is_demo_ownership": True,
            "plan_b_not_live_evidence": True,
        },
    }

    print("== joint verify matrix ==")
    _print_claim_rules()

    allow_ok = True
    if not args.skip_allowlist:
        allow_ok = _check_allowlist(report)

    v3_ok = _check_v3_config(report)

    if args.offline_only:
        report["required_ok"] = bool(allow_ok and v3_ok)
        report["live_matrix_ok"] = False
        report["note"] = "offline-only：未跑 V1/V2；不得宣称 Live"
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nwrote {OUT}")
        print(f"=== MATRIX {'OK (offline)' if report['required_ok'] else 'FAIL'} ===")
        print("口径：仅配置层；Live 请去掉 --offline-only 重跑")
        return 0 if report["required_ok"] else 1

    v1_ok, v2_ok = _check_v1_v2_live(report, rag_base=args.rag_base)
    ver_ok = bool((report["checks"].get("contract_version") or {}).get("ok"))
    gate_ok = bool((report["checks"].get("submit_gate") or {}).get("ok"))

    matrix_ok = bool(allow_ok and v3_ok and ver_ok and gate_ok and v1_ok and v2_ok)
    report["required_ok"] = matrix_ok
    report["live_matrix_ok"] = matrix_ok

    pack_info: dict[str, Any] = {"ran": False}
    if args.pack:
        if not matrix_ok:
            print("[SKIP] --pack：矩阵未全绿，不跑证据包（避免假 live_verified）")
            pack_info = {"ran": False, "skipped": True, "reason": "matrix_not_ok"}
        else:
            pack_mod = _load_script("build_joint_evidence_pack")
            # build_joint_evidence_pack.main 读 argv；直接调用内部逻辑
            old_argv = sys.argv
            try:
                sys.argv = ["build_joint_evidence_pack.py", "--live"]
                code = pack_mod.main()
            finally:
                sys.argv = old_argv
            joint_path = ROOT / "data" / "eval" / "joint_evidence_pack.json"
            joint = {}
            if joint_path.is_file():
                try:
                    joint = json.loads(joint_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    joint = {}
            pack_info = {
                "ran": True,
                "exit_code": code,
                "live_verified": bool(joint.get("live_verified")),
                "portfolio_claimable": bool(joint.get("portfolio_claimable")),
            }
            print(
                f"[{'PASS' if pack_info['live_verified'] else 'FAIL'}] evidence pack "
                f"live_verified={pack_info['live_verified']} claimable={pack_info['portfolio_claimable']}"
            )
    report["evidence_pack"] = pack_info

    # 最终宣称建议
    if pack_info.get("live_verified") and pack_info.get("portfolio_claimable"):
        claim = "本机 Live 联调通过（live_verified=true 且 synergy 可宣称）"
    elif matrix_ok:
        claim = "V1–V3 矩阵绿；尚未/未通过证据包 — 可说矩阵通过，勿单凭矩阵称 portfolio Live"
    else:
        claim = "矩阵未全绿 — 仅可说协同设计已落地 / 回退 Standalone 验收"
    report["suggested_claim"] = claim
    print(f"\n建议口径：{claim}")

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"=== MATRIX {'OK' if matrix_ok else 'FAIL'} ===")
    return 0 if matrix_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
