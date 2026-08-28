"""站点 alias 外置配置测试。"""

from __future__ import annotations

from app.domain.station import resolve_station_name


def test_xingsha_aliases():
    for q in ("星沙站 SY215C H103", "长沙星沙 报修", "星沙镇客户来电"):
        assert "星沙" in (resolve_station_name(q) or "")


def test_jingkai_support_alias():
    q = "经开周转点有没有液压滤芯"
    name = resolve_station_name(q)
    assert name and "经开" in name


def test_explicit_override():
    assert resolve_station_name("随便", override="长沙星沙服务站") == "长沙星沙服务站"
