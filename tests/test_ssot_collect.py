"""SSOT：collect 条数与 app.eval.ssot 常量一致（防文档再漂）。"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from app.eval.ssot import PYTEST_FULL_COLLECT, PYTEST_OFFLINE_COLLECT

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "data" / "eval" / "joint_evidence_pack.json"


def _collect_count(*, offline_only: bool) -> int:
    extra = ["-m", "not integration"] if offline_only else []
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", *extra]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, check=False)
    text = (proc.stdout or "") + (proc.stderr or "")
    m = re.search(r"(\d+)/(\d+)\s+tests collected", text)
    if m:
        return int(m.group(1)) if offline_only else int(m.group(2))
    m2 = re.search(r"(\d+)\s+tests collected", text)
    if m2:
        return int(m2.group(1))
    raise AssertionError(f"cannot parse collect output:\n{text[-800:]}")


def test_ssot_offline_collect_matches_constant():
    n = _collect_count(offline_only=True)
    assert n == PYTEST_OFFLINE_COLLECT, (
        f"offline collect={n} ≠ PYTEST_OFFLINE_COLLECT={PYTEST_OFFLINE_COLLECT}；"
        "请更新 app/eval/ssot.py 与对外口径"
    )


def test_ssot_full_collect_matches_constant():
    n = _collect_count(offline_only=False)
    assert n == PYTEST_FULL_COLLECT, (
        f"full collect={n} ≠ PYTEST_FULL_COLLECT={PYTEST_FULL_COLLECT}；"
        "请更新 app/eval/ssot.py"
    )


def test_live_pack_acceptance_layers_match_ssot():
    """live_verified pack 不得携带过期 pytest 条数（增测后须 --live 再生）。"""
    if not PACK.exists():
        return
    data = json.loads(PACK.read_text(encoding="utf-8"))
    if not data.get("live_verified"):
        return
    layers = data.get("acceptance_layers") or {}
    assert layers.get("pytest_offline_collect") == PYTEST_OFFLINE_COLLECT, (
        f"pack offline={layers.get('pytest_offline_collect')} ≠ {PYTEST_OFFLINE_COLLECT}；"
        "python scripts/build_joint_evidence_pack.py --live"
    )
    assert layers.get("pytest_full_collect") == PYTEST_FULL_COLLECT, (
        f"pack full={layers.get('pytest_full_collect')} ≠ {PYTEST_FULL_COLLECT}；"
        "python scripts/build_joint_evidence_pack.py --live"
    )
