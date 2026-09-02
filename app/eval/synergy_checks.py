"""联合证据 synergy_checks：required 失败则不得 portfolio_claimable。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT

EVAL_DIR = PROJECT_ROOT / "data" / "eval"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _probe_not_business_ok() -> tuple[bool, str]:
    """F3：无 token 业务 submit 须拒；contract_probe 不得进 business lane。"""
    strict = _load_json(EVAL_DIR / "demo_strict_submit_check.json")
    # skipped / 空 checks（如 RAG 不可达）不阻断，回退到 live_rag_contract_check
    if strict and not strict.get("skipped") and (strict.get("checks") or {}):
        checks = strict.get("checks") or {}
        red = checks.get("red_no_token_403") or {}
        probe = checks.get("probe_without_token_200") or {}
        green = checks.get("green_copilot_approve") or {}
        ok = bool(strict.get("all_ok") and red.get("ok") and probe.get("ok") and green.get("ok"))
        return ok, "data/eval/demo_strict_submit_check.json"
    crep = _load_json(EVAL_DIR / "live_rag_contract_check.json")
    if crep:
        # live_rag_contract_check 含 probe 归属与 business 隔离断言
        ok = bool(crep.get("all_ok"))
        return ok, "data/eval/live_rag_contract_check.json"
    return False, "missing demo_strict_submit_check / live_rag_contract_check"


def _degrade_drill_ok() -> tuple[bool, str]:
    """F6：joint_failure_drill 中 rag_degraded 幕须绿。"""
    drill = _load_json(EVAL_DIR / "joint_failure_drill.json")
    for scene in drill.get("scenes") or []:
        if isinstance(scene, dict) and scene.get("id") == "rag_degraded":
            return bool(scene.get("ok")), "data/eval/joint_failure_drill.json#rag_degraded"
    return False, "missing joint_failure_drill rag_degraded scene"


def _acl_matrix_ok() -> tuple[bool, str]:
    """F8：ACL L1/L2 矩阵（B7）；缺产物不得用 manual 弱代理冒充。"""
    matrix = _load_json(EVAL_DIR / "acl_matrix.json")
    if matrix:
        mx = matrix.get("matrix") if isinstance(matrix.get("matrix"), dict) else {}
        ok = bool(matrix.get("all_ok")) and bool(mx.get("l1_only")) and bool(mx.get("l2_only"))
        return ok, "data/eval/acl_matrix.json"
    return False, "missing data/eval/acl_matrix.json — run scripts/run_acl_matrix.py"


def build_synergy_checks(pack: dict[str, Any]) -> dict[str, Any]:
    """从 joint pack + 磁盘联调产物推导 synergy；不手填。"""
    sample = pack.get("live_sample_p1") or {}
    aa = sample.get("after_approve") or {}
    parts = pack.get("parts_gate_ab") if isinstance(pack.get("parts_gate_ab"), dict) else {}
    live_ab = parts.get("live") if isinstance(parts.get("live"), dict) else {}
    offline_ab = parts.get("offline") if isinstance(parts.get("offline"), dict) else {}
    probe = pack.get("live_probe") or {}

    draft_then_gate = {
        "id": "draft_then_gate",
        "failure_mode": "F1",
        "required": True,
        "ok": bool(
            sample.get("rag_client_mode") == "live"
            and sample.get("status") in {"waiting_hitl", "succeeded"}
            and "POL-PARTS-01" in list(sample.get("policy_ids") or [])
        ),
        "detail": "P1 live sample must hit POL-PARTS-01 after draft/parts",
    }
    hitl_then_inbox = {
        "id": "hitl_then_inbox",
        "failure_mode": "F2",
        "required": True,
        "ok": bool(sample.get("ownership_ok") is True)
        and aa.get("source") == "copilot_hitl"
        and aa.get("inbox_source") == "copilot_hitl",
        "detail": "approve → submit → inbox source=copilot_hitl + run_id",
    }
    probe_ok, probe_src = _probe_not_business_ok()
    probe_not_business = {
        "id": "probe_not_business",
        "failure_mode": "F3",
        "required": True,
        "ok": probe_ok,
        "detail": f"no-token business rejected; probe≠business ({probe_src})",
    }
    parts_ab_live = {
        "id": "parts_ab_live",
        "failure_mode": "F4",
        "required": True,
        "ok": bool(live_ab.get("present") and live_ab.get("all_ok") and offline_ab.get("all_ok")),
        "detail": "parts_gate_ab.offline + .live both all_ok",
    }
    contract_aligned = {
        "id": "contract_aligned",
        "failure_mode": "F5",
        "required": True,
        "ok": bool(probe.get("contract_version_match")),
        "detail": "RAG consumer_contract_version_supported == Copilot CONTRACT_VERSION",
    }
    degrade_ok, degrade_src = _degrade_drill_ok()
    degrade_blocks = {
        "id": "degrade_blocks_auto_submit",
        "failure_mode": "F6",
        "required": True,
        "ok": degrade_ok,
        "detail": f"joint_failure_drill rag_degraded ({degrade_src})",
    }
    acl_ok, acl_src = _acl_matrix_ok()
    acl_l1_or_l2 = {
        "id": "acl_l1_or_l2",
        "failure_mode": "F8",
        "required": True,
        "ok": acl_ok,
        "detail": f"ACL L1/L2 matrix ({acl_src})",
    }

    checks = [
        draft_then_gate,
        hitl_then_inbox,
        probe_not_business,
        parts_ab_live,
        contract_aligned,
        degrade_blocks,
        acl_l1_or_l2,
    ]
    required = [c for c in checks if c.get("required")]
    required_ok = all(bool(c.get("ok")) for c in required)
    failure_modes = {str(c.get("failure_mode")): bool(c.get("ok")) for c in checks if c.get("failure_mode")}
    required_fm = ["F1", "F2", "F3", "F4", "F5", "F6", "F8"]
    coverage = sum(1 for fm in required_fm if failure_modes.get(fm))
    return {
        "schema": "synergy_checks/v1",
        "required_ok": required_ok,
        "checks": checks,
        "failure_mode_coverage": failure_modes,
        "failure_mode_required_coverage": {
            "required": required_fm,
            "covered": coverage,
            "total": len(required_fm),
            "ratio": coverage / len(required_fm),
        },
    }


def apply_synergy_to_claimability(pack: dict[str, Any]) -> dict[str, Any]:
    """写入 synergy_checks；live_verified 时 portfolio_claimable 须 required_ok。"""
    synergy = build_synergy_checks(pack)
    pack["synergy_checks"] = synergy
    if pack.get("live_verified"):
        if not synergy.get("required_ok"):
            pack["portfolio_claimable"] = False
            failed = [c["id"] for c in synergy.get("checks") or [] if c.get("required") and not c.get("ok")]
            pack["portfolio_warning"] = (
                pack.get("portfolio_warning")
                or f"synergy_checks.required failed: {failed}"
            )
        else:
            pack["portfolio_claimable"] = True
    elif pack.get("mode") == "from_artifacts":
        pack["portfolio_claimable"] = False
    return pack
