"""从 data/intent_rules.json 加载意图/报修词表（可配置，无需改代码）。"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_RULES_PATH = Path(__file__).resolve().parents[2] / "data" / "intent_rules.json"


@lru_cache
def load_intent_rules() -> dict[str, Any]:
    return json.loads(_RULES_PATH.read_text(encoding="utf-8"))


def reload_intent_rules() -> dict[str, Any]:
    load_intent_rules.cache_clear()
    _init_exports()
    return load_intent_rules()


def _init_exports() -> None:
    global ACTION_TOKENS, CHAT_TOKENS, INJECTION_TOKENS, ACL_PROBE_TOKENS, CONFLICT_TOKENS
    global SECOND_VISIT_TOKENS, URGENT_TOKENS, WARRANTY_TOKENS, FAULT_SYMPTOM_TOKENS
    global DISPATCH_TOKENS, FAULT_CODE_RE, MODEL_RE, WEAK_ACTION_TOKENS, KNOWLEDGE_QUERY_TOKENS
    rules = load_intent_rules()
    ACTION_TOKENS = tuple(rules.get("action_tokens") or [])
    WEAK_ACTION_TOKENS = tuple(rules.get("weak_action_tokens") or [])
    KNOWLEDGE_QUERY_TOKENS = tuple(rules.get("knowledge_query_tokens") or [])
    DISPATCH_TOKENS = tuple(rules.get("dispatch_tokens") or [])
    FAULT_SYMPTOM_TOKENS = tuple(rules.get("fault_symptom_tokens") or [])
    CHAT_TOKENS = tuple(rules.get("chat_tokens") or [])
    INJECTION_TOKENS = tuple(rules.get("injection_tokens") or [])
    ACL_PROBE_TOKENS = tuple(rules.get("acl_probe_tokens") or [])
    CONFLICT_TOKENS = tuple(rules.get("conflict_tokens") or [])
    SECOND_VISIT_TOKENS = tuple(rules.get("second_visit_tokens") or [])
    URGENT_TOKENS = tuple(rules.get("urgent_tokens") or [])
    WARRANTY_TOKENS = tuple(rules.get("warranty_tokens") or [])
    FAULT_CODE_RE = re.compile(rules.get("fault_code_pattern", ""), re.IGNORECASE)
    MODEL_RE = re.compile(rules.get("model_pattern", ""), re.IGNORECASE)


_init_exports()
