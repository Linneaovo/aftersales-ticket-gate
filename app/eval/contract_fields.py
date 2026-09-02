"""契约消费字段表：与 CONTRACT_VERSION 对齐的小而硬钉扎。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT
from app.tools.rag_contract import CONTRACT_VERSION

FIELDS_PATH = PROJECT_ROOT / "data" / "eval" / "contract_consumer_fields.json"


def load_consumer_fields() -> dict[str, Any]:
    if not FIELDS_PATH.exists():
        return {}
    return json.loads(FIELDS_PATH.read_text(encoding="utf-8"))


def validate_consumer_fields_table(data: dict[str, Any] | None = None) -> list[str]:
    """表自身完整性 + 与 CONTRACT_VERSION 一致。"""
    errors: list[str] = []
    data = data if data is not None else load_consumer_fields()
    if not data:
        return ["missing contract_consumer_fields.json"]
    if data.get("contract_version") != CONTRACT_VERSION:
        errors.append(
            f"contract_version={data.get('contract_version')!r} != CONTRACT_VERSION={CONTRACT_VERSION!r}"
        )
    ask = data.get("ask") if isinstance(data.get("ask"), dict) else {}
    for key in ("required", "breaking_if_removed"):
        if not isinstance(ask.get(key), list) or not ask.get(key):
            errors.append(f"ask.{key} must be non-empty list")
    for field in ("answer", "sources", "grounded"):
        if field not in list(ask.get("required") or []):
            errors.append(f"ask.required must include {field}")
    if "items" not in list((data.get("inbox") or {}).get("required") or []):
        errors.append("inbox.required must include items")
    return errors


def consumer_fields_ok() -> bool:
    return not validate_consumer_fields_table()
