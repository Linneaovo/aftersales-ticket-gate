"""站点 alias 外置配置测试：工地 ≠ 备件网点。"""

from __future__ import annotations

from app.domain.station import resolve_jobsite, resolve_station_name, reset_station_profile_cache
from app.domain.ticket_extract import extract_service_ticket


def setup_function():
    reset_station_profile_cache()


def test_xingsha_aliases():
    for q in ("星沙站 SY215C H103", "长沙星沙 报修", "星沙镇客户来电"):
        assert "星沙" in (resolve_station_name(q) or "")


def test_jingkai_support_alias():
    q = "经开周转点有没有液压滤芯"
    name = resolve_station_name(q)
    assert name and "经开" in name


def test_longest_alias_wins_over_short_substring():
    """「长沙星沙服务站」应优先于短 alias「星沙」。"""
    q = "请到长沙星沙服务站处理 SY215C H103"
    name = resolve_station_name(q)
    assert name == "长沙星沙服务站"


def test_langli_jobsite_maps_to_primary_station_not_depot():
    """榔梨是工地，不是经开备件周转点。"""
    q = "榔梨工地 SY215C 动臂没力"
    name = resolve_station_name(q)
    assert name and "星沙" in name
    assert "经开" not in (name or "")
    assert resolve_jobsite(q) == "榔梨工地"
    ticket = extract_service_ticket(q)
    assert "星沙" in ticket["station"]
    assert ticket["jobsite"] == "榔梨工地"


def test_huanghua_jobsite_not_depot():
    q = "黄花工地液压泵异响请报修"
    assert "星沙" in (resolve_station_name(q) or "")
    assert resolve_jobsite(q) == "黄花工地"


def test_no_station_when_unrelated_text():
    q = "SY215C 液压系统原理是什么"
    assert resolve_station_name(q) is None
    assert resolve_jobsite(q) is None


def test_explicit_override():
    assert resolve_station_name("随便", override="长沙星沙服务站") == "长沙星沙服务站"


def test_station_ops_fields_on_ticket():
    """演示站务字段：班组建议 + 覆盖半径 + SLA 截止戳（非真 CRM）。"""
    ticket = extract_service_ticket(
        "长沙星沙服务站：SY215C 报故障码 H103，动臂液压无力，请开单",
        station_override="长沙星沙服务站",
    )
    assert ticket["station"] == "长沙星沙服务站"
    assert ticket.get("recommended_crew") == "液压班-甲"
    assert ticket.get("crew_match") == "skill"
    assert ticket.get("coverage_radius_km") == 45
    assert ticket.get("intake_ts")
    assert ticket.get("sla_deadline_ts") > ticket["intake_ts"]
    assert "演示" in str(ticket.get("sla_clock_note") or "")


def test_crew_skill_prefers_hydraulic_for_h103():
    from app.domain.station import recommend_crew

    info = recommend_crew(
        station="长沙星沙服务站",
        fault_codes=["H103"],
        question="动臂液压无力",
    )
    assert info["recommended_crew"] == "液压班-甲"
    assert info["crew_match"] == "skill"


def test_crew_skill_prefers_elec_for_sensor():
    from app.domain.station import recommend_crew

    info = recommend_crew(
        station="长沙星沙服务站",
        fault_codes=[],
        question="压力传感器报警请开单",
    )
    assert info["recommended_crew"] == "电器班-乙"
    assert info["crew_match"] == "skill"

