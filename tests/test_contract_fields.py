"""契约消费字段表与 CONTRACT_VERSION 对齐。"""

from __future__ import annotations

from app.eval.contract_fields import load_consumer_fields, validate_consumer_fields_table
from app.tools.rag_contract import CONTRACT_VERSION, validate_ask_response


def test_consumer_fields_table_matches_contract_version():
    data = load_consumer_fields()
    assert data.get("contract_version") == CONTRACT_VERSION
    assert validate_consumer_fields_table(data) == []


def test_ask_validator_covers_required_consumer_fields():
    required = list((load_consumer_fields().get("ask") or {}).get("required") or [])
    # 缺必填应报错
    errs = validate_ask_response({})
    for field in required:
        assert any(field in e for e in errs), f"validator should mention {field}: {errs}"
    ok_payload = {
        "answer": "x",
        "sources": [],
        "grounded": True,
        "grounding_score": 0.5,
        "blocked": False,
    }
    assert validate_ask_response(ok_payload) == []
