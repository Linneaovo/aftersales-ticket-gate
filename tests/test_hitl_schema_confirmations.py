"""HITL 请求契约：confirmations key 白名单 + return/reject 须非空 note。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.schemas import HitlDecisionRequest


def test_confirmations_unknown_key_rejected():
    with pytest.raises(ValidationError) as ei:
        HitlDecisionRequest(decision="approve", confirmations={"bogus": True})
    assert "未知层" in str(ei.value) or "bogus" in str(ei.value)


def test_confirmations_known_keys_ok():
    req = HitlDecisionRequest(
        decision="approve",
        confirmations={"shortage": True, "conflict": False},
    )
    assert req.confirmations["shortage"] is True


def test_return_requires_nonempty_note():
    with pytest.raises(ValidationError):
        HitlDecisionRequest(decision="return", note="  ", confirmations={})
    ok = HitlDecisionRequest(decision="return", note="缺现场照片", confirmations={})
    assert ok.normalized_decision() == "return"


def test_reject_requires_nonempty_note():
    with pytest.raises(ValidationError):
        HitlDecisionRequest(decision="reject", note="", confirmations={})


def test_edit_alias_normalized_to_return():
    req = HitlDecisionRequest(decision="edit", note="退回补件", confirmations={})
    assert req.normalized_decision() == "return"
