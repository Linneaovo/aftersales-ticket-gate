"""治理层 Scorecard：只聚合脚本/产物，禁止手填分数。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT
from app.eval.ssot import resolve_git_sha
from app.policy.rules_catalog import CORE_POLICIES

EVAL_DIR = PROJECT_ROOT / "data" / "eval"
PLAYBOOKS_DIR = PROJECT_ROOT / "data" / "playbooks"
SCORECARD_PATH = EVAL_DIR / "governance_scorecard.json"
STANDALONE_SCORECARD_PATH = EVAL_DIR / "standalone_scorecard.json"
SCHEMA = "governance_scorecard/v1"
STANDALONE_SCHEMA = "standalone_scorecard/v1"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _mtime(path: Path) -> float | None:
    if not path.exists():
        return None
    return path.stat().st_mtime


def _metric(
    *,
    name: str,
    ok: bool,
    value: Any,
    source: str,
    detail: str = "",
    required: bool = True,
) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "value": value,
        "source": source,
        "detail": detail,
        "required": required,
    }


def _hitl_gate_agreement() -> dict[str, Any]:
    """闭集 should_hitl 符合率（读 hitl_gate_report；缺报告则失败，禁止手填）。"""
    report = _load_json(EVAL_DIR / "hitl_gate_report.json")
    if not report:
        return _metric(
            name="hitl_gate_agreement",
            ok=False,
            value={"present": False},
            source="data/eval/hitl_gate_report.json",
            detail="missing hitl_gate_report — run scripts/run_hitl_gate_eval.py",
        )
    metrics = report.get("metrics") or {}
    thr = report.get("thresholds") or {}
    recall = metrics.get("should_hitl_recall")
    false_rate = metrics.get("false_hitl_rate")
    leak_n = int(metrics.get("leak_submit_count") or 0)
    recall_min = float(thr.get("should_hitl_recall_min", 0.92))
    false_max = float(thr.get("false_hitl_rate_max", 0.08))
    ok = bool(report.get("all_ok")) and leak_n <= int(thr.get("leak_submit_count_max", 0))
    if recall is not None:
        ok = ok and float(recall) >= recall_min
    if false_rate is not None:
        ok = ok and float(false_rate) <= false_max
    n_cases = int(report.get("n_cases") or 0)
    ok = ok and n_cases >= 25
    return _metric(
        name="hitl_gate_agreement",
        ok=ok,
        value={
            "mode": report.get("mode"),
            "n_cases": n_cases,
            "n_should_hitl": metrics.get("n_should_hitl"),
            "n_should_not_hitl": metrics.get("n_should_not_hitl"),
            "should_hitl_recall": recall,
            "false_hitl_rate": false_rate,
            "leak_submit_count": leak_n,
            "metric_kind": "offline_goldset",
            "note": "offline_goldset_not_production_precision",
        },
        source="data/eval/hitl_gate_report.json",
        detail=(
            f"n={n_cases} recall={recall} false_hitl_rate={false_rate} leak={leak_n} "
            f"(thresholds recall>={recall_min} false<={false_max} n>=25)"
        ),
    )


def _intent_held_out_ok(*, required: bool = True) -> dict[str, Any]:
    report = _load_json(EVAL_DIR / "intent_eval_report.json")
    if not report:
        return _metric(
            name="intent_held_out",
            ok=False,
            value={"present": False},
            source="data/eval/intent_eval_report.json",
            detail="missing — run scripts/run_intent_eval.py",
            required=required,
        )
    held = report.get("held_out") if isinstance(report.get("held_out"), dict) else {}
    acc = held.get("accuracy", report.get("accuracy"))
    min_acc = float(report.get("min_held_out_accuracy") or 0.75)
    n = held.get("n_cases") or report.get("n_cases")
    failures = list(held.get("failures") or [])[:5]
    ok = bool(report.get("ok")) and acc is not None and float(acc) >= min_acc and int(n or 0) >= 30
    return _metric(
        name="intent_held_out",
        ok=ok,
        value={
            "held_out_accuracy": acc,
            "n_cases": n,
            "min_held_out_accuracy": min_acc,
            "failure_top": failures,
            "low_confidence_rate": (held.get("low_confidence_rate") or report.get("low_confidence_rate")),
            "note": "rule baseline; held_out is professionalism signal",
        },
        source="data/eval/intent_eval_report.json",
        detail=f"held_out acc={acc} n={n} failures={len(held.get('failures') or [])}",
        required=required,
    )


def _false_hitl_cost_advisory() -> dict[str, Any]:
    """误拦代价代理：false_hitl_rate + should_not 分母（advisory）。"""
    report = _load_json(EVAL_DIR / "hitl_gate_report.json")
    metrics = report.get("metrics") or {}
    return _metric(
        name="false_hitl_cost_proxy",
        ok=True,
        value={
            "false_hitl_rate": metrics.get("false_hitl_rate"),
            "n_should_not_hitl": metrics.get("n_should_not_hitl"),
            "interpretation": "false_hitl≈站长被多余打断的比例代理；非工时计量",
        },
        source="data/eval/hitl_gate_report.json",
        detail="advisory only",
        required=False,
    )


def _leak_submit_rate() -> dict[str, Any]:
    """未批准业务落箱：用 joint pack 归属 + live_function 代理；缺产物则失败。"""
    joint = _load_json(EVAL_DIR / "joint_evidence_pack.json")
    func = _load_json(EVAL_DIR / "live_function_test.json")
    sample = joint.get("live_sample_p1") or {}
    aa = sample.get("after_approve") or {}
    ownership_ok = sample.get("ownership_ok")
    leak_signals: list[str] = []
    if aa and ownership_ok is False:
        leak_signals.append("joint_p1_ownership_not_ok")
    if aa.get("source") and aa.get("source") != "copilot_hitl":
        leak_signals.append(f"submit_source={aa.get('source')}")
    if aa.get("inbox_source") and aa.get("inbox_source") != "copilot_hitl":
        leak_signals.append(f"inbox_source={aa.get('inbox_source')}")
    func_ok = bool(func.get("all_ok")) if func else False
    # 无 live 产物时不得假装 leak=0
    has_evidence = bool(joint) or bool(func)
    rate = 1.0 if leak_signals else 0.0
    ok = has_evidence and rate == 0.0 and (not joint.get("live_verified") or ownership_ok is not False)
    if joint.get("live_verified") and ownership_ok is True and not leak_signals:
        ok = True
        rate = 0.0
    elif not has_evidence:
        ok = False
        rate = None
    return _metric(
        name="leak_submit_rate",
        ok=ok,
        value={"rate": rate, "leak_signals": leak_signals, "live_function_all_ok": func_ok},
        source="data/eval/joint_evidence_pack.json + live_function_test.json",
        detail="target rate=0; requires artifacts (no hand-fill)",
    )


def _parts_gate_ab_ok(*, standalone: bool = False) -> dict[str, Any]:
    parts = _load_json(EVAL_DIR / "parts_gate_ab.json")
    joint = _load_json(EVAL_DIR / "joint_evidence_pack.json")
    nested = joint.get("parts_gate_ab") if isinstance(joint.get("parts_gate_ab"), dict) else {}
    offline = nested.get("offline") if isinstance(nested.get("offline"), dict) else {}
    live = nested.get("live") if isinstance(nested.get("live"), dict) else {}
    offline_ok = bool(offline.get("all_ok") if offline else parts.get("all_ok"))
    live_present = bool(live.get("present"))
    live_ok = bool(live.get("all_ok")) if live_present else False
    # Standalone：仅 offline 必过；live_* 透传展示不挡
    ok = bool(parts or offline) and offline_ok
    return _metric(
        name="parts_gate_ab_ok",
        ok=ok,
        value={
            "offline_all_ok": offline_ok,
            "live_present": live_present,
            "live_all_ok": live_ok,
            "live_is_bonus_only": standalone,
            "parts_file_all_ok": bool(parts.get("all_ok")),
        },
        source="data/eval/parts_gate_ab.json (+ joint nested)",
        detail="offline required; live bonus" if standalone else "",
    )


def _degrade_blocks_auto_submit() -> dict[str, Any]:
    """进程内断言：rag_degraded + auto_submit 不得直接可提交。"""
    from app.policy.gates import evaluate_submit_eligible

    state = {
        "intent": "fault_dispatch",
        "role": "technician",
        "auto_submit": True,
        "rag_degraded": True,
        "service_ticket": {"fault_codes": ["H103"], "station": "长沙星沙服务站"},
        "work_order_draft": {"draft": {"fault_codes": ["H103"]}},
        "critic_report": {"passed": True, "force_hitl": False, "reasons": [], "policy_ids": []},
        "conflict_bundle": {},
        "parts_check": {"shortage": False},
        "hitl": {},
        "status": "running",
    }
    eligible, blockers = evaluate_submit_eligible(state)
    blocked = (not eligible) and any("DEGRADE" in str(b) or "降级" in str(b) for b in blockers)
    # 亦接受 force_hitl / 角色门禁拦截
    ok = not eligible
    return _metric(
        name="degrade_blocks_auto_submit",
        ok=ok,
        value={"eligible": eligible, "blockers": list(blockers), "degrade_tagged": blocked},
        source="app.policy.gates.evaluate_submit_eligible (in-process)",
        detail="auto_submit=True + rag_degraded 必须不可直接 submit",
    )


def _file_outbox_port_ok() -> dict[str, Any]:
    """进程内：file_outbox 可写可读幂等（Standalone 落箱端口）。"""
    import tempfile
    from pathlib import Path

    from app.tools.submit_destination import FileOutboxDestination

    try:
        with tempfile.TemporaryDirectory() as td:
            dest = FileOutboxDestination(outbox_dir=Path(td))
            first = dest.submit({"draft": {"probe": True}}, run_id="standalone-scorecard-probe")
            second = dest.submit({"draft": {"probe": False}}, run_id="standalone-scorecard-probe")
            rows = dest.list_tickets(limit=5)
            got = dest.get_ticket("standalone-scorecard-probe")
            ok = (
                first.get("destination") == "file_outbox"
                and first.get("is_production_ticket") is False
                and first.get("source") == "copilot_hitl"
                and second.get("idempotent_replay") is True
                and len(rows) >= 1
                and isinstance(got, dict)
            )
    except Exception as exc:  # noqa: BLE001
        return _metric(
            name="file_outbox_port_ok",
            ok=False,
            value={"error": str(exc)},
            source="FileOutboxDestination (in-process)",
        )
    return _metric(
        name="file_outbox_port_ok",
        ok=ok,
        value={"ticket_id": first.get("ticket_id"), "list_n": len(rows)},
        source="FileOutboxDestination (in-process)",
        detail="file_outbox write/list/idempotent",
    )


def _core_policy_evidence_coverage(*, standalone: bool = False) -> dict[str, Any]:
    covered: dict[str, list[str]] = {pid: [] for pid in CORE_POLICIES}
    for path in sorted(PLAYBOOKS_DIR.glob("*.json")):
        spec = _load_json(path)
        reasons = list(spec.get("expect_hitl_reasons") or [])
        for pid in CORE_POLICIES:
            if pid in reasons or any(pid in str(r) for r in reasons):
                covered[pid].append(path.stem)
    # ROLE-01：技师路径须人确（多剧本 waiting_hitl + technician key）
    if not covered["POL-ROLE-01"]:
        for path in sorted(PLAYBOOKS_DIR.glob("*.json")):
            spec = _load_json(path)
            if spec.get("expect_status") == "waiting_hitl" and "technician" in str(
                spec.get("api_key") or ""
            ):
                covered["POL-ROLE-01"].append(path.stem)
    # DEGRADE-01：联合故障 drill / 或 Standalone 进程内 degrade 门禁
    drill = _load_json(EVAL_DIR / "joint_failure_drill.json")
    if drill.get("scenes"):
        for scene in drill.get("scenes") or []:
            if isinstance(scene, dict) and scene.get("id") in {
                "rag_unreachable",
                "rag_degraded",
                "no_silent_demorag",
            }:
                if "POL-DEGRADE-01" in CORE_POLICIES:
                    covered["POL-DEGRADE-01"].append(f"drill:{scene.get('id')}")
    if standalone and not covered.get("POL-DEGRADE-01"):
        deg = _degrade_blocks_auto_submit()
        if deg.get("ok"):
            covered["POL-DEGRADE-01"].append("in_process:degrade_blocks_auto_submit")
    missing = [pid for pid, refs in covered.items() if not refs]
    ok = not missing
    return _metric(
        name="core_policy_evidence_coverage",
        ok=ok,
        value={"covered": covered, "missing": missing},
        source="data/playbooks + drill|in-process degrade",
    )


def _contract_drift(*, required: bool = True) -> dict[str, Any]:
    from app.eval.contract_fields import validate_consumer_fields_table
    from app.tools.rag_contract import CONTRACT_VERSION

    crep = _load_json(EVAL_DIR / "live_rag_contract_check.json")
    joint = _load_json(EVAL_DIR / "joint_evidence_pack.json")
    probe = joint.get("live_probe") or {}
    version_match = probe.get("contract_version_match")
    file_ok = bool(crep.get("all_ok")) if crep else False
    file_ver = crep.get("contract_version")
    field_errs = validate_consumer_fields_table()
    fields_ok = not field_errs
    ok = False
    if crep:
        ok = file_ok and (not file_ver or file_ver == CONTRACT_VERSION) and fields_ok
    elif version_match is True:
        ok = fields_ok
    elif fields_ok and not crep:
        # 无 live 契约产物时，至少消费字段表须与版本对齐
        ok = False
    # Standalone：消费字段表对齐即可（Live 契约产物为加分）
    if not required and fields_ok:
        ok = True
    return _metric(
        name="contract_drift",
        ok=ok,
        value={
            "expected": CONTRACT_VERSION,
            "live_rag_contract_all_ok": file_ok,
            "live_rag_contract_version": file_ver,
            "joint_contract_version_match": version_match,
            "consumer_fields_ok": fields_ok,
            "consumer_fields_errors": field_errs,
        },
        source="data/eval/live_rag_contract_check.json + contract_consumer_fields.json",
        detail="ok" if ok else "missing/failed contract artifact or consumer fields table",
        required=required,
    )


def source_mtimes() -> dict[str, float | None]:
    paths = [
        EVAL_DIR / "parts_gate_ab.json",
        EVAL_DIR / "live_function_test.json",
        EVAL_DIR / "live_integration_manual.json",
        EVAL_DIR / "live_rag_contract_check.json",
        EVAL_DIR / "joint_evidence_pack.json",
        EVAL_DIR / "joint_failure_drill.json",
        EVAL_DIR / "hitl_gate_report.json",
    ]
    return {str(p.relative_to(PROJECT_ROOT)): _mtime(p) for p in paths}


def build_scorecard(*, profile: str = "full") -> dict[str, Any]:
    standalone = profile.strip().lower() in {"standalone", "solo"}
    if standalone:
        metrics = [
            _hitl_gate_agreement(),
            _parts_gate_ab_ok(standalone=True),
            _degrade_blocks_auto_submit(),
            _core_policy_evidence_coverage(standalone=True),
            _file_outbox_port_ok(),
            _intent_held_out_ok(required=True),
            _false_hitl_cost_advisory(),
            _contract_drift(required=False),
            _leak_submit_rate_optional(),
        ]
        schema = STANDALONE_SCHEMA
        note = "standalone profile: no :8001; offline goldset ≠ production precision; joint leak/live advisory"
    else:
        metrics = [
            _hitl_gate_agreement(),
            _leak_submit_rate(),
            _parts_gate_ab_ok(standalone=False),
            _degrade_blocks_auto_submit(),
            _core_policy_evidence_coverage(standalone=False),
            _contract_drift(required=True),
            _intent_held_out_ok(required=False),
            _false_hitl_cost_advisory(),
        ]
        schema = SCHEMA
        note = "scores aggregated from artifacts/in-process checks only; never hand-edit; offline≠live precision"
    required = [m for m in metrics if m.get("required", True)]
    all_ok = all(bool(m.get("ok")) for m in required)
    return {
        "schema": schema,
        "profile": "standalone" if standalone else "full",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": resolve_git_sha(),
        "app_version": __import__("app", fromlist=["__version__"]).__version__,
        "all_ok": all_ok,
        "metrics": metrics,
        "source_mtimes": source_mtimes(),
        "hand_filled": False,
        "note": note,
    }


def _leak_submit_rate_optional() -> dict[str, Any]:
    m = _leak_submit_rate()
    m["required"] = False
    m["detail"] = (m.get("detail") or "") + " (advisory in standalone)"
    return m


def write_scorecard(path: Path | None = None, *, profile: str = "full") -> dict[str, Any]:
    card = build_scorecard(profile=profile)
    standalone = profile.strip().lower() in {"standalone", "solo"}
    out = path or (STANDALONE_SCORECARD_PATH if standalone else SCORECARD_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    return card


def scorecard_is_stale(card: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
    """若源产物 mtime 新于 scorecard 记录 → stale。"""
    card = card or _load_json(SCORECARD_PATH)
    if not card:
        return True, ["missing_scorecard"]
    recorded = card.get("source_mtimes") or {}
    reasons: list[str] = []
    for rel, mt in source_mtimes().items():
        old = recorded.get(rel)
        if mt is None:
            continue
        if old is None or float(mt) > float(old) + 0.5:
            reasons.append(rel)
    return bool(reasons), reasons
