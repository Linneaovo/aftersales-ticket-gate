"""B6 feedback roundtrip：degraded submit → down 可按 run_id 回读。"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_mod():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "check_feedback_roundtrip",
        root / "scripts" / "check_feedback_roundtrip.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_feedback_roundtrip_offline_degraded_down():
    mod = _load_mod()
    report = mod._run_offline()
    assert report["ok"] is True, report
    assert report["feedback_ref"]["rating"] == "down"
    assert "down" in (report.get("lookup") or {}).get("ratings", [])
    assert report.get("required_for_claimable") is False
