"""联合故障注入 hardening（B4）。

默认可自动：degrade / retrieve_only / 低 grounding / 禁静默 DemoRag / probe lane（读产物）。
须人工停 :8001 的 503 探测：报告 `manual:true` + 步骤，**不得**在 RAG 仍可达时假称 probe 已绿。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "data" / "eval" / "joint_failure_drill.json"
EVAL = ROOT / "data" / "eval"


def _env_demo_live_linkage_ok() -> tuple[bool, dict[str, str]]:
    """演示档 .env.demo 为 SSOT；当前进程可能是 standalone，不因此判红。"""
    env_demo = ROOT / ".env.demo"
    lines: dict[str, str] = {}
    if env_demo.exists():
        for line in env_demo.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, _, v = s.partition("=")
            lines[k.strip()] = v.strip()
    require = lines.get("REQUIRE_LIVE", "0") in {"1", "true", "True"}
    block = lines.get("BLOCK_RUNS_WHEN_NOT_LIVE", "0") in {"1", "true", "True"}
    fallback_off = lines.get("RAG_AUTO_FALLBACK", "1") in {"0", "false", "False"}
    offline_off = lines.get("DEMO_OFFLINE", "1") in {"0", "false", "False"}
    ok = (require or block) and fallback_off and offline_off
    return ok, lines


def _scene_rag_unreachable(*, probe_live: bool) -> dict[str, Any]:
    from app.config import get_settings

    settings = get_settings()
    live_req = bool(
        settings.block_runs_when_not_live
        or settings.require_live
        or (not settings.rag_auto_fallback and not settings.demo_offline)
    )
    demo_ok, demo_lines = _env_demo_live_linkage_ok()
    # 未探针：以 .env.demo 配置层为准；探针时再看运行时 live_req + 503
    config_ok = demo_ok if not probe_live else (
        live_req and not settings.rag_auto_fallback and not settings.demo_offline
    )
    scene: dict[str, Any] = {
        "id": "rag_unreachable",
        "title": "RAG 不可达时不得静默开跑",
        "expected": "live 模式下 POST /runs → 503；rag_mode 诚实",
        "config_live_linkage_required": live_req,
        "rag_auto_fallback": bool(settings.rag_auto_fallback),
        "demo_offline": bool(settings.demo_offline),
        "env_demo_require_live": demo_lines.get("REQUIRE_LIVE"),
        "env_demo_block_runs": demo_lines.get("BLOCK_RUNS_WHEN_NOT_LIVE"),
        "ok": config_ok,
        "manual": False,
        "evidence": ".env.demo + app.config / rehearse_rag_failure",
    }
    if not probe_live:
        scene["manual"] = True
        scene["manual_steps"] = [
            "1. 停 enterprise-rag :8001",
            "2. python scripts/build_joint_failure_drill.py --probe-live",
            "3. 期望 probe_runs_status=503 且 probe_ok=true",
        ]
        scene["probe_note"] = "未 --probe-live：仅 .env.demo 配置断言；503 须人工停 RAG 后探测"
        return scene

    import httpx

    try:
        rag = httpx.get("http://127.0.0.1:8001/health", timeout=3.0)
        rag_up = rag.status_code == 200
    except Exception:  # noqa: BLE001
        rag_up = False
    scene["probe_rag_up"] = rag_up
    if not rag_up and live_req:
        try:
            r = httpx.post(
                "http://127.0.0.1:8002/runs",
                headers={"X-API-Key": "demo-technician", "Content-Type": "application/json"},
                json={"question": "SY215C H103请报修处理", "station": "长沙星沙服务站"},
                timeout=30.0,
            )
            scene["probe_runs_status"] = r.status_code
            scene["probe_ok"] = r.status_code == 503
            scene["ok"] = bool(config_ok and scene["probe_ok"])
            scene["manual"] = False
        except Exception as exc:  # noqa: BLE001
            scene["probe_error"] = str(exc)
            scene["ok"] = False
            scene["manual"] = False
    elif rag_up:
        # 不得假绿：配置可绿，但明确未完成 503 探针
        scene["manual"] = True
        scene["manual_steps"] = [
            "1. 停 enterprise-rag :8001",
            "2. 重跑本脚本 --probe-live",
            "3. 确认 POST /runs → 503",
        ]
        scene["probe_note"] = "RAG 当前可达；未执行 503 探针（非假绿）"
        scene["probe_ok"] = None
        scene["ok"] = config_ok  # 配置层仍可绿；探针层诚实留空
    return scene


def _scene_rag_degraded() -> dict[str, Any]:
    from app.policy.gates import evaluate_submit_eligible
    from app.policy.rules_catalog import tag

    state = {
        "intent": "fault_dispatch",
        "role": "technician",
        "auto_submit": True,
        "rag_degraded": True,
        "service_ticket": {"fault_codes": ["H103"], "station": "长沙星沙服务站"},
        "work_order_draft": {"draft": {"fault_codes": ["H103"]}},
        "critic_report": {
            "passed": True,
            "force_hitl": True,
            "reasons": [tag("POL-DEGRADE-01")],
            "policy_ids": ["POL-DEGRADE-01"],
        },
        "conflict_bundle": {},
        "parts_check": {"shortage": False},
        "hitl": {},
        "status": "running",
    }
    eligible, blockers = evaluate_submit_eligible(state)
    degrade_hit = any("POL-DEGRADE-01" in str(b) for b in blockers)
    return {
        "id": "rag_degraded",
        "title": "RAG degraded 禁 auto_submit 直提",
        "expected": "evaluate_submit_eligible → not eligible + POL-DEGRADE-01",
        "eligible": eligible,
        "blockers": list(blockers),
        "ok": (not eligible) and degrade_hit,
        "manual": False,
        "evidence": "app.policy.gates.evaluate_submit_eligible",
        "policy_ids": ["POL-DEGRADE-01"],
    }


def _scene_no_silent_demorag() -> dict[str, Any]:
    """演示档以 .env.demo 为 SSOT；当前进程可能是 standalone，不因此判红。"""
    from app.config import get_settings

    settings = get_settings()
    env_demo = ROOT / ".env.demo"
    demo_fallback_line = ""
    demo_offline_line = ""
    if env_demo.exists():
        for line in env_demo.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("RAG_AUTO_FALLBACK"):
                demo_fallback_line = s
            elif s.startswith("DEMO_OFFLINE"):
                demo_offline_line = s
    demo_fallback_ok = "RAG_AUTO_FALLBACK=0" in demo_fallback_line
    demo_offline_ok = "DEMO_OFFLINE=0" in demo_offline_line
    file_ok = demo_fallback_ok and demo_offline_ok
    runtime_advisory = (not settings.rag_auto_fallback) or demo_fallback_ok
    return {
        "id": "no_silent_demorag",
        "title": "禁止静默 DemoRag 冒充联调",
        "expected": "RAG_AUTO_FALLBACK=0 且 DEMO_OFFLINE=0（演示档 .env.demo）",
        "rag_auto_fallback": bool(settings.rag_auto_fallback),
        "demo_offline": bool(settings.demo_offline),
        "env_demo_line": demo_fallback_line or None,
        "env_demo_offline_line": demo_offline_line or None,
        "ok": file_ok,
        "manual": False,
        "evidence": ".env.demo (演示档 SSOT)",
        "advisory_ok_if_dev_fallback": runtime_advisory,
    }


def _scene_retrieve_only_forces_hitl() -> dict[str, Any]:
    """B4：retrieve_only → waiting_hitl + POL-DEGRADE-01，禁静默 succeeded+submit。"""
    from app.graph.runner import create_initial_state, run_until_pause
    from app.tools.eval_stub import EvalRagStub

    payload = {
        "answer": "检索摘要（生成降级）",
        "sources": [{"chunk": {"source": "故障码对照表.txt", "text": "H103"}, "score": 0.8}],
        "grounded": True,
        "grounding_score": 0.7,
        "blocked": False,
        "retrieve_only": True,
        "conflicts": [],
    }
    st = create_initial_state(
        "长沙星沙 SY215C H103请报修处理",
        api_key="demo-technician",
        station="长沙星沙服务站",
        parts_force_hints=["液压滤芯"],
        auto_submit=True,
        engine="langgraph",
    )
    client = EvalRagStub(
        ask_payload=payload,
        parts=["液压滤芯"],
        ticket_id="T-DEMO-1",
        request_id="fake-req",
    )
    out = run_until_pause(st, client=client, persist=False)
    status = out.get("status")
    critic = out.get("critic_report") or {}
    policies = list(critic.get("policy_ids") or [])
    reasons = " ".join((out.get("hitl") or {}).get("reasons") or [])
    ok = (
        status == "waiting_hitl"
        and ("POL-DEGRADE-01" in policies or "POL-DEGRADE-01" in reasons)
        and not out.get("work_order_submit")
    )
    return {
        "id": "retrieve_only_forces_hitl",
        "title": "retrieve_only → HITL，不得直提",
        "expected": "waiting_hitl + POL-DEGRADE-01；无 work_order_submit",
        "status": status,
        "policy_ids": policies,
        "submit_present": bool(out.get("work_order_submit")),
        "ok": ok,
        "manual": False,
        "evidence": "FakeRag retrieve_only + run_until_pause",
    }


def _scene_low_grounding_no_silent_submit() -> dict[str, Any]:
    """B4：低 grounding 故障开单不得静默成功提交。"""
    from app.graph.runner import create_initial_state, run_until_pause
    from app.tools.eval_stub import EvalRagStub

    payload = {
        "answer": "依据不足",
        "sources": [],
        "grounded": False,
        "grounding_score": 0.1,
        "blocked": False,
        "conflicts": [],
    }
    st = create_initial_state(
        "长沙星沙 SY215C H103请报修处理",
        api_key="demo-technician",
        station="长沙星沙服务站",
        auto_submit=True,
        engine="langgraph",
    )
    client = EvalRagStub(ask_payload=payload, ticket_id="T-DEMO-1", request_id="fake-req")
    out = run_until_pause(st, client=client, persist=False)
    status = out.get("status")
    # 硬拒 rejected 或 waiting_hitl 均可；禁止 succeeded 且已 submit
    silent_leak = status == "succeeded" and bool(out.get("work_order_submit"))
    ok = (not silent_leak) and status in {"rejected", "waiting_hitl", "failed"}
    return {
        "id": "low_grounding_no_silent_submit",
        "title": "低 grounding 不得静默落箱",
        "expected": "status∈{rejected,waiting_hitl,failed} 且无成功 submit",
        "status": status,
        "submit_present": bool(out.get("work_order_submit")),
        "ok": ok,
        "manual": False,
        "evidence": "FakeRag grounded=false + run_until_pause",
    }


def _scene_probe_lane_isolation() -> dict[str, Any]:
    """B4：探针≠业务箱（读既有严档/契约产物；缺则失败，不假绿）。"""
    strict = {}
    crep = {}
    sp = EVAL / "demo_strict_submit_check.json"
    cp = EVAL / "live_rag_contract_check.json"
    if sp.exists():
        try:
            strict = json.loads(sp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            strict = {}
    if cp.exists():
        try:
            crep = json.loads(cp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            crep = {}

    # 与 synergy_checks 对齐：skipped / 空 checks（如 RAG 不可达残片）不阻断，回退 contract
    if strict and not strict.get("skipped") and (strict.get("checks") or {}):
        checks = strict.get("checks") or {}
        red = checks.get("red_no_token_403") or {}
        probe = checks.get("probe_without_token_200") or {}
        green = checks.get("green_copilot_approve") or {}
        ok = bool(
            strict.get("all_ok") and red.get("ok") and probe.get("ok") and green.get("ok")
        )
        return {
            "id": "probe_lane_isolation",
            "title": "探针 submit 不得进业务 lane",
            "expected": "demo_strict_submit：无 token 业务 403；probe 200；绿路径 inbox",
            "ok": ok,
            "manual": False,
            "source": "data/eval/demo_strict_submit_check.json",
            "evidence": "scripts/demo_strict_submit_check.py",
        }
    if crep:
        return {
            "id": "probe_lane_isolation",
            "title": "探针 submit 不得进业务 lane",
            "expected": "live_rag_contract_check all_ok（含 probe 归属）",
            "ok": bool(crep.get("all_ok")),
            "manual": False,
            "source": "data/eval/live_rag_contract_check.json",
            "evidence": "scripts/live_rag_contract_check.py",
        }
    return {
        "id": "probe_lane_isolation",
        "title": "探针 submit 不得进业务 lane",
        "expected": "须有 demo_strict_submit_check 或 live_rag_contract_check",
        "ok": False,
        "manual": False,
        "source": None,
        "skip_reason": "missing probe isolation artifacts",
        "evidence": "run demo_strict_submit_check or live_rag_contract_check",
    }


def build_drill(*, probe_live: bool = False) -> dict[str, Any]:
    scenes = [
        _scene_rag_unreachable(probe_live=probe_live),
        _scene_rag_degraded(),
        _scene_no_silent_demorag(),
        _scene_retrieve_only_forces_hitl(),
        _scene_low_grounding_no_silent_submit(),
        _scene_probe_lane_isolation(),
    ]
    # required = 非 manual 或 manual 但配置层 ok；manual 场景不因「未探针」而整包红
    required_ids = {
        "rag_degraded",
        "no_silent_demorag",
        "retrieve_only_forces_hitl",
        "low_grounding_no_silent_submit",
        "probe_lane_isolation",
        "rag_unreachable",  # 配置层 ok 即可；探针单独字段
    }
    required_ok = all(bool(s.get("ok")) for s in scenes if s.get("id") in required_ids)
    return {
        "schema": "joint_failure_drill/v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "all_ok": required_ok,
        "scenes": scenes,
        "aligned_with": ["PLAN_B.md", "scripts/rehearse_rag_failure.py", "B4 hardening"],
        "note": (
            "自动幕：degrade/retrieve_only/低 grounding/禁静默/probe lane；"
            "503 须人工停 RAG + --probe-live，报告 manual=true，禁止假绿"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build joint failure drill artifact")
    parser.add_argument("--probe-live", action="store_true", help="probe 503 when RAG down")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    drill = build_drill(probe_live=args.probe_live)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(drill, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {path} all_ok={drill.get('all_ok')} schema={drill.get('schema')}")
    for s in drill.get("scenes") or []:
        flag = "OK" if s.get("ok") else "FAIL"
        man = " manual" if s.get("manual") else ""
        print(f"  [{flag}]{man} {s.get('id')}")
    return 0 if drill.get("all_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
