# -*- coding: utf-8 -*-
"""E4 L3：业务 submit 透传 X-Copilot-Submit-Token。"""

from __future__ import annotations

from app.config import Settings
from app.tools.rag_client import RagClient


class _CaptureClient:
    def __init__(self) -> None:
        self.last_headers: dict | None = None
        self.is_closed = False

    def request(self, method, path, *, headers=None, timeout=None, **kwargs):
        self.last_headers = dict(headers or {})

        class _Resp:
            status_code = 200
            content = b"{}"
            text = "{}"

            def json(self):
                return {"ok": True, "ticket_id": "LOCAL-TEST"}

        return _Resp()


def test_submit_includes_token_header_for_business(monkeypatch):
    capture = _CaptureClient()
    monkeypatch.setattr("app.tools.rag_client.get_http_client", lambda *a, **k: capture)
    monkeypatch.setattr("app.tools.rag_client.circuit_allow", lambda *a, **k: True)
    monkeypatch.setattr("app.tools.rag_client.circuit_record_success", lambda *a, **k: None)
    settings = Settings(
        rag_base_url="http://127.0.0.1:8001",
        api_key="demo-key",
        copilot_submit_token="shared-secret",
    )
    client = RagClient(settings=settings, api_key="demo-key")
    client.submit_work_order(
        {"draft": {"ticket_type": "fault_repair"}},
        source="copilot_hitl",
        run_id="r1",
    )
    assert capture.last_headers is not None
    assert capture.last_headers.get("X-Copilot-Submit-Token") == "shared-secret"
    assert capture.last_headers.get("X-API-Key") == "demo-key"


def test_submit_skips_token_header_for_probe(monkeypatch):
    capture = _CaptureClient()
    monkeypatch.setattr("app.tools.rag_client.get_http_client", lambda *a, **k: capture)
    monkeypatch.setattr("app.tools.rag_client.circuit_allow", lambda *a, **k: True)
    monkeypatch.setattr("app.tools.rag_client.circuit_record_success", lambda *a, **k: None)
    settings = Settings(
        rag_base_url="http://127.0.0.1:8001",
        api_key="demo-key",
        copilot_submit_token="shared-secret",
    )
    client = RagClient(settings=settings, api_key="demo-key")
    client.submit_work_order(
        {"draft": {"ticket_type": "fault_repair"}},
        source="contract_probe",
        submitted_by="contract_probe",
    )
    assert capture.last_headers is not None
    assert "X-Copilot-Submit-Token" not in capture.last_headers
