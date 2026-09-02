# -*- coding: utf-8 -*-
"""C.1 缺口补测：注入路径上 Decision Certificate 须带齐 policy_ids。"""

from __future__ import annotations

from app.graph.runner import public_view, run_until_pause
from app.graph.state import empty_state
from tests.test_core import FakeRag


def test_conflict_ungrounded_certificate_includes_ground_01():
    payload = {
        "answer": "两版制度口径不一致，请站长确认。",
        "sources": [],
        "grounded": False,
        "grounding_score": 0.1,
        "blocked": False,
        "conflicts": [{"doc_a": "旧版", "doc_b": "新版", "metric": "质保月数"}],
    }
    st = empty_state(
        run_id="inj-ground",
        raw_input="星沙站 SY215C 液压泵质保期新旧制度不一致，到底哪个为准？",
        role="technician",
        api_key="demo-technician",
    )
    out = run_until_pause(st, client=FakeRag(ask_payload=payload), persist=False)
    assert out.get("status") == "waiting_hitl"
    cert = out.get("decision_certificate") or {}
    assert "POL-GROUND-01" in (cert.get("policy_ids") or [])
    view = public_view(out)
    assert "POL-GROUND-01" in ((view.get("decision_certificate") or {}).get("policy_ids") or [])
