"""B4 joint failure drill hardening。"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_drill_mod():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "build_joint_failure_drill",
        root / "scripts" / "build_joint_failure_drill.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_joint_failure_drill_b4_scenes_auto_ok():
    mod = _load_drill_mod()
    drill = mod.build_drill(probe_live=False)
    assert drill.get("schema") == "joint_failure_drill/v2"
    by_id = {s["id"]: s for s in drill.get("scenes") or []}
    for sid in (
        "rag_degraded",
        "no_silent_demorag",
        "retrieve_only_forces_hitl",
        "low_grounding_no_silent_submit",
        "probe_lane_isolation",
        "rag_unreachable",
    ):
        assert sid in by_id, sid
        assert by_id[sid]["ok"] is True, by_id[sid]
    # 未探针时须标 manual，不得假装已验 503
    assert by_id["rag_unreachable"].get("manual") is True
    assert by_id["rag_unreachable"].get("manual_steps")
    assert drill.get("all_ok") is True
