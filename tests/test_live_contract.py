"""Live Portfolio JSON 与脚本契约一致。

重要：本文件只校验证据包 **schema / 入库钉扎**，**不等于** 当场 HTTP Live 联调。
HTTP 联调见：
  - L1：linkage-l1.yml / scripts/run_l1_linkage.py（evidence_tier=L1，live_verified=false）
  - L2：live-linkage.yml / build_joint_evidence_pack --live（须 live_verified=true）
"""

from __future__ import annotations

import json
from pathlib import Path

from app.eval.live_contract import (
    LIVE_FUNCTION_EXPECTED_TOTAL,
    LIVE_FUNCTION_SCRIPT_VERSION,
    LIVE_MANUAL_EXPECTED_TOTAL,
    LIVE_MANUAL_SCRIPT_VERSION,
)
from app.eval.ssot import PYTEST_FULL_COLLECT, PYTEST_OFFLINE_COLLECT

_EVAL = Path(__file__).resolve().parents[1] / "data" / "eval"


def test_ssot_pytest_counts_positive():
    assert PYTEST_OFFLINE_COLLECT > 0
    assert PYTEST_FULL_COLLECT >= PYTEST_OFFLINE_COLLECT


def test_live_contract_totals_positive():
    assert LIVE_FUNCTION_EXPECTED_TOTAL == 29
    assert LIVE_MANUAL_EXPECTED_TOTAL == 11
    assert LIVE_FUNCTION_SCRIPT_VERSION.startswith("2026-")
    assert LIVE_MANUAL_SCRIPT_VERSION.startswith("2026-")


def test_committed_live_manual_evidence_matches_contract():
    path = _EVAL / "live_integration_manual.json"
    assert path.exists(), "缺少本机 Live 证据包 live_integration_manual.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("all_ok") is True
    assert int(data.get("passed") or 0) == LIVE_MANUAL_EXPECTED_TOTAL
    assert data.get("script_version") == LIVE_MANUAL_SCRIPT_VERSION
    mock = data.get("mock_submit") or {}
    assert mock.get("destination") == "rag_mock_inbox"
    assert mock.get("is_production_ticket") is False


def test_committed_live_function_evidence_matches_contract():
    path = _EVAL / "live_function_test.json"
    assert path.exists(), "缺少本机 Live 证据包 live_function_test.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("all_ok") is True
    assert int(data.get("passed") or 0) == LIVE_FUNCTION_EXPECTED_TOTAL
    assert data.get("script_version") == LIVE_FUNCTION_SCRIPT_VERSION
    mock = data.get("mock_submit") or {}
    assert mock.get("destination") == "rag_mock_inbox"


def test_joint_evidence_pack_schema_when_present():
    """Schema 钉扎 ≠ HTTP Live；from_artifacts 不得自称 L2 / live_verified。"""
    path = _EVAL / "joint_evidence_pack.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("schema") == "joint_evidence_pack/v1"
    assert "live_verified" in data
    assert "portfolio_claimable" in data
    assert data.get("hard_claims", {}).get("destination") == "rag_mock_inbox"
    # 分层字段（新包必有；旧包兼容缺省）
    tier = data.get("evidence_tier")
    if tier is not None:
        assert tier in {"L0", "L1", "L2", "artifacts"}
    if data.get("mode") == "from_artifacts":
        assert data.get("live_verified") is not True
        assert data.get("portfolio_claimable") is False
        if tier is not None:
            assert tier != "L2"
        assert data.get("parts_gate_ab_live_ok") is False
        ab = data.get("parts_gate_ab") or {}
        if isinstance(ab.get("live"), dict):
            assert ab["live"].get("all_ok") is not True
    if tier == "L1":
        assert data.get("live_verified") is False
    rag_idx = data.get("rag_eval_index") or {}
    if rag_idx:
        assert rag_idx.get("copilot_claims_mrr") is False
        assert "combined_score" not in rag_idx
    if data.get("mode") == "from_artifacts" and not data.get("live_verified"):
        assert data.get("portfolio_claimable") is False
        assert data.get("parts_gate_ab_live_ok") is False
        ab = data.get("parts_gate_ab") or {}
        if isinstance(ab.get("live"), dict):
            assert ab["live"].get("all_ok") is not True


def test_live_contract_module_doc_is_schema_only():
    """防回归：本测试文件文档字符串须声明 ≠ HTTP Live。"""
    import tests.test_live_contract as mod

    assert "不等于" in (mod.__doc__ or "") or "!=" in (mod.__doc__ or "") or "≠" in (
        mod.__doc__ or ""
    )


def test_parts_live_allowlist_aligns_with_ledger():
    from pathlib import Path

    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "check_parts_live_align",
        root / "scripts" / "check_parts_live_align.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    report = mod.check()
    assert report.get("ok") is True, report.get("errors")
