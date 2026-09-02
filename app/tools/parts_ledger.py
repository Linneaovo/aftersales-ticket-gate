from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.domain.parts_catalog import load_parts_catalog
from app.domain.station import load_station_profile


def _model_compatible(ticket_model: str | None, allowed: list[Any] | None) -> bool:
    """台账 machine_models 非空时按机型防错件；空列表=不限制。"""
    models = [str(m).strip().upper() for m in (allowed or []) if m]
    if not models:
        return True
    tm = (ticket_model or "").strip().upper()
    if not tm:
        return True  # 未抽到机型时不误拦
    if tm in models:
        return True
    # 家族兼容：SY215C ↔ SY215
    for a in models:
        if tm.startswith(a) or a.startswith(tm):
            return True
    return False


class PartsLedgerClient(ABC):
    """配件台账抽象；当前 JsonLedger 实现，生产可接 WMS/ERP HTTP。"""

    @abstractmethod
    def check_parts(self, part_hints: list[str], *, machine_model: str | None = None) -> dict[str, Any]:
        ...


class JsonPartsLedger(PartsLedgerClient):
    def __init__(self, path: str | None = None) -> None:
        self._path = path

    def load_ledger(self) -> dict[str, Any]:
        if self._path:
            path = Path(self._path)
            if not path.exists():
                profile = load_station_profile()
                return {
                    "station": profile.get("primary_station", "长沙星沙服务站"),
                    "support_depot": profile.get("support_depot", "经开备件周转点"),
                    "items": [],
                }
            data = json.loads(path.read_text(encoding="utf-8"))
            profile = load_station_profile()
            data.setdefault("station", profile.get("primary_station"))
            data.setdefault("support_depot", profile.get("support_depot"))
            return data
        return load_parts_catalog()

    def check_parts(self, part_hints: list[str], *, machine_model: str | None = None) -> dict[str, Any]:
        from app.domain.parts_master import MASTER_SOURCE, normalize_part_hints, reset_parts_master_cache

        # E1：每次预核强制失效，改 JSON 后同进程下一跑即可看到新 stock
        reset_parts_master_cache()
        canonical, hint_mapping = normalize_part_hints(part_hints)
        ledger = self.load_ledger()
        profile = load_station_profile()
        depot = ledger.get("support_depot") or profile.get("support_depot") or "经开备件周转点"
        items_out: list[dict[str, Any]] = []
        shortage = False
        unknown_parts = False
        model_mismatch = False
        catalog = {str(i.get("name", "")): i for i in ledger.get("items", [])}
        catalog.update({str(i.get("part_no", "")): i for i in ledger.get("items", [])})

        depot_phone = str(ledger.get("depot_phone") or profile.get("depot_phone") or "")
        depot_phone_note = str(ledger.get("depot_phone_note") or profile.get("depot_phone_note") or "")
        default_lead = int(ledger.get("default_lead_time_hours") or 4)

        demo_note = str(
            ledger.get("_demo_note")
            or "演示 JSON 台账（非 WMS）；库存为剧本数据，改 stock 会改变 POL-PARTS-01 是否触发"
        )
        if not canonical:
            return {
                "needed": False,
                "items": [],
                "shortage": False,
                "unknown_parts": False,
                "model_mismatch": False,
                "ledger_degraded": False,
                "shortage_items": [],
                "mismatch_items": [],
                "alt_depot": depot,
                "depot_phone": depot_phone,
                "depot_phone_note": depot_phone_note,
                "lead_time_hours": 0,
                "suggested_action": "无需配件预核",
                "note": "未检出明确配件需求",
                "source": "demo_ledger",
                "ledger_kind": "demo_json",
                "demo_note": demo_note,
                "master_data_authority": MASTER_SOURCE,
                "hint_mapping": hint_mapping,
                "machine_model": machine_model or "",
            }

        max_lead = 0
        for hint in canonical:
            hit = catalog.get(hint) if hint else None
            if hit is None and hint:
                hit = next(
                    (
                        row
                        for row in ledger.get("items") or []
                        if isinstance(row, dict)
                        and (
                            str(row.get("name") or "") == hint
                            or str(row.get("part_no") or "").upper() == hint.upper()
                        )
                    ),
                    None,
                )
            if hit is None:
                items_out.append({"hint": hint, "status": "unknown", "stock": 0})
                unknown_parts = True
                continue
            models = hit.get("machine_models") or []
            if not _model_compatible(machine_model, models if isinstance(models, list) else []):
                model_mismatch = True
                items_out.append(
                    {
                        "hint": hint,
                        "part_no": hit.get("part_no"),
                        "name": hit.get("name"),
                        "stock": int(hit.get("stock") or 0),
                        "status": "model_mismatch",
                        "depot": hit.get("depot", "星沙"),
                        "machine_models": list(models) if isinstance(models, list) else [],
                        "ticket_machine_model": machine_model or "",
                    }
                )
                continue
            stock = int(hit.get("stock") or 0)
            status = "ok" if stock > 0 else "shortage"
            if stock <= 0:
                shortage = True
            lead_h = int(hit.get("lead_time_hours") if hit.get("lead_time_hours") is not None else default_lead)
            if stock <= 0:
                max_lead = max(max_lead, lead_h)
            items_out.append(
                {
                    "hint": hint,
                    "part_no": hit.get("part_no"),
                    "name": hit.get("name"),
                    "stock": stock,
                    "status": status,
                    "depot": hit.get("depot", "星沙"),
                    "alt_depot": hit.get("alt_depot") or depot,
                    "lead_time_hours": lead_h,
                    "machine_models": hit.get("machine_models") or [],
                }
            )

        shortage_names = [
            str(i.get("name") or i.get("hint") or "")
            for i in items_out
            if i.get("status") == "shortage"
        ]
        unknown_names = [
            str(i.get("hint") or "") for i in items_out if i.get("status") == "unknown"
        ]
        mismatch_names = [
            str(i.get("name") or i.get("hint") or "")
            for i in items_out
            if i.get("status") == "model_mismatch"
        ]

        if model_mismatch and not shortage and not unknown_parts:
            suggested = "存在机型不匹配件，须核对适用机型；禁止按缺料调拨话术处理"
            note = (
                f"model_mismatch：票面机型={machine_model or '(空)'} "
                f"与台账 machine_models 不符，须 confirmations.ledger"
            )
            lead = 0
        elif unknown_parts and not shortage:
            suggested = "存在未识别件号，须核对主数据；禁止按缺料调拨话术处理"
            note = "unknown_parts：不可视为可调拨缺料，须 confirmations.ledger"
            lead = 0
            if model_mismatch:
                note += f"；另有机型不匹配件 {','.join(mismatch_names)}"
                suggested += "；并核对机型适用性"
        elif shortage:
            lead = max_lead or default_lead
            phone_bit = ""
            if depot_phone:
                phone_bit = f" · DEMO电话 {depot_phone}"
                if depot_phone_note:
                    phone_bit += f"（{depot_phone_note}）"
            suggested = f"建议：{depot}调拨 · 预计 {lead}h{phone_bit}"
            note = f"{depot}可调拨 / 或改约上门；缺料禁止静默开单"
            if unknown_parts:
                note += f"；另有未知件 {','.join(unknown_names)} 须主数据核对"
                suggested += "；并核对未知件号"
            if model_mismatch:
                note += f"；另有机型不匹配件 {','.join(mismatch_names)}"
                suggested += "；并核对机型适用性"
        else:
            suggested = f"{ledger.get('station', '星沙')}库存可覆盖"
            note = suggested
            lead = 0

        return {
            "needed": True,
            "items": items_out,
            "shortage": shortage,
            "unknown_parts": unknown_parts,
            "model_mismatch": model_mismatch,
            "ledger_degraded": False,
            "shortage_items": [n for n in shortage_names if n],
            "mismatch_items": [n for n in mismatch_names if n],
            "alt_depot": depot,
            "depot_phone": depot_phone,
            "depot_phone_note": depot_phone_note,
            "lead_time_hours": lead,
            "suggested_action": suggested,
            "note": note,
            "source": "demo_ledger",
            "ledger_kind": "demo_json",
            "demo_note": demo_note,
            "master_data_authority": MASTER_SOURCE,
            "hint_mapping": hint_mapping,
            "machine_model": machine_model or "",
        }


class HttpPartsLedger(PartsLedgerClient):
    """WMS/ERP HTTP 台账；POST {base}/parts/check {"hints":[...]}。"""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def check_parts(self, part_hints: list[str], *, machine_model: str | None = None) -> dict[str, Any]:
        from app.domain.parts_master import normalize_part_hints, reset_parts_master_cache
        from app.tools.http_pool import get_http_client

        reset_parts_master_cache()
        canonical, mapping = normalize_part_hints(part_hints)
        try:
            client = get_http_client(self._base_url)
            payload: dict[str, Any] = {"hints": canonical}
            if machine_model:
                payload["machine_model"] = machine_model
            resp = client.post("/parts/check", json=payload, timeout=10.0)
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            if isinstance(data, dict):
                data.setdefault("source", "wms_http")
                data.setdefault("ledger_degraded", False)
                data.setdefault("unknown_parts", False)
                data.setdefault("model_mismatch", False)
                data["hint_mapping"] = mapping
                data["master_data_authority"] = self._base_url
                data["machine_model"] = machine_model or data.get("machine_model") or ""
                return data
        except Exception as exc:
            # 降级本地台账必须可感知，禁止假成功冒充 WMS
            fallback = JsonPartsLedger().check_parts(canonical, machine_model=machine_model)
            fallback["source"] = "json_fallback_after_http_error"
            fallback["http_error"] = str(exc)
            fallback["ledger_degraded"] = True
            fallback["hint_mapping"] = mapping
            fallback["note"] = (
                str(fallback.get("note") or "")
                + "；WMS HTTP 失败已降级本地演示台账，须 confirmations.ledger"
            ).lstrip("；")
            fallback["suggested_action"] = (
                "台账 HTTP 降级：禁止静默采信本地库存，须站长确认后继续"
            )
            return fallback
        degraded = JsonPartsLedger().check_parts(canonical, machine_model=machine_model)
        degraded["source"] = "json_fallback_empty_http_body"
        degraded["ledger_degraded"] = True
        degraded["hint_mapping"] = mapping
        return degraded


_ledger_client: PartsLedgerClient | None = None


def get_parts_ledger_client() -> PartsLedgerClient:
    global _ledger_client
    if _ledger_client is None:
        settings = get_settings()
        url = (settings.parts_ledger_url or "").strip()
        _ledger_client = HttpPartsLedger(url) if url else JsonPartsLedger()
    return _ledger_client


def reset_parts_ledger_client() -> None:
    """settings 变更后（如 PARTS_LEDGER_URL）重置台账客户端单例。"""
    global _ledger_client
    _ledger_client = None


def load_parts_ledger(path: str | None = None) -> dict[str, Any]:
    """兼容入口：默认走 domain catalog；显式 path 时读指定 JSON。"""
    return JsonPartsLedger(path).load_ledger()


def check_parts(
    part_hints: list[str],
    *,
    path: str | None = None,
    machine_model: str | None = None,
) -> dict[str, Any]:
    client: PartsLedgerClient = JsonPartsLedger(path) if path else get_parts_ledger_client()
    return client.check_parts(part_hints, machine_model=machine_model)


def _load_answer_tokens() -> list[str]:
    """演示词表外置；非 NER。优先长度降序，减少短词误触。"""
    path = Path(__file__).resolve().parents[2] / "data" / "parts_answer_tokens.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        tokens = [str(t) for t in (data.get("tokens") or []) if t]
        tokens.sort(key=len, reverse=True)
        return tokens
    except (json.JSONDecodeError, OSError):
        return []


def hints_from_rag_and_draft(rag: dict[str, Any], draft: dict[str, Any] | None) -> list[str]:
    """配件 hint：优先 draft/RAG work_order；answer 词表默认关闭（ALLOW_ANSWER_TOKEN_HINTS=1 才扫）。"""
    from app.domain.parts_master import normalize_part_hints

    raw_hints: list[str] = []
    body = draft or {}
    if isinstance(body.get("draft"), dict):
        body = {**body, **body["draft"]}
    for p in body.get("recommended_parts") or body.get("parts") or []:
        if p:
            raw_hints.append(str(p))
    for p in body.get("part_nos") or []:
        if p and str(p) not in raw_hints:
            raw_hints.append(str(p))
    wo = (rag or {}).get("work_order")
    if isinstance(wo, dict):
        for p in wo.get("recommended_parts") or wo.get("parts") or wo.get("part_nos") or []:
            if p and str(p) not in raw_hints:
                raw_hints.append(str(p))
    if not raw_hints and get_settings().allow_answer_token_hints:
        answer = str((rag or {}).get("answer") or "")
        if answer:
            for token in _load_answer_tokens():
                if len(token) < 3:
                    continue
                if token in answer and token not in raw_hints:
                    raw_hints.append(token)
    canonical, _ = normalize_part_hints(raw_hints)
    return canonical
