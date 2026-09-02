from __future__ import annotations

import json
from pathlib import Path

from app.graph.nodes import classify_intent
from app.graph.runner import create_initial_state, run_until_pause
from app.graph.state import empty_state
from app.quality.rules import run_quality_checks
from app.tools.parts_ledger import check_parts
from tests.test_core import FakeRag

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "data" / "eval" / "cases.jsonl"


def _load_cases():
    rows = []
    for line in CASES.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def test_routing_cases_from_file():
    for case in _load_cases():
        if case.get("bucket") != "routing" or "expect_intent" not in case:
            continue
        assert classify_intent(case.get("question") or "") == case["expect_intent"], case["id"]


def test_quality_cases_from_file():
    for case in _load_cases():
        if case.get("bucket") != "quality":
            continue
        st = empty_state(intent=case.get("intent") or "knowledge_only", rag_result=case["rag"])
        if case["rag"].get("conflicts"):
            st["conflict_bundle"] = {
                "present": True,
                "items": case["rag"]["conflicts"],
                "policy": "不作裁决",
            }
        report = run_quality_checks(st)
        assert report["passed"] is case["expect_passed"], case["id"]


def test_parts_cases_from_file():
    for case in _load_cases():
        if case.get("bucket") != "parts":
            continue
        out = check_parts(case["hints"])
        assert out["shortage"] is case["expect_shortage"], case["id"]
        if "expect_unknown_parts" in case:
            assert bool(out.get("unknown_parts")) is case["expect_unknown_parts"], case["id"]


def test_hitl_meta_cases_technician_needs_hitl():
    for case in _load_cases():
        if case.get("bucket") != "hitl":
            continue
        if case["id"] != "H01":
            continue
        # HITL 须 langgraph；fallback 禁止假 waiting_hitl
        state = create_initial_state(
            "SY215C H103请报修处理",
            api_key="demo-technician",
            engine="langgraph",
        )
        out = run_until_pause(state, client=FakeRag(), persist=False)  # type: ignore[arg-type]
        assert out["status"] == "waiting_hitl"


def test_e2e_playbook_chitchat_meta():
    for case in _load_cases():
        if case.get("playbook") != "p6_chitchat":
            continue
        state = create_initial_state("你好，今天天气怎么样？", engine="fallback")
        out = run_until_pause(state, client=FakeRag(), persist=False)  # type: ignore[arg-type]
        assert out["status"] == case["expect_status"]


def test_error_rag_meta():
    state = create_initial_state("H103是什么意思", engine="fallback")
    out = run_until_pause(state, client=FakeRag(fail=True), persist=False)  # type: ignore[arg-type]
    assert out["status"] == "failed"
