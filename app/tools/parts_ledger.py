from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.domain.parts_catalog import load_parts_catalog
from app.domain.station import load_station_profile


class PartsLedgerClient(ABC):
    """配件台账抽象；当前 JsonLedger 实现，生产可接 WMS/ERP HTTP。"""

    @abstractmethod
    def check_parts(self, part_hints: list[str]) -> dict[str, Any]:
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

    def check_parts(self, part_hints: list[str]) -> dict[str, Any]:
        from app.domain.parts_master import MASTER_SOURCE, normalize_part_hints

        canonical, hint_mapping = normalize_part_hints(part_hints)
        ledger = self.load_ledger()
        profile = load_station_profile()
        depot = ledger.get("support_depot") or profile.get("support_depot") or "经开备件周转点"
        items_out: list[dict[str, Any]] = []
        shortage = False
        catalog = {str(i.get("name", "")): i for i in ledger.get("items", [])}
        catalog.update({str(i.get("part_no", "")): i for i in ledger.get("items", [])})

        depot_phone = str(ledger.get("depot_phone") or profile.get("depot_phone") or "")
        default_lead = int(ledger.get("default_lead_time_hours") or 4)

        if not canonical:
            return {
                "needed": False,
                "items": [],
                "shortage": False,
                "shortage_items": [],
                "alt_depot": depot,
                "depot_phone": depot_phone,
                "lead_time_hours": 0,
                "suggested_action": "无需配件预核",
                "note": "未检出明确配件需求",
                "source": "demo_ledger",
                "master_data_authority": MASTER_SOURCE,
                "hint_mapping": hint_mapping,
            }

        max_lead = 0
        for hint in canonical:
            hit = None
            for key, row in catalog.items():
                if hint and key and (hint in key or key in hint):
                    hit = row
                    break
            if hit is None:
                items_out.append({"hint": hint, "status": "unknown", "stock": 0})
                shortage = True
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

        if shortage:
            shortage_names = [
                str(i.get("name") or i.get("hint") or "")
                for i in items_out
                if i.get("status") in {"shortage", "unknown"}
            ]
            lead = max_lead or default_lead
            phone_suffix = f" · 联系电话 {depot_phone}" if depot_phone else ""
            suggested = f"建议：{depot}调拨 · 预计 {lead}h{phone_suffix}"
            note = f"{depot}可调拨 / 或改约上门；缺料禁止静默开单"
        else:
            shortage_names = []
            suggested = f"{ledger.get('station', '星沙')}库存可覆盖"
            note = suggested
            lead = 0
        return {
            "needed": True,
            "items": items_out,
            "shortage": shortage,
            "shortage_items": [n for n in shortage_names if n],
            "alt_depot": depot,
            "depot_phone": depot_phone,
            "lead_time_hours": lead,
            "suggested_action": suggested,
            "note": note,
            "source": "demo_ledger",
            "master_data_authority": MASTER_SOURCE,
            "hint_mapping": hint_mapping,
        }


class HttpPartsLedger(PartsLedgerClient):
    """WMS/ERP HTTP 台账；POST {base}/parts/check {"hints":[...]}。"""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def check_parts(self, part_hints: list[str]) -> dict[str, Any]:
        import httpx

        from app.domain.parts_master import normalize_part_hints

        canonical, mapping = normalize_part_hints(part_hints)
        try:
            with httpx.Client(base_url=self._base_url, timeout=10.0) as client:
                resp = client.post("/parts/check", json={"hints": canonical})
                resp.raise_for_status()
                data = resp.json() if resp.content else {}
                if isinstance(data, dict):
                    data.setdefault("source", "wms_http")
                    data["hint_mapping"] = mapping
                    data["master_data_authority"] = self._base_url
                    return data
        except Exception as exc:
            fallback = JsonPartsLedger().check_parts(canonical)
            fallback["source"] = "json_fallback_after_http_error"
            fallback["http_error"] = str(exc)
            fallback["hint_mapping"] = mapping
            return fallback
        return JsonPartsLedger().check_parts(canonical)


_ledger_client: PartsLedgerClient | None = None


def get_parts_ledger_client() -> PartsLedgerClient:
    global _ledger_client
    if _ledger_client is None:
        settings = get_settings()
        url = (settings.parts_ledger_url or "").strip()
        _ledger_client = HttpPartsLedger(url) if url else JsonPartsLedger()
    return _ledger_client


def load_parts_ledger(path: str | None = None) -> dict[str, Any]:
    """兼容入口：默认走 domain catalog；显式 path 时读指定 JSON。"""
    return JsonPartsLedger(path).load_ledger()


def check_parts(part_hints: list[str], *, path: str | None = None) -> dict[str, Any]:
    client: PartsLedgerClient = JsonPartsLedger(path) if path else get_parts_ledger_client()
    return client.check_parts(part_hints)


def hints_from_rag_and_draft(rag: dict[str, Any], draft: dict[str, Any] | None) -> list[str]:
    from app.domain.parts_master import normalize_part_hints

    raw_hints: list[str] = []
    body = draft or {}
    if isinstance(body.get("draft"), dict):
        body = {**body, **body["draft"]}
    for p in body.get("recommended_parts") or body.get("parts") or []:
        if p:
            raw_hints.append(str(p))
    answer = str((rag or {}).get("answer") or "")
    for token in ("电磁阀", "液压泵", "液压泵总成", "滤芯", "密封圈", "压力传感器", "主控阀"):
        if token in answer and token not in raw_hints:
            raw_hints.append(token)
    wo = (rag or {}).get("work_order")
    if isinstance(wo, dict):
        for p in wo.get("recommended_parts") or wo.get("parts") or []:
            if p and str(p) not in raw_hints:
                raw_hints.append(str(p))
    canonical, _ = normalize_part_hints(raw_hints)
    return canonical
