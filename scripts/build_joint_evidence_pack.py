"""构建跨仓联合证据包（Portfolio）。

--live（默认推荐）  探测 :8001/:8002，抽样 P1
  · 真 RAG+模型 → evidence_tier=L2；仅此时可 live_verified=true
  · 契约 stub   → evidence_tier=L1；l1_verified 可见；live_verified 永 false
--from-artifacts    仅合并已有 JSON；evidence_tier=artifacts；永不可称 L2

分层口径：app/eval/evidence_tier.py
输出：data/eval/joint_evidence_pack.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "eval" / "joint_evidence_pack.json"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _build_from_artifacts() -> dict:
    from app.eval.parts_gate_ab import nest_parts_gate_ab
    from app.eval.ssot import PYTEST_FULL_COLLECT, PYTEST_OFFLINE_COLLECT
    from app.policy.rules_catalog import CORE_POLICIES, POLICY_CATALOG_VERSION

    manual = _load_json(ROOT / "data" / "eval" / "live_integration_manual.json")
    func = _load_json(ROOT / "data" / "eval" / "live_function_test.json")
    parts_ab = _load_json(ROOT / "data" / "eval" / "parts_gate_ab.json")
    # artifacts-only：禁止把 stub 写成 Live 反证
    nested = nest_parts_gate_ab(
        offline={
            "present": bool(parts_ab),
            "all_ok": bool(parts_ab.get("all_ok")),
            "rag_mode": parts_ab.get("rag_mode") or "fakerag_stub",
            "schema": parts_ab.get("schema"),
        }
        if parts_ab
        else {"present": False, "all_ok": False},
        live={
            "present": False,
            "all_ok": False,
            "rag_mode": "live",
            "skip_reason": "from_artifacts_only_no_live_ab",
        },
    )
    from app.eval.ssot import resolve_git_sha

    return {
        "schema": "joint_evidence_pack/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": resolve_git_sha(),
        "mode": "from_artifacts",
        "evidence_tier": "artifacts",
        # 铁律：快照路径永不可 live_verified（忽略入参，防误传 True）
        "live_verified": False,
        "l1_verified": False,
        "portfolio_claimable": False,
        "parts_gate_ab_live_ok": False,
        "portfolio_warning": (
            "artifacts_only：仅合并历史 live_*.json，未当场探测 :8001/:8002。"
            "evidence_tier=artifacts，永不可称 L2；请 --live（L2）或 run_l1_linkage（L1）。"
        ),
        "hosts": {"rag": "http://127.0.0.1:8001", "copilot": "http://127.0.0.1:8002"},
        "narrative": {
            "enterprise_rag": "知识是否可看、是否冲突、草稿是否有据（ACL / citations / draft）",
            "copilot": "在有据前提下谁能开单、缺料/冲突/降级是否必须人确；提交仅为 rag_mock_inbox",
            "not_erp": "is_production_ticket=false · 不做技师派工/排班",
            "main_demo": ["P1 POL-PARTS-01", "P8 角色脱敏+冲突", "A-07 裸链漏 HITL"],
            "ui_roles": {
                "rag_ui": "售后知识治理 Copilot :8501（开发者）",
                "copilot_ui": "报修开单门禁 Copilot :8502（开发者，非站长作业 App）",
            },
            "inbox_ownership": "RAG=落箱能力；仅 Copilot 站长批准后 submit；探针≠业务路径",
            "student_data": "台账/站务为演示主数据；可起 mock_parts_wms，非主机厂生产库",
        },
        "policy_catalog_version": POLICY_CATALOG_VERSION,
        "core_policies": list(CORE_POLICIES),
        "interview_core_policies": list(CORE_POLICIES),
        "acceptance_layers": {
            "L0_pytest_fakerag": "offline orchestration only; not HTTP linkage",
            "L1_compose_contract": "linkage-l1.yml / docker-compose.joint.yml；证契约不证检索",
            "L2_live_rag": "live-linkage.yml self-hosted/dispatch；须 live_verified",
            "pytest_offline_collect": PYTEST_OFFLINE_COLLECT,
            "pytest_full_collect": PYTEST_FULL_COLLECT,
            "live_json": "necessary but not sufficient without live_verified + evidence_tier=L2",
            "ci_l2_live": "live-linkage.yml default off (no GH-hosted Ollama)",
            "from_artifacts": "never L2",
        },
        "live_integration_manual": {
            "all_ok": manual.get("all_ok"),
            "passed": manual.get("passed"),
            "total": manual.get("total"),
            "script_version": manual.get("script_version"),
            "checklist_hash": manual.get("checklist_hash"),
        },
        "live_function_test": {
            "all_ok": func.get("all_ok"),
            "passed": func.get("passed"),
            "total": func.get("total"),
            "script_version": func.get("script_version"),
            "checklist_hash": func.get("checklist_hash"),
        },
        "parts_gate_ab": nested,
        "hard_claims": {
            "rag_mode_required": "live",
            "destination": "rag_mock_inbox",
            "is_production_ticket": False,
            "not_erp_dispatch": True,
            "decision_certificate_schema": "decision_certificate/v1",
            "decision_certificate_assurance": "state_snapshot_not_tamper_proof",
            "standalone_ne_live": True,
            "token_is_demo_ownership_not_prod_auth": True,
            "plan_b_not_live_evidence": True,
            "from_artifacts_not_live_evidence": True,
        },
        "claim_rules": {
            "standalone_green": "门禁仓可独立验收",
            "design_ready": "协同设计已落地（未验证 Live）",
            "l1_ok": "evidence_tier=L1 且 l1_verified=true → 可宣称 CI/Compose HTTP 契约联调",
            "live_ok": "仅 evidence_tier=L2 且 live_verified=true 且 portfolio_claimable=true 可宣称本机 Live",
            "forbidden": [
                "pytest FakeRag = Live / L2",
                "L1 stub = live_verified / 检索质量",
                "Plan B / from_artifacts = 联调通过 / L2",
                "token/source = 生产鉴权",
                "Standalone 绿顶 Live 绿",
            ],
        },
        "portfolio_do_not_attach": [
            "smoke_report.json",
            "compare_report.json as live evidence",
            "from_artifacts pack without live_verified",
            "parts_gate_ab.offline as live reverse-proof",
            "l1_linkage_report as L2 live_verified",
        ],
        "governance_scorecard_ref": "data/eval/governance_scorecard.json",
        "joint_failure_drill_ref": "data/eval/joint_failure_drill.json",
    }


def _enrich_live(pack: dict) -> dict:
    import httpx

    from app.eval.evidence_tier import enforce_pack_tier_rules, tier_from_rag_health
    from app.eval.parts_gate_ab import nest_parts_gate_ab, run_parts_gate_ab, run_parts_gate_ab_live
    from app.eval.ssot import resolve_git_sha

    tech = {"X-API-Key": "demo-technician"}
    pack["live_verified"] = False
    pack["l1_verified"] = False
    pack["portfolio_claimable"] = False
    pack["parts_gate_ab_live_ok"] = False
    pack["git_sha"] = resolve_git_sha()
    pack["hosts"] = {"rag": "http://127.0.0.1:8001", "copilot": "http://127.0.0.1:8002"}
    try:
        rag = httpx.get("http://127.0.0.1:8001/health", timeout=5.0)
        pack["live_probe"] = {
            "rag_health": rag.status_code == 200,
        }
        if rag.status_code == 200:
            try:
                rh = rag.json()
                pack["live_probe"]["consumer_contract_version_supported"] = rh.get(
                    "consumer_contract_version_supported"
                )
                pack["live_probe"]["rag_mode"] = rh.get("mode")
                pack["live_probe"]["rag_evidence_tier"] = rh.get("evidence_tier")
                pack["evidence_tier"] = tier_from_rag_health(rh if isinstance(rh, dict) else {})
            except Exception:  # noqa: BLE001
                pack["evidence_tier"] = "L2"
        else:
            pack["evidence_tier"] = "L2"
    except Exception as exc:  # noqa: BLE001
        pack["live_probe"] = {"rag_health": False, "error": str(exc)}
        pack["portfolio_warning"] = "live probe failed: RAG unreachable"
        pack["evidence_tier"] = pack.get("evidence_tier") or "L2"
        return enforce_pack_tier_rules(pack)

    try:
        from app.tools.rag_contract import CONTRACT_VERSION

        h = httpx.get("http://127.0.0.1:8002/health", headers=tech, timeout=15.0)
        body = h.json() if h.status_code == 200 else {}
        pack["live_probe"]["copilot_rag_mode"] = body.get("rag_mode")
        pack["live_probe"]["demo_mode_warning"] = body.get("demo_mode_warning")
        pack["live_probe"]["live_eval_all_ok"] = body.get("live_eval_all_ok")
        pack["live_probe"]["parts_ledger_sha256"] = body.get("parts_ledger_sha256")
        pack["live_probe"]["rag_contract_version"] = body.get("rag_contract_version")
        supported = pack["live_probe"].get("consumer_contract_version_supported")
        copilot_cv = body.get("rag_contract_version")
        version_ok = supported == CONTRACT_VERSION and copilot_cv == CONTRACT_VERSION
        pack["live_probe"]["contract_version_match"] = bool(version_ok)
        pack["live_probe"]["expected_contract_version"] = CONTRACT_VERSION
    except Exception as exc:  # noqa: BLE001
        pack["live_probe"]["copilot_error"] = str(exc)
        pack["portfolio_warning"] = "live probe failed: Copilot unreachable"
        return enforce_pack_tier_rules(pack)

    if not pack["live_probe"].get("contract_version_match"):
        pack["portfolio_warning"] = (
            "contract version mismatch — 不得 live_verified/claimable "
            f"(RAG={pack['live_probe'].get('consumer_contract_version_supported')!r} "
            f"Copilot={pack['live_probe'].get('rag_contract_version')!r} "
            f"expected={pack['live_probe'].get('expected_contract_version')!r})"
        )
        pack["live_verified"] = False
        pack["portfolio_claimable"] = False
        return enforce_pack_tier_rules(pack)

    if pack["live_probe"].get("copilot_rag_mode") != "live":
        pack["portfolio_warning"] = "copilot rag_mode≠live — 不得宣称真联调"
        return enforce_pack_tier_rules(pack)

    try:
        from app.policy.hitl_layers import confirmations_covering

        p1 = httpx.post(
            "http://127.0.0.1:8002/playbooks/p1_xingsha_h103/run",
            headers=tech,
            timeout=180.0,
        )
        p1b = p1.json() if p1.status_code == 200 else {}
        cert = p1b.get("decision_certificate") or {}
        policy_ids = list(cert.get("policy_ids") or [])
        sample = {
            "status": p1b.get("status"),
            "rag_client_mode": p1b.get("rag_client_mode"),
            "certificate_phase": cert.get("phase"),
            "certificate_assurance": cert.get("assurance"),
            "policy_ids": policy_ids,
            "policy_catalog_version": cert.get("policy_catalog_version"),
            "is_production_ticket": cert.get("is_production_ticket"),
            "hints_source": (p1b.get("parts_check") or {}).get("hints_source"),
            "demo_injected_hints": (p1b.get("parts_check") or {}).get("demo_injected_hints"),
            "shortage": bool((p1b.get("parts_check") or {}).get("shortage")),
        }
        run_id = p1b.get("run_id")
        if p1b.get("status") == "waiting_hitl" and run_id:
            pending = list((p1b.get("hitl") or {}).get("pending_layers") or [])
            chief = {"X-API-Key": "demo-chief", "Content-Type": "application/json"}
            hitl = httpx.post(
                f"http://127.0.0.1:8002/runs/{run_id}/hitl",
                headers=chief,
                json={
                    "decision": "approve",
                    "note": "joint_evidence_pack",
                    "confirmations": confirmations_covering(pending),
                },
                timeout=180.0,
            )
            hb = hitl.json() if hitl.status_code == 200 else {}
            rc = hb.get("decision_certificate") or {}
            submit = hb.get("work_order_submit") or {}
            sample["after_approve"] = {
                "status": hb.get("status"),
                "destination": submit.get("destination"),
                "is_production_ticket": submit.get("is_production_ticket"),
                "certificate_phase": rc.get("phase"),
                "ticket_id": rc.get("ticket_id") or submit.get("ticket_id"),
                "submitted_by": submit.get("submitted_by"),
                "source": submit.get("source"),
                "run_id": submit.get("run_id") or run_id,
            }
            # E4 L2：业务落箱归属（RAG 持久化，不依赖 note）
            tid = sample["after_approve"].get("ticket_id")
            if tid:
                try:
                    detail = httpx.get(
                        f"http://127.0.0.1:8001/work-orders/inbox/{tid}",
                        headers={"X-API-Key": "demo-key"},
                        timeout=60.0,
                    )
                    if detail.status_code == 200:
                        d = detail.json()
                        sample["after_approve"]["inbox_source"] = d.get("source")
                        sample["after_approve"]["inbox_run_id"] = d.get("run_id")
                except Exception as exc:  # noqa: BLE001
                    sample["after_approve"]["inbox_ownership_error"] = str(exc)
        pack["live_sample_p1"] = sample
        pack["mode"] = "live"
        # E2：P1 sample 必须含 POL-PARTS-01（缺料主叙事）
        ok_sample = (
            sample.get("rag_client_mode") == "live"
            and sample.get("status") in {"waiting_hitl", "succeeded"}
            and "POL-PARTS-01" in (sample.get("policy_ids") or [])
        )
        aa = sample.get("after_approve") or {}
        if aa:
            ok_ownership = (
                aa.get("source") == "copilot_hitl"
                and bool(aa.get("run_id"))
                and aa.get("inbox_source") == "copilot_hitl"
                and bool(aa.get("inbox_run_id"))
            )
            sample["ownership_ok"] = ok_ownership
        else:
            sample["ownership_ok"] = None
            ok_ownership = False  # 未跑到 approve→submit 则不得宣称完整联调落箱
        pack["live_sample_p1"] = sample

        # offline A/B（回归安全网）
        parts_path = ROOT / "data" / "eval" / "parts_gate_ab.json"
        parts_ab = _load_json(parts_path)
        if not parts_ab.get("all_ok"):
            try:
                parts_ab = run_parts_gate_ab()
                parts_path.write_text(
                    json.dumps(parts_ab, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception as exc:  # noqa: BLE001
                parts_ab = {"all_ok": False, "error": str(exc), "rag_mode": "fakerag_stub"}

        # live A/B（联调深度；禁止 stub 冒充）
        live_ab = run_parts_gate_ab_live()
        nested = nest_parts_gate_ab(
            offline={
                "present": True,
                "all_ok": bool(parts_ab.get("all_ok")),
                "rag_mode": parts_ab.get("rag_mode") or "fakerag_stub",
                "schema": parts_ab.get("schema"),
            },
            live=live_ab,
        )
        pack["parts_gate_ab"] = nested
        ok_parts_offline = bool(parts_ab.get("all_ok"))
        ok_parts_live = bool(live_ab.get("present") and live_ab.get("all_ok"))
        pack["parts_gate_ab_live_ok"] = ok_parts_live
        is_l1 = pack.get("evidence_tier") == "L1"
        # L1：契约闭环即可 l1_verified；永不可 live_verified（不要求 parts live A/B）
        # L2：portfolio_claimable 仍要求 offline；live_verified 另要求 live A/B + P1 + 归属
        if is_l1:
            pack["l1_verified"] = bool(ok_sample and ok_ownership)
            pack["portfolio_claimable"] = bool(pack["l1_verified"] and ok_parts_offline)
            pack["live_verified"] = False
            pack["parts_gate_ab_live_ok"] = False  # L1 stub 不证 live A/B
            if not ok_sample:
                pack["portfolio_warning"] = (
                    "L1 P1 sample incomplete / missing POL-PARTS-01"
                )
            elif not ok_ownership:
                pack["portfolio_warning"] = (
                    "L1 approve→submit 归属未闭环（inbox source=copilot_hitl + run_id）"
                )
            else:
                pack["portfolio_warning"] = (
                    "evidence_tier=L1：可宣称 HTTP 契约联调；不得宣称 live_verified / 检索质量"
                )
        else:
            pack["evidence_tier"] = "L2"
            pack["l1_verified"] = False
            pack["portfolio_claimable"] = bool(ok_sample and ok_parts_offline)
            pack["live_verified"] = bool(
                ok_sample and ok_parts_offline and ok_parts_live and ok_ownership
            )
            if not ok_sample:
                if "POL-PARTS-01" not in (sample.get("policy_ids") or []):
                    pack["portfolio_warning"] = "P1 sample missing POL-PARTS-01（件号漂移或台账缓存？）"
                else:
                    pack["portfolio_warning"] = "P1 sample incomplete"
            elif not ok_ownership:
                pack["portfolio_warning"] = (
                    "approve→submit 归属未闭环（需 inbox source=copilot_hitl + run_id；E4 L2）"
                )
            elif not ok_parts_offline:
                pack["portfolio_warning"] = "parts_gate_ab.offline not all_ok — run scripts/parts_gate_ab_test.py"
            elif not ok_parts_live:
                pack["portfolio_warning"] = "parts_gate_ab.live not all_ok — check :8001/:8002 + ledger align"
            else:
                pack["portfolio_warning"] = None
    except Exception as exc:  # noqa: BLE001
        pack["live_probe"]["sample_error"] = str(exc)
        pack["portfolio_warning"] = f"live sample error: {exc}"
    return enforce_pack_tier_rules(pack)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="联合证据包。推荐 --live；--from-artifacts 仅历史摘要。"
    )
    parser.add_argument(
        "--from-artifacts",
        action="store_true",
        help="仅合并 JSON；live_verified=false，不可单独作联调证据",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="探测 :8001/:8002 并抽样 P1（推荐；无参数时默认等同 --live）",
    )
    args = parser.parse_args()

    # 无参数或显式 --live → 当场探测；仅 --from-artifacts → 降级包
    use_live = args.live or not args.from_artifacts
    if args.from_artifacts and args.live:
        use_live = True

    from app.eval.evidence_tier import enforce_pack_tier_rules
    from app.eval.synergy_checks import apply_synergy_to_claimability

    pack = _build_from_artifacts()
    if use_live:
        pack = _enrich_live(pack)
    else:
        pack["mode"] = "from_artifacts"
        pack["evidence_tier"] = "artifacts"

    pack = apply_synergy_to_claimability(pack)
    pack = enforce_pack_tier_rules(pack)
    # 索引治理产物（不手填分数）
    scorecard = _load_json(ROOT / "data" / "eval" / "governance_scorecard.json")
    drill = _load_json(ROOT / "data" / "eval" / "joint_failure_drill.json")
    pack["governance_scorecard"] = {
        "present": bool(scorecard),
        "all_ok": bool(scorecard.get("all_ok")) if scorecard else False,
        "generated_at": scorecard.get("generated_at"),
    }
    pack["joint_failure_drill"] = {
        "present": bool(drill),
        "all_ok": bool(drill.get("all_ok")) if drill else False,
        "generated_at": drill.get("generated_at"),
    }
    # B5：正式读取 RAG baseline 摘要数字；禁止综合分 / 抢 MRR
    from app.eval.rag_baseline_index import build_rag_eval_index

    pack["rag_eval_index"] = build_rag_eval_index()
    acl_matrix = _load_json(ROOT / "data" / "eval" / "acl_matrix.json")
    pack["acl_matrix"] = {
        "present": bool(acl_matrix),
        "all_ok": bool(acl_matrix.get("all_ok")) if acl_matrix else False,
        "matrix": acl_matrix.get("matrix") if acl_matrix else None,
        "generated_at": acl_matrix.get("generated_at"),
        "ref": "data/eval/acl_matrix.json",
    }
    fb = _load_json(ROOT / "data" / "eval" / "feedback_roundtrip.json")
    pack["feedback_roundtrip"] = {
        "present": bool(fb),
        "all_ok": bool(fb.get("all_ok")) if fb else False,
        "required_for_claimable": False,
        "offline_ok": bool((fb.get("offline") or {}).get("ok")) if fb else False,
        "live_ok": fb.get("live_ok") if fb else None,
        "ref": "data/eval/feedback_roundtrip.json",
        "note": "advisory B6：degraded→down 按 run_id 回读；不挡 claimable",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    syn = pack.get("synergy_checks") or {}
    print(
        f"tier={pack.get('evidence_tier')} live_verified={pack.get('live_verified')} "
        f"l1_verified={pack.get('l1_verified')} claimable={pack.get('portfolio_claimable')} "
        f"parts_ab_live={pack.get('parts_gate_ab_live_ok')} "
        f"synergy_required_ok={syn.get('required_ok')} "
        f"mode={pack.get('mode')} warning={pack.get('portfolio_warning')!r}"
    )
    if pack.get("evidence_tier") == "L1":
        print("NOTE: evidence_tier=L1 — HTTP contract only; NOT live_verified / NOT retrieval quality")
    elif not pack.get("live_verified"):
        print("NOTE: pack is NOT live-verified; re-run with real RAG+model: --live")
    return 0 if pack.get("live_verified") or pack.get("l1_verified") or args.from_artifacts else 1


if __name__ == "__main__":
    raise SystemExit(main())
