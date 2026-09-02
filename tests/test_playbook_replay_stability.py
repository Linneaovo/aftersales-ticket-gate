# -*- coding: utf-8 -*-
"""Phase 6：FakeRag 同一 playbook 双次回放 → 门禁/证书关键字段一致。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import get_settings
from app.eval.replay_stability import stability_fingerprint
from app.graph.builder import reset_graph_cache
from app.playbooks.runner import validate_playbook_result
from tests.test_playbooks import PLAYBOOKS, _fake_rag_for_question, _hints_from_playbook, _run_playbook

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolated_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.db"))
    get_settings.cache_clear()
    reset_graph_cache()


@pytest.mark.parametrize("playbook_path", PLAYBOOKS, ids=lambda p: p.stem)
def test_playbook_double_run_stable(playbook_path: Path):
    data = json.loads(playbook_path.read_text(encoding="utf-8"))
    question = str(data.get("question") or "")
    hints = _hints_from_playbook(data)
    client = _fake_rag_for_question(question, parts=hints or None)

    out1 = _run_playbook(data, engine="langgraph", client=client)
    out2 = _run_playbook(data, engine="langgraph", client=client)

    report = validate_playbook_result(data, out1)
    assert report["passed"], f"{playbook_path.stem} first run: {report['diffs']}"

    fp1 = stability_fingerprint(out1)
    fp2 = stability_fingerprint(out2)
    assert fp1 == fp2, (
        f"{playbook_path.stem}: 双次回放不稳定\n"
        f"run1={fp1}\nrun2={fp2}"
    )
    # run_id 应不同（两次独立创建），但证书决策视图一致
    assert out1.get("run_id") and out2.get("run_id")
    assert out1.get("run_id") != out2.get("run_id")
