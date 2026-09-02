"""data/playbooks/*.json 回归：默认 langgraph（与 POST /runs 一致）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import get_settings
from app.graph.builder import reset_graph_cache
from app.graph.runner import create_initial_state, run_until_pause
from app.playbooks.runner import validate_playbook_result
from tests.test_core import FakeRag

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOKS = sorted((ROOT / "data" / "playbooks").glob("*.json"))
LANGGRAPH_SPOTLIGHT = {p.stem for p in PLAYBOOKS}


def _fake_rag_for_question(question: str, parts: list[str] | None = None) -> FakeRag:
    conflicts = []
    if any(x in question for x in ("质保", "哪个为准", "新旧", "不一致")):
        conflicts = [{"doc_a": "旧版", "doc_b": "新版", "metric": "质保月数"}]
    payload = {
        "answer": "两版制度数字不一致，并列展示，不作裁决。" if conflicts else "H103 与液压压力相关。",
        "sources": [{"chunk": {"source": "故障码对照表.txt", "text": "H103"}, "score": 0.9}],
        "grounded": True,
        "grounding_score": 0.85,
        "blocked": False,
        "conflicts": conflicts,
    }
    return FakeRag(ask_payload=payload, parts=parts or ["液压泵总成"])


def _hints_from_playbook(data: dict) -> list[str]:
    hints = data.get("parts_hints") or data.get("parts_hint") or []
    if isinstance(hints, str):
        return [hints]
    return list(hints)


def _run_playbook(data: dict, *, engine: str, client: FakeRag) -> dict:
    state = create_initial_state(
        str(data.get("question") or ""),
        api_key=str(data.get("api_key") or "demo-technician"),
        knowledge_base=str(data.get("knowledge_base") or "demo-kb"),
        auto_submit=bool(data.get("auto_submit") or False),
        parts_force_hints=_hints_from_playbook(data),
        station=data.get("station"),
        second_visit=data.get("second_visit"),
        sla_class=data.get("sla_class"),
        engine=engine,
    )
    return run_until_pause(state, client=client, persist=False)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _isolated_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.db"))
    get_settings.cache_clear()
    reset_graph_cache()


@pytest.mark.parametrize("playbook_path", PLAYBOOKS, ids=lambda p: p.stem)
def test_playbook_expectations_langgraph(playbook_path: Path):
    data = json.loads(playbook_path.read_text(encoding="utf-8"))
    question = str(data.get("question") or "")
    hints = _hints_from_playbook(data)
    client = _fake_rag_for_question(question, parts=hints or None)
    out = _run_playbook(data, engine="langgraph", client=client)
    report = validate_playbook_result(data, out)
    assert report["passed"], f"{playbook_path.stem}: {report['diffs']}"
    assert out.get("engine") == "langgraph"


@pytest.mark.parametrize("playbook_id", sorted(LANGGRAPH_SPOTLIGHT))
def test_playbook_spotlight_matches_fallback(playbook_id: str):
    """核心剧本：非 HITL 时两引擎 status 一致；HITL 时 fallback 须 failed（禁止假 waiting_hitl）。"""
    path = ROOT / "data" / "playbooks" / f"{playbook_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    question = str(data.get("question") or "")
    hints = _hints_from_playbook(data)
    client = _fake_rag_for_question(question, parts=hints or None)
    out_lg = _run_playbook(data, engine="langgraph", client=client)
    out_fb = _run_playbook(data, engine="fallback", client=client)
    assert out_lg.get("intent") == out_fb.get("intent")
    if out_lg.get("status") == "waiting_hitl":
        assert out_fb.get("status") == "failed", (
            f"{playbook_id}: HITL 场景 fallback 须 failed，got {out_fb.get('status')}"
        )
        assert "fallback" in str(out_fb.get("error") or "").lower()
    else:
        assert out_lg.get("status") == out_fb.get("status"), (
            f"{playbook_id}: langgraph={out_lg.get('status')} fallback={out_fb.get('status')}"
        )
