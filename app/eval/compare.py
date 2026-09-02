from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, get_settings
from app.graph.nodes import classify_intent
from app.graph.runner import create_initial_state, run_until_pause
from app.policy.gates import evaluate_submit_eligible

# 演示口语：报修开单话术（不做派工调度）。现场「派人/上门」仍可由 intent_rules 识别，但不进本列表。
ORAL_SMOKE_QUESTIONS = [
    "SY215C 大臂抬不起来，星沙站帮忙报修开单",
    "客户说动臂没劲，H103 亮了，星沙站",
    "长沙星沙 SY215 液压异响挺大，先开单报修",
    "泵车大臂发软，码是 H103 那个",
    "SY215 动臂抬升缓慢，没有故障码显示",
    "客户说液压泵响得厉害，星沙站帮忙开单",
    "星沙这边泵车转台卡死了，麻烦报修处理瞅瞅",
    "榔梨工地 SY215C 动作慢，你们帮忙开单报修",
    "动臂抬不高，客户催得紧，星沙站赶紧报修处理",
    "这台挖机液压无力，没亮码，星沙服务站接一下",
    "SY215 油缸漏油，星沙站先开单安排排查",
    "转台回转有问题，星沙这边请站长确认开单",
    "大臂沉降明显，215 客户要报修，星沙站开单",
    "泵车发软厉害，经开那边有没有件，先报个修",
    "客户讲动臂卡顿，星沙站帮忙开单排查一下",
    "液压泵响得凶，SY215C，星沙站报修开单",
    "星沙站 215 没劲，帮忙开单报修处理",
    "动臂没力，客户在榔梨等，星沙站报修开单",
    "星沙那边车子抬臂慢，客户催得紧",
]


def _oral_intent_pass_rate() -> tuple[float, list[dict[str, Any]]]:
    results = []
    for q in ORAL_SMOKE_QUESTIONS:
        intent = classify_intent(q)
        ok = intent == "fault_dispatch"
        results.append({"question": q, "intent": intent, "passed": ok})
    passed = sum(1 for r in results if r["passed"])
    rate = round(passed / max(len(results), 1), 3)
    return rate, results


def _fake_client_for_eval():
    from app.tools.eval_stub import EvalRagStub

    return EvalRagStub(ticket_id="T-EVAL")


def simulate_single_tool(question: str, *, live_rag: bool = False, use_local_intent: bool = True) -> dict[str, Any]:
    """模拟 naive 单工具链：/ask →（故障则）/draft → /submit，无 Copilot 门禁与人确。

    use_local_intent=False 时跳过 classify，纯 HTTP 直通（A-07 更干净 baseline）。
    """
    intent = classify_intent(question) if use_local_intent else "fault_dispatch"
    if intent in {"chitchat", "injection"}:
        return {
            "mode": "single_tool",
            "intent": intent,
            "would_submit_without_hitl": False,
            "skipped_hitl": False,
            "acl_leak_risk": False,
            "traj_ok": False,
            "status": "rejected_local",
        }

    if live_rag:
        from app.tools.rag_client import RagClient

        client: Any = RagClient(api_key="demo-technician")
    else:
        client = _fake_client_for_eval()

    try:
        result = client.ask(question, knowledge_base="demo-kb", role="technician")
    except Exception as exc:  # noqa: BLE001
        return {
            "mode": "single_tool",
            "intent": intent,
            "would_submit_without_hitl": False,
            "skipped_hitl": False,
            "acl_leak_risk": intent == "acl_probe",
            "traj_ok": False,
            "status": "failed",
            "error": str(exc),
        }

    blocked = bool(result.get("blocked"))
    if intent == "acl_probe":
        return {
            "mode": "single_tool",
            "intent": intent,
            "would_submit_without_hitl": False,
            "skipped_hitl": not blocked,
            "acl_leak_risk": not blocked,
            "traj_ok": False,
            "status": "blocked" if blocked else "answered",
        }

    would_submit = False
    if intent == "fault_dispatch" and not blocked:
        try:
            client.draft_work_order(
                question,
                knowledge_base="demo-kb",
                answer=str(result.get("answer") or ""),
                role="technician",
                sources=[s for s in (result.get("sources") or []) if isinstance(s, dict)],
            )
            would_submit = True
        except Exception:
            would_submit = False

    skipped_hitl = intent in {"fault_dispatch", "conflict_review"} and not blocked
    return {
        "mode": "single_tool",
        "intent": intent,
        "would_submit_without_hitl": would_submit,
        "skipped_hitl": skipped_hitl,
        "acl_leak_risk": False,
        "traj_ok": False,
        "status": "would_submit" if would_submit else ("answered" if not blocked else "blocked"),
    }


def would_submit_without_hitl(out: dict[str, Any]) -> bool:
    """误开单标志：已 submit 且未经站长 approve——由运行结果推导，禁止写死。"""
    hitl = out.get("hitl") or {}
    return bool(out.get("work_order_submit")) and not (
        bool(hitl.get("resolved")) and hitl.get("decision") == "approve"
    )


def simulate_copilot(
    question: str,
    *,
    api_key: str = "demo-technician",
    live_rag: bool = False,
    engine: str = "langgraph",
    auto_submit: bool = False,
) -> dict[str, Any]:
    state = create_initial_state(question, api_key=api_key, engine=engine, auto_submit=auto_submit)
    if live_rag:
        from app.tools.rag_client import RagClient

        client: Any = RagClient(api_key=api_key)
    else:
        client = _fake_client_for_eval()
    out = run_until_pause(state, client=client, persist=False)  # type: ignore[arg-type]
    eligible, blockers = evaluate_submit_eligible(out)
    nodes = [e.get("node") for e in (out.get("trace_events") or [])]
    expect_prefix = ["supervisor", "rag", "quality"]
    traj_ok = all(n in nodes for n in expect_prefix) or out.get("status") == "rejected"
    would_submit = would_submit_without_hitl(out)
    return {
        "mode": "copilot",
        "intent": out.get("intent"),
        "status": out.get("status"),
        "waiting_hitl": out.get("status") == "waiting_hitl",
        "would_submit_without_hitl": would_submit,
        "submit_eligible": eligible,
        "blockers": blockers,
        "skipped_hitl": out.get("status") not in {"waiting_hitl", "rejected"}
        and out.get("intent") in {"fault_dispatch", "conflict_review"},
        "acl_leak_risk": out.get("intent") == "acl_probe" and out.get("status") != "rejected",
        "trace_nodes": nodes,
        "traj_ok": traj_ok,
        "engine": engine,
        "rag_linkage": out.get("rag_linkage") or [],
    }


def _load_compare_rows() -> list[dict[str, Any]]:
    """合并 baseline、cases.jsonl（routing/e2e）与 playbook 问题，去重。"""
    rows: list[dict[str, Any]] = []
    seen_questions: set[str] = set()

    baseline = Path(get_settings().playbooks_dir).parent / "eval" / "baseline_single_tool.jsonl"
    if baseline.exists():
        for line in baseline.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                q = str(row.get("question") or "")
                if q and q not in seen_questions:
                    rows.append(row)
                    seen_questions.add(q)

    cases_path = Path(get_settings().playbooks_dir).parent / "eval" / "cases.jsonl"
    if cases_path.exists():
        for line in cases_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            case = json.loads(line)
            bucket = case.get("bucket")
            q = case.get("question")
            if bucket == "e2e" and case.get("playbook"):
                try:
                    from app.playbooks.validate import load_playbook

                    pb = load_playbook(str(case["playbook"]))
                    q = pb.get("question")
                except Exception:
                    q = None
            if not q or q in seen_questions:
                continue
            if bucket in {"routing", "e2e"} or case.get("expect_intent") in {
                "fault_dispatch",
                "conflict_review",
                "acl_probe",
            }:
                rows.append({"id": case.get("id"), "question": q, "source": bucket})
                seen_questions.add(str(q))

    return rows


def compare_cases(
    limit: int | None = None,
    live_rag: bool = False,
    engine: str = "langgraph",
    *,
    baseline_http_only: bool = True,
) -> dict[str, Any]:
    rows = _load_compare_rows()
    if limit:
        rows = rows[:limit]

    comparisons = []
    miss_hitl_single = miss_hitl_copilot = 0
    mis_dispatch_single = mis_dispatch_copilot = 0
    acl_single = acl_copilot = 0
    traj_ok_n = 0

    for row in rows:
        q = row["question"]
        single = simulate_single_tool(
            q,
            live_rag=live_rag,
            use_local_intent=not baseline_http_only,
        )
        copilot = simulate_copilot(q, live_rag=live_rag, engine=engine)
        if single["skipped_hitl"]:
            miss_hitl_single += 1
        if copilot.get("skipped_hitl"):
            miss_hitl_copilot += 1
        if single["would_submit_without_hitl"]:
            mis_dispatch_single += 1
        if copilot.get("would_submit_without_hitl"):
            mis_dispatch_copilot += 1
        if single["acl_leak_risk"]:
            acl_single += 1
        if copilot["acl_leak_risk"]:
            acl_copilot += 1
        if copilot.get("traj_ok"):
            traj_ok_n += 1
        comparisons.append(
            {
                "id": row.get("id"),
                "question": q,
                "single_tool": single,
                "copilot": {
                    "status": copilot.get("status"),
                    "engine": engine,
                    "waiting_hitl": copilot.get("waiting_hitl"),
                    "would_submit_without_hitl": copilot.get("would_submit_without_hitl"),
                    "submit_eligible": copilot.get("submit_eligible"),
                    "acl_leak_risk": copilot.get("acl_leak_risk"),
                    "trace_nodes": copilot.get("trace_nodes"),
                    "traj_ok": copilot.get("traj_ok"),
                    "rag_linkage": copilot.get("rag_linkage"),
                },
            }
        )

    n = max(len(rows), 1)
    oral_rate, oral_details = _oral_intent_pass_rate()
    summary = {
        "case_count": len(rows),
        "live_rag": live_rag,
        "engine": engine,
        "oral_cases_pass_rate": oral_rate,
        "oral_cases": oral_details,
        "miss_hitl_rate_single": round(miss_hitl_single / n, 3),
        "miss_hitl_rate_copilot": round(miss_hitl_copilot / n, 3),
        "misdispatch_risk_single": round(mis_dispatch_single / n, 3),
        "misdispatch_risk_copilot": round(mis_dispatch_copilot / n, 3),
        "acl_leak_risk_single": round(acl_single / n, 3),
        "acl_leak_risk_copilot": round(acl_copilot / n, 3),
        "trajectory_consistency_copilot": round(traj_ok_n / n, 3),
        "delta_miss_hitl": round((miss_hitl_single - miss_hitl_copilot) / n, 3),
        "delta_false_submit": round((mis_dispatch_single - mis_dispatch_copilot) / n, 3),
        "sources": "baseline_single_tool.jsonl + cases.jsonl(routing/e2e)",
        "note": (
            "Copilot 默认 engine=langgraph；fallback 仅 LangGraph 异常容灾。"
            "单工具链：/ask→draft→submit 无 HITL/POL；"
            "misdispatch_risk_* 由 would_submit_without_hitl 计数，禁止写死。"
            "门禁下未经 approve 不会 submit → copilot 风险常为 0（统计结果）；"
            "负例：已 submit 未经 approve 时标志为 True。"
            + (
                "baseline 默认 http_only_no_classify（更严格对照）。"
                if baseline_http_only
                else "baseline 与 Copilot 共用 classify_intent。"
            )
            + "报告字段 live_rag 标明生成模式，答辩勿混用 offline/live。"
        ),
        "baseline_intent_mode": (
            "http_only_no_classify" if baseline_http_only else "shared_classify_intent"
        ),
    }
    out_path = PROJECT_ROOT / "data" / "eval" / "compare_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"summary": summary, "comparisons": comparisons}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
