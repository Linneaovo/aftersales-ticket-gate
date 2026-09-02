from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, get_settings


@lru_cache
def load_station_profile() -> dict[str, Any]:
    path = Path(get_settings().station_profile_path) if get_settings().station_profile_path else PROJECT_ROOT / "data" / "station_profile.json"
    if not path.exists():
        path = PROJECT_ROOT / "data" / "station_profile.json"
    if not path.exists():
        return {
            "primary_station": "长沙星沙服务站",
            "support_depot": "经开备件周转点",
            "urgent_response_hours": 4,
            "normal_response_hours": 24,
            "rainy_season_note": "雨季户外作业需备注防滑与电路防护",
        }
    return json.loads(path.read_text(encoding="utf-8"))


def reset_station_profile_cache() -> None:
    load_station_profile.cache_clear()


def default_station_context() -> dict[str, Any]:
    profile = load_station_profile()
    return {
        "primary_station": profile.get("primary_station", "长沙星沙服务站"),
        "support_depot": profile.get("support_depot", "经开备件周转点"),
        "urgent_response_hours": int(profile.get("urgent_response_hours") or 4),
        "normal_response_hours": int(profile.get("normal_response_hours") or 24),
        "rainy_season_note": profile.get("rainy_season_note") or "",
        "station_aliases": profile.get("station_aliases") or {},
        "jobsite_aliases": profile.get("jobsite_aliases") or {},
        "coverage_radius_km": profile.get("coverage_radius_km"),
        "crews": profile.get("crews") or [],
        "station_code": profile.get("station_code") or "",
        "ops_source": "station_profile.json_demo",
    }


def _station_alias_candidates(profile: dict[str, Any]) -> list[tuple[str, str]]:
    """(alias, canonical_station_name)，按 alias 长度降序用于最长匹配。"""
    primary = str(profile.get("primary_station") or "长沙星沙服务站")
    support = str(profile.get("support_depot") or "经开备件周转点")
    aliases = profile.get("station_aliases") or {}
    pairs: list[tuple[str, str]] = []
    for alias in aliases.get("primary") or []:
        if alias:
            pairs.append((str(alias), primary))
    for alias in aliases.get("support") or []:
        if alias:
            pairs.append((str(alias), support))
    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    return pairs


def _jobsite_alias_candidates(profile: dict[str, Any]) -> list[tuple[str, str]]:
    """(alias, canonical_jobsite)，工地 ≠ 网点/备件点。"""
    raw = profile.get("jobsite_aliases") or {}
    pairs: list[tuple[str, str]] = []
    if isinstance(raw, dict):
        for canonical, aliases in raw.items():
            for alias in aliases or []:
                if alias:
                    pairs.append((str(alias), str(canonical)))
            if canonical:
                pairs.append((str(canonical), str(canonical)))
    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    # 去重保最长优先顺序
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for alias, canonical in pairs:
        if alias in seen:
            continue
        seen.add(alias)
        out.append((alias, canonical))
    return out


def resolve_jobsite(text: str) -> str | None:
    """解析工地/作业点；不与服务站/备件周转点混用。"""
    q = text or ""
    if not q.strip():
        return None
    profile = load_station_profile()
    for alias, canonical in _jobsite_alias_candidates(profile):
        if alias in q:
            return canonical
    return None


def resolve_station_name(text: str, *, override: str | None = None) -> str | None:
    """从问句或 override 解析服务站/备件网点名。

    工地别名不映射为经开备件点：仅出现工地时归属主站（星沙）覆盖范围。
    """
    if override:
        return override.strip() or None
    q = text or ""
    if not q.strip():
        return None
    profile = load_station_profile()
    for alias, canonical in _station_alias_candidates(profile):
        if alias in q:
            return canonical
    # 工地 ≠ 网点：归属主站覆盖，jobsite 字段由 resolve_jobsite 单独给出
    if resolve_jobsite(q):
        return str(profile.get("primary_station") or "长沙星沙服务站")
    return None


def recommend_crew(
    *,
    station: str | None,
    fault_codes: list[str] | None = None,
    question: str = "",
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """演示级班组建议：站覆盖 + skills 命中故障码/液压等关键词。

    非 ERP 派工/排班；仅开单门禁提示。无命中时回退该站首个班组。
    """
    profile = profile or load_station_profile()
    crews = [c for c in (profile.get("crews") or []) if isinstance(c, dict)]
    if not crews:
        return {"recommended_crew": "", "crew_match": "none", "crew_id": ""}

    station_s = (station or "").strip()
    covered = []
    for crew in crews:
        covers = crew.get("covers_stations") or []
        if not station_s:
            covered.append(crew)
            continue
        if not covers or station_s in covers or any(str(c) in station_s for c in covers):
            covered.append(crew)
    pool = covered or crews

    needles: list[str] = [str(c).upper() for c in (fault_codes or []) if c]
    q = question or ""
    for tok in ("液压", "主控阀", "电气", "传感器", "动臂", "H103"):
        if tok.lower() in q.lower() or tok in q:
            needles.append(tok.upper() if tok.startswith("H") else tok)

    best = None
    best_score = -1
    for crew in pool:
        skills = [str(s) for s in (crew.get("skills") or [])]
        score = 0
        for n in needles:
            for sk in skills:
                if n.upper() == sk.upper() or n in sk or sk in n:
                    score += 2
                    break
        if score > best_score:
            best_score = score
            best = crew

    if best is None:
        best = pool[0]
        best_score = 0
    match = "skill" if best_score > 0 else "station_fallback"
    return {
        "recommended_crew": str(best.get("name") or best.get("id") or ""),
        "crew_id": str(best.get("id") or ""),
        "crew_match": match,
        "crew_skills": list(best.get("skills") or []),
        "crew_shift": str(best.get("shift") or ""),
        "demo_only": bool(best.get("demo_only", True)),
    }
