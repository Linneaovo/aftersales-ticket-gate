from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

import httpx
import streamlit as st

COPILOT_URL = os.getenv("COPILOT_BASE_URL", "http://127.0.0.1:8002").rstrip("/")
CHIEF_KEY = "demo-chief"

PERSONAS = {
    "技师（张伟）": "demo-technician",
    "配件员（陈雨）": "demo-parts",
    "站长（刘波）": "demo-chief",
    "默认 demo-key": "demo-key",
}

from app.domain.station import load_station_profile

STATION_OPTIONS = [
    "（从问句识别，不强制默认）",
    "长沙星沙服务站",
    "经开备件周转点",
]

from app.eval.compare import ORAL_SMOKE_QUESTIONS as ORAL_DEMO_QUESTIONS


def _headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key, "Content-Type": "application/json"}


def api(method: str, path: str, api_key: str, **kwargs):
    with httpx.Client(base_url=COPILOT_URL, timeout=180.0) as client:
        resp = client.request(method, path, headers=_headers(api_key), **kwargs)
        if resp.status_code >= 400:
            raise RuntimeError(f"{resp.status_code}: {resp.text}")
        return resp.json()


def _trace_latency_chart(events: list[dict]) -> dict[str, int]:
    buckets: dict[str, int] = defaultdict(int)
    for ev in events:
        node = str(ev.get("node") or "unknown")
        ms = int(ev.get("latency_ms") or 0)
        if ms > 0:
            buckets[node] += ms
        else:
            buckets[node] += 1
    return dict(buckets)


def _fmt_service_ticket(ticket: dict) -> str:
    if not ticket:
        return "—"
    codes = ticket.get("fault_codes") or []
    role_labels = {
        "technician": "技师",
        "parts_clerk": "配件员",
        "station_chief": "站长",
        "finance": "财务",
        "general": "通用",
    }
    reporter = ticket.get("reporter_role") or ""
    reporter_label = role_labels.get(reporter, reporter)
    lines = [
        f"- **提单角色**：{reporter_label}" if reporter else None,
        f"- **机型**：{ticket.get('machine_model') or '—'}",
        f"- **故障码**：{', '.join(codes) if codes else '—'}",
        f"- **服务站**：{ticket.get('station') or '—'}",
        f"- **二次进站**：{'是' if ticket.get('second_visit') else '否'}",
        f"- **SLA**：{ticket.get('sla_class') or 'normal'}（首响 {ticket.get('response_hours') or '—'}h）",
        f"- **质保相关**：{'是' if ticket.get('warranty_claim') else '否'}",
    ]
    excerpt = str(ticket.get("raw_excerpt") or "").strip()
    if excerpt:
        lines.append(f"- **原文摘要**：{excerpt}")
    return "\n".join(p for p in lines if p)


def _fmt_conflict_bundle(cb: dict) -> str:
    if not cb or not cb.get("present"):
        return "当前无制度/质保冲突"
    lines = [f"**策略**：{cb.get('policy') or 'no_arbitration'}（并列展示，不作自动裁决）"]
    if cb.get("redacted"):
        lines.append(f"_{cb.get('reason') or '冲突明细已脱敏'}_")
        return "\n".join(lines)
    items = cb.get("items") or []
    for i, item in enumerate(items[:5], 1):
        if isinstance(item, dict):
            left = item.get("left") or item.get("doc_a") or item.get("metric") or ""
            right = item.get("right") or item.get("doc_b") or ""
            topic = item.get("topic") or item.get("metric") or f"冲突 {i}"
            lines.append(f"- **{topic}**：{left} ↔ {right}")
        else:
            lines.append(f"- {item}")
    if len(items) > 5:
        lines.append(f"- …共 {len(items)} 条")
    return "\n".join(lines)


def _fmt_parts_check(pc: dict) -> str:
    if not pc:
        return "—"
    source = pc.get("source") or "demo_ledger"
    header = f"_数据来源：本地演示台账（`{source}`），生产接 WMS/ERP_\n\n"
    if not pc.get("needed") and not pc.get("items"):
        return header + str(pc.get("note") or "未做配件预核")
    lines: list[str] = []
    for row in pc.get("items") or []:
        if not isinstance(row, dict):
            continue
        name = row.get("name") or row.get("hint") or row.get("part_no") or "—"
        stock = row.get("stock")
        status = row.get("status") or ("shortage" if (stock or 0) <= 0 else "ok")
        status_label = "[缺]" if status == "shortage" or (stock or 0) <= 0 else "[有]"
        depot = row.get("depot") or ""
        alt = row.get("alt_depot") or ""
        stock_txt = f"库存 {stock}" if stock is not None else "库存未知"
        extra = f" · 调拨至 {alt}" if alt and status == "shortage" else ""
        lines.append(f"{status_label} **{name}**（{row.get('part_no') or '—'}）— {stock_txt}{extra} · {depot}")
    if pc.get("shortage"):
        lines.append(f"\n**缺料结论**：{pc.get('note') or '存在缺料'}")
    else:
        lines.append("\n**缺料结论**：库存充足")
    return header + ("\n".join(lines) if lines else str(pc.get("note") or "—"))


def _fmt_sla_linkage(sla: dict, linkage: list, degraded: bool) -> str:
    lines: list[str] = []
    if sla:
        flags = [
            ("二次进站", sla.get("second_visit")),
            ("二次进站已确认", sla.get("second_visit_confirmed")),
            ("SLA 等级", sla.get("sla_class")),
            ("首响窗口", f"{sla.get('response_hours')}h" if sla.get("response_hours") else "—"),
            ("紧急须站长确认", sla.get("needs_chief_for_sla")),
        ]
        for label, val in flags:
            if val is not None and val != "":
                lines.append(f"- **{label}**：{val}")
    if linkage:
        lines.append(f"- **RAG 联动**：{' → '.join(linkage)}")
    if degraded:
        lines.append("- **RAG 降级**：是（须人确）")
    return "\n".join(lines) if lines else "—"


def _fmt_work_order_draft(draft: dict) -> str:
    if not draft:
        return "尚无工单草稿"
    inner = draft.get("draft") if isinstance(draft.get("draft"), dict) else draft
    codes = draft.get("fault_codes") or inner.get("fault_codes") or []
    notes = str(inner.get("notes") or draft.get("notes") or "").strip()
    parts = inner.get("parts") or draft.get("parts") or []
    lines = [
        f"- **来源**：{draft.get('source') or inner.get('source') or '—'}",
        f"- **故障码**：{', '.join(codes) if codes else '—'}",
        f"- **机型**：{inner.get('machine_model') or draft.get('machine_model') or '—'}",
        f"- **服务站**：{inner.get('station') or draft.get('station') or '—'}",
    ]
    if parts:
        lines.append(f"- **配件**：{', '.join(str(p) for p in parts[:8])}")
    if notes:
        lines.append(f"- **备注**：{notes[:200]}{'…' if len(notes) > 200 else ''}")
    return "\n".join(lines)


def _render_trace_events(events: list[dict]) -> None:
    for i, ev in enumerate(events, 1):
        node = ev.get("node") or "—"
        agent = ev.get("agent") or "—"
        tool = ev.get("tool") or "—"
        ok = ev.get("ok")
        ms = ev.get("latency_ms")
        latency = f"{ms}ms" if ms else "—"
        status = "OK" if ok else "FAIL"
        policy_ids = ev.get("policy_ids") or []
        reasons = ev.get("reasons") or []
        reporter = ev.get("reporter_role") or ev.get("service_ticket", {}).get("reporter_role") if isinstance(ev.get("service_ticket"), dict) else None
        extra: list[str] = []
        if reporter:
            extra.append(f"提单角色={reporter}")
        if policy_ids:
            extra.append(f"策略 {', '.join(policy_ids)}")
        if reasons:
            extra.append("; ".join(str(r) for r in reasons[:2]))
        tail = f" · {extra[0]}" if extra else ""
        st.markdown(f"{i}. {status} **{agent}** / `{node}` · tool={tool} · {latency}{tail}")


def _render_eval_summary(report: dict) -> None:
    summary = report.get("summary") or {}
    rows = [
        {"指标": "engine", "值": summary.get("engine", "—")},
        {"指标": "case_count", "值": summary.get("case_count", "—")},
        {"指标": "delta_miss_hitl", "值": summary.get("delta_miss_hitl", "—")},
        {"指标": "delta_false_submit", "值": summary.get("delta_false_submit", "—")},
        {"指标": "oral_cases_pass_rate", "值": summary.get("oral_cases_pass_rate", "—")},
        {"指标": "live_rag", "值": summary.get("live_rag", "—")},
    ]
    st.table(rows)


def _render_inbox_table(inbox: dict) -> None:
    items = inbox.get("items") or []
    if not items:
        st.caption("收件箱为空（mock 收件箱，非 ERP 工单号）")
        return
    rows = []
    for it in items[:10]:
        if not isinstance(it, dict):
            continue
        rows.append(
            {
                "ticket_id": it.get("ticket_id") or it.get("id") or "—",
                "状态": it.get("status") or "—",
                "摘要": str(it.get("summary") or it.get("note") or "")[:80],
            }
        )
    st.caption("RAG mock 收件箱（非 ERP 派工调度）")
    st.table(rows)


st.set_page_config(page_title="售后开单协同 Copilot", layout="wide")

PLAN_B_TRACE_PATH = Path(__file__).resolve().parents[2] / "data" / "eval" / "plan_b_trace.json"

health: dict = {}
_live_required = False
_demo_warn = False

with st.sidebar:
    st.subheader("连接")
    st.text(f"Copilot: {COPILOT_URL}")
    persona = st.selectbox("提单人设", list(PERSONAS.keys()))
    api_key = PERSONAS[persona]
    st.code(api_key)
    try:
        health = api("GET", "/health", api_key)
        _live_required = bool(health.get("live_linkage_required"))
        _demo_warn = bool(health.get("demo_mode_warning"))
        rag_mode = health.get("rag_mode", "unknown")
        if rag_mode == "live" and health.get("status") == "ok":
            st.success(f"rag_mode=**live** · RAG 真连")
        elif health.get("rag_auto_fallback"):
            st.error(f"rag_mode={rag_mode} · AUTO_FALLBACK 开启 — 演示 live 请 copy .env.demo .env")
        else:
            st.warning(health.get("hint") or f"rag_mode={rag_mode}")
        p_ok = health.get("persistence_ok")
        if p_ok is None:
            p_ok = not (health.get("persistence") or {}).get("issues")
        st.caption(
            f"**摘要** · rag_mode={rag_mode} · persistence_ok={p_ok} · "
            f"engine={health.get('engine')} · v={health.get('version', '—')}"
        )
        with st.expander("健康检查详情 JSON"):
            st.json(
                {
                    "rag_mode": rag_mode,
                    "rag_auto_fallback": health.get("rag_auto_fallback"),
                    "engine": health.get("engine"),
                    "persistence_ok": p_ok,
                    "persistence_hint": health.get("persistence_hint"),
                    "smoke_passed": health.get("smoke_passed"),
                    "last_run_status": health.get("last_run_status"),
                }
            )
    except Exception as exc:  # noqa: BLE001
        st.error(f"健康检查失败: {exc}")

    if health.get("engine_degraded") or (health.get("rag_auto_fallback") and health.get("rag_mode") != "live"):
        st.error(
            "⚠ 非生产路径："
            + (
                f"engine_degraded — {health.get('engine_degraded_reason') or health.get('hint')}"
                if health.get("engine_degraded")
                else "RAG_AUTO_FALLBACK 开启或 rag_mode≠live — 演示 live 请 copy .env.demo .env"
            )
        )

    with st.expander("Plan B · Trace 回放（RAG 不可达）"):
        if PLAN_B_TRACE_PATH.exists():
            plan_b = json.loads(PLAN_B_TRACE_PATH.read_text(encoding="utf-8"))
            st.caption(plan_b.get("scenario") or "预录 P1 trace")
            pb_events = plan_b.get("events") or []
            pb_chart = _trace_latency_chart(pb_events)
            if pb_chart:
                st.bar_chart(pb_chart)
            for i, ev in enumerate(pb_events, 1):
                st.write(
                    f"{i}. `{ev.get('agent')}`/`{ev.get('node')}` "
                    f"latency={ev.get('latency_ms', '-')}ms · "
                    + json.dumps(
                        {k: v for k, v in ev.items() if k not in {"ts", "agent", "node", "run_id", "iteration", "latency_ms"}},
                        ensure_ascii=False,
                    )[:220]
                )
            st.download_button(
                "下载 plan_b_trace.json",
                data=json.dumps(plan_b, ensure_ascii=False, indent=2),
                file_name="plan_b_trace.json",
                mime="application/json",
            )
        else:
            st.caption("未找到 data/eval/plan_b_trace.json — 见 PLAN_B.md")

    public_view_mode = st.checkbox("演示脱敏模式 (view=public)", value=True, help="多人演示时隐藏完整 draft/trace")
    role_key = {
        "技师（张伟）": "technician",
        "配件员（陈雨）": "parts_clerk",
        "站长（刘波）": "station_chief",
        "默认 demo-key": "general",
    }[persona]
    try:
        st.info(api("GET", f"/roles/path?role={role_key}&intent=fault_dispatch", api_key).get("path_hint"))
    except Exception:
        pass

    with st.expander("Policy 策略目录 (POL-*) — 答辩主线见 README"):
        st.caption("答辩只讲 5 条主线 POL；其余为扩展预留。")
        try:
            policies = api("GET", "/policies", api_key).get("items") or []
            for p in policies:
                st.markdown(f"**{p['id']}** — {p.get('label', '')}")
                if p.get("trigger"):
                    st.caption(f"触发：{p['trigger']}")
        except Exception as exc:  # noqa: BLE001
            st.caption(f"策略加载失败: {exc}")

    if st.button("A-07 对比（离线 FakeRAG）"):
        st.session_state["eval_report"] = api("POST", "/eval/compare?engine=langgraph&live_rag=false", api_key)
        st.session_state["eval_mode"] = "offline"
    if st.button("A-07 对比（live RAG · 需 :8001）"):
        try:
            st.session_state["eval_report"] = api("POST", "/eval/compare?engine=langgraph&live_rag=true", api_key)
            st.session_state["eval_mode"] = "live"
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))
    if st.button("刷新收件箱"):
        try:
            st.session_state["inbox"] = api("GET", "/inbox?limit=5", CHIEF_KEY)
        except Exception as exc:  # noqa: BLE001
            st.session_state["inbox_err"] = str(exc)

    st.subheader("剧本")
    try:
        playbooks = api("GET", "/playbooks", api_key).get("items") or []
    except Exception:
        playbooks = []
    pb_labels = {f"{p['id']} · {p.get('title')}": p["id"] for p in playbooks}
    choice = st.selectbox("选择剧本", ["（手动输入）"] + list(pb_labels.keys()))
    if choice != "（手动输入）" and st.button("一键跑剧本"):
        view_q = "?view=public" if public_view_mode else ""
        st.session_state["last_run"] = api("POST", f"/playbooks/{pb_labels[choice]}/run{view_q}", api_key)

    st.subheader("口语报修（非 playbook）")
    oral_q = st.selectbox("预设问句", ORAL_DEMO_QUESTIONS)
    if st.button("跑口语问句"):
        st.session_state["question"] = oral_q

st.title("长株潭工程机械售后开单协同 Copilot（LangGraph 门禁编排）")
st.caption("知识层 enterprise-rag · 行动层开单协同/门禁编排/mock 收件箱 · **不含 ERP 技师派工调度**")

if _demo_warn or (run := st.session_state.get("last_run")) and run.get("rag_client_mode") == "demo_offline":
    st.error(
        "**非 live 联调**：当前为 DemoRag 离线替身或 demo_mode_warning=true。"
        "答辩请 `copy .env.demo .env` 并启动 enterprise-rag :8001。"
    )
elif _demo_warn:
    st.error(
        "**非 live 联调模式**（`demo_mode_warning=true`）。演示前请 `copy .env.demo .env` 并确认 `rag_mode=live`。"
    )
elif _live_required and health.get("rag_mode") == "live":
    st.success("live 联调模式已启用 — 可开始协同演示")

question = st.text_area(
    "报修/查询内容",
    value=st.session_state.get(
        "question",
        "长沙星沙服务站：SY215C 报故障码 H103，客户反映动臂液压无力，请安排报修开单",
    ),
    height=100,
    key="question_input",
    help="建议写明服务站与机型；未识别站名时将触发 POL-STATION-01 站长确认。",
)
station_choice = st.selectbox("服务站（显式传入 API）", STATION_OPTIONS, index=1)
station_param = None if station_choice.startswith("（") else station_choice
if station_choice.startswith("（"):
    st.caption("未选站：仅依赖问句 alias 识别；识别不到则 **不默认星沙**，走 POL-STATION-01 人确。")
c1, c2, c3 = st.columns(3)
with c1:
    auto_submit = st.checkbox("站长人确后自动提交收件箱", value=False)
with c2:
    second_visit = st.checkbox("二次进站", value=False)
with c3:
    kb = st.text_input("知识库", value="demo-kb")

if st.button("开始协同", type="primary", disabled=_live_required and health.get("rag_mode") != "live"):
    try:
        if _live_required and health.get("rag_mode") != "live":
            st.error("live 模式要求 RAG 可达。请先启动 enterprise-rag :8001。")
        else:
            view_q = "?view=public" if public_view_mode else ""
            st.session_state["last_run"] = api(
                "POST",
                f"/runs{view_q}",
                api_key,
                json={
                    "question": question,
                    "knowledge_base": kb,
                    "api_key": api_key,
                    "auto_submit": auto_submit,
                    "second_visit": second_visit,
                    **({"station": station_param} if station_param else {}),
                },
            )
    except Exception as exc:  # noqa: BLE001
        st.error(str(exc))
elif _live_required and health.get("rag_mode") != "live":
    st.caption("「开始协同」已禁用：当前非 live 模式。")

if st.session_state.get("eval_report"):
    st.subheader("A-07 基线对比（漏人确 / 误开单 / 越权）")
    summary = st.session_state["eval_report"].get("summary") or {}
    mode_label = st.session_state.get("eval_mode") or ("live" if summary.get("live_rag") else "offline")
    st.caption(
        f"engine={summary.get('engine', 'langgraph')} · cases={summary.get('case_count')} · mode={mode_label}"
        f" · oral_pass={summary.get('oral_cases_pass_rate', '—')}"
    )
    _render_eval_summary(st.session_state["eval_report"])
    comps = st.session_state["eval_report"].get("comparisons") or []
    b01 = next((c for c in comps if c.get("id") == "B01"), None)
    if b01:
        with st.expander("B01 具体 diff（答辩可贴 PPT）"):
            st.table(
                [
                    {"字段": k, "裸链": v.get("single_tool") if isinstance(v, dict) else v, "Copilot": v.get("copilot") if isinstance(v, dict) else "—"}
                    for k, v in (b01.get("diff") or b01.items())
                    if k not in {"id", "question"}
                ][:8]
                or [{"说明": json.dumps(b01, ensure_ascii=False)[:500]}]
            )
            with st.expander("B01 原始 JSON"):
                st.json(b01)

if st.session_state.get("inbox"):
    st.subheader("RAG mock 收件箱（非 ERP）")
    _render_inbox_table(st.session_state["inbox"])
    with st.expander("收件箱原始 JSON"):
        st.json(st.session_state["inbox"])
if st.session_state.get("inbox_err"):
    st.caption(st.session_state["inbox_err"])

run = st.session_state.get("last_run")
if run:
    linkage = run.get("rag_linkage") or []
    st.subheader(
        f"运行 {run.get('run_id')} · {run.get('status')} · "
        f"engine={run.get('engine', 'langgraph')} · path={run.get('execution_path', '—')} · "
        f"wo_state={run.get('work_order_state', '—')} · rag_mode={run.get('rag_client_mode', '—')}"
    )
    if run.get("work_order_state") == "ready_for_chief":
        st.info("技师侧草稿已就绪（`ready_for_chief`），待站长 Key 提交 mock 收件箱。")
    if linkage:
        st.success(f"RAG 联动链路 ({len(linkage)}): {' → '.join(linkage)}")
    elif not run.get("rag_offline_mode"):
        st.warning("rag_linkage 为空 — 可能未走完整 ask/retrieve/draft 路径")
    if run.get("rag_offline_mode"):
        st.error("当前为 **DemoRag 离线兜底** — 非 live 联调，请检查 RAG_AUTO_FALLBACK=0")
    if run.get("engine_degraded") or run.get("engine") == "fallback":
        st.error(
            f"⚠ 执行引擎已降级（engine={run.get('engine')}）："
            f"{run.get('engine_degraded_reason') or run.get('error') or 'fallback 容灾路径'}"
        )
        st.caption("生产路径仅 langgraph；fallback 仅 LangGraph 异常容灾，勿当作主路径。")
    meta = run.get("playbook_meta") or {}
    if meta.get("business_background"):
        st.info(f"**业务背景**：{meta['business_background']}")
    if meta:
        v_ok = meta.get("validation_passed")
        if v_ok is True:
            st.success("剧本规格验证通过")
        elif v_ok is False:
            st.error("剧本规格验证未通过")
            st.json(meta.get("validation_diffs") or meta.get("diffs") or [])
        with st.expander("剧本 expect vs actual"):
            st.json(
                {
                    "expect_status": meta.get("expect_status"),
                    "expect_intent": meta.get("expect_intent"),
                    "expect_hitl_reasons": meta.get("expect_hitl_reasons"),
                    "actual_status": run.get("status"),
                    "actual_intent": run.get("intent"),
                }
            )
    st.write(run.get("final_summary") or run.get("error") or "")
    a, b, c, d = st.columns(4)
    with a:
        st.markdown("**报修作业单**")
        st.markdown(_fmt_service_ticket(run.get("service_ticket") or {}))
        with st.expander("原始 JSON"):
            st.json(run.get("service_ticket") or {})
    with b:
        st.markdown("**冲突束（不作裁决）**")
        cb = run.get("conflict_bundle") or {}
        if cb.get("redacted"):
            st.info("配件岗视角：冲突明细已脱敏")
        st.markdown(_fmt_conflict_bundle(cb))
        with st.expander("原始 JSON"):
            st.json(cb)
    with c:
        st.markdown("**配件缺口**")
        pc = run.get("parts_check") or {}
        if pc.get("suggested_action"):
            st.warning(pc.get("suggested_action"))
        st.markdown(_fmt_parts_check(pc))
        with st.expander("原始 JSON"):
            st.json(pc)
    with d:
        st.markdown("**SLA / 联动**")
        st.markdown(
            _fmt_sla_linkage(
                run.get("sla_flags") or {},
                list(run.get("rag_linkage") or []),
                bool(run.get("rag_degraded")),
            )
        )
        with st.expander("原始 JSON"):
            st.json(
                {
                    "sla_flags": run.get("sla_flags"),
                    "rag_linkage": run.get("rag_linkage"),
                    "degraded": run.get("rag_degraded"),
                }
            )

    st.markdown("**知识摘要**")
    st.write((run.get("rag") or {}).get("answer") or "—")

    if run.get("status") == "waiting_hitl":
        st.warning("待站长确认（须站长角色 API Key；技师 Key 将返回 403）")
        st.write((run.get("hitl") or {}).get("prompt"))
        for r in (run.get("hitl") or {}).get("reasons") or []:
            st.write(f"- {r}")
        note = st.text_input("确认/改单备注", value="")
        hitl_q = "?view=public" if public_view_mode else ""
        x, y, z = st.columns(3)
        with x:
            if st.button("站长批准"):
                st.session_state["last_run"] = api(
                    "POST", f"/runs/{run['run_id']}/hitl{hitl_q}", CHIEF_KEY, json={"decision": "approve", "note": note}
                )
                st.rerun()
        with y:
            if st.button("站长拒绝"):
                st.session_state["last_run"] = api(
                    "POST", f"/runs/{run['run_id']}/hitl{hitl_q}", CHIEF_KEY, json={"decision": "reject", "note": note}
                )
                st.rerun()
        with z:
            if st.button("改单(需备注)"):
                try:
                    st.session_state["last_run"] = api(
                        "POST",
                        f"/runs/{run['run_id']}/hitl{hitl_q}",
                        CHIEF_KEY,
                        json={"decision": "edit", "note": note or "请补充现场照片后重提"},
                    )
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))

    st.markdown("**工单草稿**")
    st.markdown(_fmt_work_order_draft(run.get("work_order_draft") or {}))
    with st.expander("工单草稿原始 JSON"):
        st.json(run.get("work_order_draft") or {})
    if run.get("work_order_submit"):
        st.markdown("**已提交 mock 收件箱**")
        submit = run.get("work_order_submit") or {}
        ticket_id = submit.get("ticket_id") or submit.get("id") or "—"
        dest = submit.get("destination") or "rag_mock_inbox"
        is_prod = submit.get("is_production_ticket", False)
        st.success(
            f"**destination={dest}** · ticket_id={ticket_id} · is_production_ticket={is_prod}\n\n"
            "此为 RAG 侧 mock 收件箱，**非 ERP 工单号**。可在侧边栏「刷新收件箱」回读。"
        )
        with st.expander("提交回执 JSON"):
            st.json(submit)
        st.caption(f"反馈回写: {run.get('feedback_ref')}")

    events = run.get("trace_events") or []
    policy_summary = run.get("trace_policy_summary") or []
    if policy_summary:
        st.caption(f"触发策略: {', '.join(policy_summary)}")
    st.markdown("**节点耗时**")
    chart_data = _trace_latency_chart(events)
    if chart_data:
        st.bar_chart(chart_data)
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        if st.button("导出 Trace JSON"):
            st.download_button(
                "下载 trace.json",
                data=json.dumps({"run_id": run.get("run_id"), "events": events}, ensure_ascii=False, indent=2),
                file_name=f"trace_{run.get('run_id')}.json",
                mime="application/json",
            )
    with col_t2:
        if run.get("run_id"):
            try:
                full_trace = api("GET", f"/runs/{run['run_id']}/trace", api_key)
                st.caption(f"trace 节点数: {len(full_trace.get('events') or [])}")
            except Exception:
                pass

    st.markdown("**完整 Trace**")
    _render_trace_events(events)
