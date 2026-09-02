"""从 data/intent_rules.json 加载意图/报修词表与判定规则（可配置，无需改代码）。

词表含现场口语「派人/上门」等，仅用于识别报修意图；产品 scope 仍是开单门禁，不做 ERP 派工。
演示口语列表（ORAL_SMOKE）刻意使用报修开单话术，避免调度品牌。

判定树（intent_priority_rules / fault_dispatch_rules / post_fault_rules）带 rule_id，
失败时可追溯「触发了哪条规则」。
"""

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
    global EQUIPMENT_CONTEXT_TOKENS, FAULT_PHRASE_TOKENS, MASTER_VISIT_TOKENS
    global HELP_APPEAL_TOKENS, MASTER_MENTION_TOKENS
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
    EQUIPMENT_CONTEXT_TOKENS = tuple(rules.get("equipment_context_tokens") or [])
    FAULT_PHRASE_TOKENS = tuple(rules.get("fault_phrase_tokens") or [])
    MASTER_VISIT_TOKENS = tuple(rules.get("master_visit_tokens") or [])
    HELP_APPEAL_TOKENS = tuple(rules.get("help_appeal_tokens") or ["你们", "帮忙"])
    MASTER_MENTION_TOKENS = tuple(rules.get("master_mention_tokens") or ["师傅"])


def resolve_intent_confidence_threshold() -> float:
    """POL-INTENT-01 阈值 SSOT：intent_rules.json 优先，否则 Settings。"""
    from app.config import get_settings

    rules = load_intent_rules()
    json_thr = rules.get("intent_confidence_threshold")
    if json_thr is not None:
        return float(json_thr)
    return float(get_settings().intent_confidence_threshold or 0.5)


def _re_sub_ws(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _token_list(rules: dict[str, Any], key: str) -> tuple[str, ...]:
    return tuple(rules.get(key) or [])


def _match_token_list(q: str, lower: str, tokens: tuple[str, ...]) -> bool:
    return any(t in q for t in tokens) or any(t in lower for t in tokens if t.isascii())


def _rule_ok(flags: dict[str, bool], rule: dict[str, Any]) -> bool:
    for name in rule.get("all") or []:
        if not flags.get(str(name), False):
            return False
    any_list = rule.get("any") or []
    if any_list and not any(flags.get(str(name), False) for name in any_list):
        return False
    return True


def build_intent_flags(question: str) -> dict[str, bool]:
    """计算布尔特征；供 fault_dispatch_rules 匹配（单源可测）。"""
    q = (question or "").strip()
    compact = _re_sub_ws(q)
    codes = bool(FAULT_CODE_RE.findall(q))
    has_action = any(t in compact for t in ACTION_TOKENS)
    has_weak_action = any(t in q for t in WEAK_ACTION_TOKENS) or any(t in compact for t in WEAK_ACTION_TOKENS)
    has_dispatch = any(t in q for t in DISPATCH_TOKENS)
    has_symptom = any(t in q for t in FAULT_SYMPTOM_TOKENS)
    has_model = bool(MODEL_RE.search(q))
    has_equipment_token = any(t in q for t in EQUIPMENT_CONTEXT_TOKENS)
    has_equipment_ctx = has_model or has_symptom or codes or has_equipment_token
    from app.domain.station import resolve_jobsite, resolve_station_name

    has_geo_ctx = bool(resolve_station_name(q) or resolve_jobsite(q) or "客户" in q)
    has_help_appeal = any(t in q for t in HELP_APPEAL_TOKENS)
    has_master_mention = any(t in q for t in MASTER_MENTION_TOKENS)
    has_master_visit = any(t in compact for t in MASTER_VISIT_TOKENS)
    has_fault_phrase = any(t in q for t in FAULT_PHRASE_TOKENS)
    return {
        "codes": codes,
        "has_action": has_action,
        "has_weak_action": has_weak_action,
        "has_dispatch": has_dispatch,
        "has_symptom": has_symptom,
        "has_model": has_model,
        "has_equipment_ctx": has_equipment_ctx,
        "has_equipment_token": has_equipment_token,
        "has_geo_ctx": has_geo_ctx,
        "has_help_appeal": has_help_appeal,
        "has_master_mention": has_master_mention,
        "has_master_visit": has_master_visit,
        "has_fault_phrase": has_fault_phrase,
    }


_DEFAULT_FD_WEIGHTS: dict[str, float] = {
    "fault_code": 0.35,
    "model": 0.25,
    "action": 0.25,
    "symptom": 0.15,
    "dispatch_token": 0.10,
    "weak_action": 0.10,
    "intake_phrase": 0.15,
    "station_or_jobsite": 0.08,
}


def _fault_dispatch_weights() -> dict[str, Any]:
    rules = load_intent_rules()
    raw = rules.get("fault_dispatch_score_weights") or {}
    return raw if isinstance(raw, dict) else {}


def score_fault_dispatch_signals(question: str) -> tuple[float, list[str]]:
    """规则信号加权 → 置信度；权重来自 intent_rules.json（POL-INTENT-01）。"""
    q = (question or "").strip()
    flags = build_intent_flags(q)
    weights = _fault_dispatch_weights()
    signals: list[str] = []
    score = 0.0

    def _w(key: str) -> float:
        val = weights.get(key, _DEFAULT_FD_WEIGHTS.get(key, 0.0))
        try:
            return float(val)
        except (TypeError, ValueError):
            return float(_DEFAULT_FD_WEIGHTS.get(key, 0.0))

    flag_to_signal = (
        ("codes", "fault_code"),
        ("has_model", "model"),
        ("has_action", "action"),
        ("has_symptom", "symptom"),
        ("has_dispatch", "dispatch_token"),
        ("has_weak_action", "weak_action"),
    )
    for flag_name, signal in flag_to_signal:
        if flags.get(flag_name):
            score += _w(signal)
            signals.append(signal)

    phrases = weights.get("intake_phrase_any")
    if not isinstance(phrases, list) or not phrases:
        phrases = ["报修", "开单"]
    if any(str(p) in q for p in phrases if p):
        score += _w("intake_phrase")
        signals.append("intake_phrase")

    if flags.get("has_geo_ctx"):
        # has_geo_ctx 含「客户」；打分历史语义仅站/工地，保持兼容
        from app.domain.station import resolve_jobsite, resolve_station_name

        if resolve_station_name(q) or resolve_jobsite(q):
            score += _w("station_or_jobsite")
            signals.append("station_or_jobsite")

    return min(score, 1.0), signals


def classify_intent_detailed(question: str) -> tuple[str, float, list[str]]:
    """返回 (intent, confidence, signals)。signals 含 rule:<id> 便于评测溯源。

    词表与判定树均来自 intent_rules.json；nodes 仅再导出包装。
    """
    rules = load_intent_rules()
    q = (question or "").strip()
    lower = q.lower()

    for pr in rules.get("intent_priority_rules") or []:
        match_key = str(pr.get("match") or "")
        tokens = _token_list(rules, match_key)
        if tokens and _match_token_list(q, lower, tokens):
            rid = str(pr.get("rule_id") or "PRIORITY")
            sig = str(pr.get("signal") or rid)
            return str(pr.get("intent")), float(pr.get("confidence", 1.0)), [sig, f"rule:{rid}"]

    flags = build_intent_flags(q)
    for fr in rules.get("fault_dispatch_rules") or []:
        if _rule_ok(flags, fr):
            rid = str(fr.get("rule_id") or "FD")
            conf, signals = score_fault_dispatch_signals(q)
            return "fault_dispatch", conf, signals + [f"rule:{rid}"]

    for pr in rules.get("post_fault_rules") or []:
        match_key = str(pr.get("match") or "")
        tokens = _token_list(rules, match_key)
        if not tokens or not any(t in q for t in tokens):
            continue
        exclude = pr.get("exclude_any") or []
        if any(x in q for x in exclude):
            continue
        rid = str(pr.get("rule_id") or "POST")
        sig = str(pr.get("signal") or rid)
        return str(pr.get("intent")), float(pr.get("confidence", 1.0)), [sig, f"rule:{rid}"]

    fb = rules.get("fallback_rule") or {}
    rid = str(fb.get("rule_id") or "KO-FALLBACK")
    sig = str(fb.get("signal") or "fallback_knowledge")
    return (
        str(fb.get("intent") or "knowledge_only"),
        float(fb.get("confidence", 0.6)),
        [sig, f"rule:{rid}"],
    )


def classify_intent(question: str) -> str:
    return classify_intent_detailed(question)[0]


def fired_rule_id(signals: list[str] | None) -> str | None:
    for s in signals or []:
        if isinstance(s, str) and s.startswith("rule:"):
            return s[5:]
    return None


_init_exports()
