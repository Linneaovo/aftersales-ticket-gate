from __future__ import annotations

import html
import json
import os
import re
from collections import defaultdict

import httpx
import streamlit as st

from app.branding import APP_TITLE
from app.policy.rules_catalog import POLICIES
from app.ui.styles import PAGE_STYLE

_POL_TAG_RE = re.compile(r"\[(POL-[A-Z0-9-]+)\]")
_FRIENDLY_SWAPS = (
    ("站长人确", "站长确认"),
    ("须人确", "须站长确认"),
    ("人确批准", "站长确认批准"),
    ("人确", "站长确认"),
    ("不可直接 submit", "不可直接提交"),
    ("submit", "提交"),
    ("role=technician", "当前为技师"),
    ("role=parts_clerk", "当前为配件员"),
    ("role=station_chief", "当前为站长"),
    ("mock inbox", "演示收件箱"),
    ("rag_mock_inbox", "演示收件箱"),
    ("file_outbox", "本地提交记录"),
    ("outbox", "提交记录"),
)

COPILOT_URL = os.getenv("COPILOT_BASE_URL", "http://127.0.0.1:8002").rstrip("/")

LAYER_LABELS_SHORT = {
    "conflict": "制度/质保冲突确认",
    "shortage": "缺料确认",
    "sla": "时效确认",
    "degrade": "知识源降级确认",
    "station": "服务站归属确认",
    "ledger": "台账/件号确认",
    "weather": "户外作业确认",
    "intent": "意图低置信确认",
}

INTENT_LABELS = {
    "fault_dispatch": "报修开单",
    "parts_inquiry": "配件查询",
    "conflict_review": "冲突复核",
    "knowledge_only": "知识查询",
}

LINKAGE_LABELS = {
    "ask": "问答",
    "retrieve": "检索",
    "ask.work_order": "开单",
    "work_orders.draft": "开单",
    "work_orders.submit": "提交",
    "feedback": "反馈",
}

RAG_UI_URL = os.getenv("RAG_UI_URL", "http://127.0.0.1:8501")


def _chief_api_key() -> str:
    from app.policy.gates import _chief_keys, _role_default_keys

    chiefs = _chief_keys()
    if chiefs:
        return next(iter(chiefs))
    return _role_default_keys().get("station_chief", "demo-chief")


CHIEF_KEY = _chief_api_key()

PERSONAS = {
    "技师（张伟）": "demo-technician",
    "配件员（陈雨）": "demo-parts",
    "站长（刘波）": "demo-chief",
}

SCENE_LABELS = {
    "p1_xingsha_h103": "缺料报修",
    "p1b_no_shortage_ready": "有库存",
    "p8_parts_clerk_conflict": "制度冲突",
    "p10_wangcheng_shortage": "望城缺料",
    "p9_liuyang_pump_leak": "浏阳渗油",
}

STATION_OPTIONS = [
    "自动识别",
    "长沙星沙服务站",
    "经开备件周转点",
]

from app.eval.compare import ORAL_SMOKE_QUESTIONS as ORAL_DEMO_QUESTIONS  # noqa: E402


def _headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key, "Content-Type": "application/json"}


def api(method: str, path: str, api_key: str, **kwargs):
    with httpx.Client(base_url=COPILOT_URL, timeout=180.0) as client:
        resp = client.request(method, path, headers=_headers(api_key), **kwargs)
        if resp.status_code >= 400:
            raise RuntimeError(f"{resp.status_code}: {resp.text}")
        return resp.json()


def _uses_inbox(health: dict) -> bool:
    return str(health.get("submit_destination") or "") == "rag_mock_inbox"


def _is_live(health: dict) -> bool:
    return str(health.get("rag_mode") or "") == "live"


def _is_standalone(health: dict) -> bool:
    return str(health.get("runtime_mode") or "") == "standalone"


def _flow_steps(health: dict) -> tuple[str, ...]:
    if _uses_inbox(health):
        return ("报修", "门禁", "确认", "收件")
    return ("报修", "门禁", "确认", "落箱")


def _refresh_submit_records(health: dict) -> None:
    try:
        if _uses_inbox(health):
            st.session_state["inbox"] = api("GET", "/inbox?limit=10", CHIEF_KEY)
            st.session_state.pop("outbox", None)
        else:
            st.session_state["outbox"] = api("GET", "/outbox?limit=10", CHIEF_KEY)
            st.session_state.pop("inbox", None)
        st.session_state.pop("submit_err", None)
    except Exception as exc:  # noqa: BLE001
        st.session_state["submit_err"] = str(exc)


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
        "hr": "人事",
        "general": "通用",
    }
    reporter = ticket.get("reporter_role") or ""
    reporter_label = role_labels.get(reporter, reporter)
    lines = [
        f"- **提单角色**：{reporter_label}" if reporter else None,
        f"- **机型**：{ticket.get('machine_model') or '—'}",
        f"- **故障码**：{', '.join(codes) if codes else '—'}",
        f"- **服务站**：{ticket.get('station') or '—'}",
        f"- **工地**：{ticket.get('jobsite')}" if ticket.get("jobsite") else None,
        f"- **二次进站**：{'是' if ticket.get('second_visit') else '否'}",
        f"- **时效**：{ticket.get('sla_class') or 'normal'}（窗口 {ticket.get('response_hours') or '—'}h）",
        f"- **质保相关**：{'是' if ticket.get('warranty_claim') else '否'}",
    ]
    excerpt = str(ticket.get("raw_excerpt") or "").strip()
    if excerpt:
        lines.append(f"- **原文摘要**：{excerpt}")
    return "\n".join(p for p in lines if p)


def _friendly_text(text: str) -> str:
    """把内部策略码/黑话转成演示可读文案（不改 API 原文）。"""
    out = str(text or "")

    def _repl(m: re.Match[str]) -> str:
        pid = m.group(1)
        label = POLICIES.get(pid, pid)
        for a, b in _FRIENDLY_SWAPS:
            label = label.replace(a, b)
        return label

    out = _POL_TAG_RE.sub(_repl, out)
    for a, b in _FRIENDLY_SWAPS:
        out = out.replace(a, b)
    return out


def _fmt_conflict_bundle(cb: dict) -> str:
    if not cb or not cb.get("present"):
        return ""
    policy = cb.get("policy") or "no_arbitration"
    policy_label = "并列展示，不作自动裁决" if policy == "no_arbitration" else str(policy)
    lines = [f"**处理方式**：{policy_label}"]
    if cb.get("redacted"):
        lines.append(f"_{_friendly_text(cb.get('reason') or '敏感明细已隐藏，请换站长查看')}_")
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
    if not pc.get("needed") and not pc.get("items"):
        return str(pc.get("note") or "未做配件预核")
    lines: list[str] = []
    for row in pc.get("items") or []:
        if not isinstance(row, dict):
            continue
        name = row.get("name") or row.get("hint") or row.get("part_no") or "—"
        stock = row.get("stock")
        status = row.get("status") or ("shortage" if (stock or 0) <= 0 else "ok")
        status_label = "[缺]" if status == "shortage" or (stock or 0) <= 0 else "[有]"
        depot = row.get("depot") or ""
        stock_txt = f"库存 {stock}" if stock is not None else "库存未知"
        lines.append(f"{status_label} **{name}** — {stock_txt} · {depot}")
    if pc.get("shortage"):
        lines.append(f"\n**缺料结论**：{pc.get('note') or '存在缺料'}")
    else:
        lines.append("\n**缺料结论**：库存充足")
    return "\n".join(lines) if lines else str(pc.get("note") or "—")


def _fmt_sla_linkage(sla: dict, linkage: list, degraded: bool) -> str:
    lines: list[str] = []
    if sla:
        flags = [
            ("二次进站", sla.get("second_visit")),
            ("时效等级", sla.get("sla_class")),
            ("首响窗口", f"{sla.get('response_hours')}h" if sla.get("response_hours") else None),
            ("紧急须站长确认", sla.get("needs_chief_for_sla")),
        ]
        for label, val in flags:
            if val is None or val == "":
                continue
            if isinstance(val, bool):
                val = "是" if val else "否"
            lines.append(f"- **{label}**：{val}")
    if linkage and st.session_state.get("show_advanced"):
        lines.append(f"- **调用链**：{' → '.join(linkage)}")
    if degraded:
        lines.append("- **知识降级**：是（须站长确认）")
    return "\n".join(lines) if lines else ""


def _fmt_work_order_draft(draft: dict) -> str:
    if not draft:
        return "尚无工单草稿"
    inner = draft.get("draft") if isinstance(draft.get("draft"), dict) else draft
    codes = draft.get("fault_codes") or inner.get("fault_codes") or []
    notes = str(inner.get("notes") or draft.get("notes") or "").strip()
    parts = inner.get("parts") or draft.get("parts") or []
    lines = [
        f"- **来源**：{_friendly_text(str(draft.get('source') or inner.get('source') or '—'))}",
        f"- **故障码**：{', '.join(codes) if codes else '—'}",
        f"- **机型**：{inner.get('machine_model') or draft.get('machine_model') or '—'}",
        f"- **服务站**：{inner.get('station') or draft.get('station') or '—'}",
    ]
    if parts:
        lines.append(f"- **配件**：{', '.join(str(p) for p in parts[:8])}")
    if notes:
        lines.append(f"- **备注**：{notes[:200]}{'…' if len(notes) > 200 else ''}")
    return "\n".join(lines)


def _fmt_rag_sources(rag: dict, *, limit: int = 3) -> str:
    sources = (rag or {}).get("sources") or []
    if not sources:
        return ""
    lines: list[str] = []
    for src in sources[:limit]:
        if not isinstance(src, dict):
            continue
        chunk = src.get("chunk") if isinstance(src.get("chunk"), dict) else {}
        name = chunk.get("source") or src.get("source") or chunk.get("doc_id") or "—"
        score = src.get("score")
        score_txt = f" · 相关度 {float(score):.0%}" if score is not None else ""
        lines.append(f"- {name}{score_txt}")
    return "\n".join(lines)


def _fmt_cert_summary(cert: dict) -> str:
    if not cert:
        return ""
    phase_map = {"pending": "待确认", "resolved": "已确认", "auto": "自动通过"}
    phase = phase_map.get(str(cert.get("phase") or ""), "—")
    dest = _friendly_text(str(cert.get("destination") or "—"))
    tid = cert.get("ticket_id") or "—"
    return f"{phase} · {tid} · {dest}"


def _render_cert_line(cert: dict) -> None:
    summary = _fmt_cert_summary(cert)
    if not summary:
        return
    st.markdown(
        f'<p class="cert-summary">审批留痕 · {html.escape(summary)}</p>',
        unsafe_allow_html=True,
    )


def _render_trace_events(events: list[dict]) -> None:
    for i, ev in enumerate(events, 1):
        node = ev.get("node") or "—"
        agent = ev.get("agent") or "—"
        tool = ev.get("tool") or "—"
        ok = ev.get("ok")
        ms = ev.get("latency_ms")
        latency = f"{ms}ms" if ms else "—"
        status = "OK" if ok else "FAIL"
        st.markdown(f"{i}. {status} **{agent}** / `{node}` · tool={tool} · {latency}")


def _render_eval_summary(report: dict) -> None:
    summary = report.get("summary") or {}
    rows = [
        {"指标": "引擎", "值": summary.get("engine", "—")},
        {"指标": "用例数", "值": summary.get("case_count", "—")},
        {"指标": "漏拦 HITL 差值", "值": summary.get("delta_miss_hitl", "—")},
        {"指标": "口语用例通过率", "值": summary.get("oral_cases_pass_rate", "—")},
    ]
    st.table(rows)


def _render_submit_records(health: dict, run: dict | None = None) -> None:
    label = "收件记录" if _uses_inbox(health) else "提交记录"
    st.markdown(
        f'<p class="section-label" id="submit-records">{html.escape(label)}</p>',
        unsafe_allow_html=True,
    )
    highlight_ticket = None
    if run:
        sub = run.get("work_order_submit") or {}
        highlight_ticket = sub.get("ticket_id") or st.session_state.get("highlight_ticket")

    if _uses_inbox(health):
        items = (st.session_state.get("inbox") or {}).get("items") or []
        if not items:
            st.caption("暂无收件记录")
            return
        if highlight_ticket:
            st.markdown(
                f'<p class="record-highlight">本次提交：{html.escape(str(highlight_ticket))}</p>',
                unsafe_allow_html=True,
            )
        rows = []
        jump_map: dict[str, str] = {}
        for it in items[:8]:
            if not isinstance(it, dict):
                continue
            tid = str(it.get("ticket_id") or it.get("id") or "—")
            src = str(it.get("source") or "")
            src_label = "站长批准" if src == "copilot_hitl" else (src or "—")
            note = str(it.get("summary") or it.get("note") or "")
            mark = "★ " if highlight_ticket and tid == str(highlight_ticket) else ""
            rows.append(
                {
                    "单号": f"{mark}{tid}",
                    "来源": src_label,
                    "提交人": it.get("submitted_by") or "—",
                    "摘要": note[:50] or "—",
                }
            )
            rid = str(it.get("run_id") or "")
            if rid:
                jump_map[tid] = rid
        st.table(rows)
        if jump_map:
            pick_tid = st.selectbox("关联单据", list(jump_map.keys()), key="inbox_jump_pick")
            if st.button("打开关联单据", key="inbox_jump_open"):
                view_q = "?view=public" if st.session_state.get("public_view_mode", True) else ""
                st.session_state["last_run"] = api(
                    "GET", f"/runs/{jump_map[pick_tid]}{view_q}", CHIEF_KEY
                )
                st.rerun()
        return

    items = (st.session_state.get("outbox") or {}).get("items") or []
    if not items:
        st.caption("暂无提交记录")
        return
    highlight_run = (run or {}).get("run_id") or st.session_state.get("highlight_run_id")
    if highlight_run:
        st.markdown(
            f'<p class="record-highlight">本次提交：{html.escape(str(highlight_run))}</p>',
            unsafe_allow_html=True,
        )
        if st.button("打开本次单据", key="outbox_jump_open"):
            view_q = "?view=public" if st.session_state.get("public_view_mode", True) else ""
            st.session_state["last_run"] = api(
                "GET", f"/runs/{highlight_run}{view_q}", CHIEF_KEY
            )
            st.rerun()
    st.table(
        [
            {
                "单号": (
                    f"★ {it.get('run_id')}"
                    if highlight_run and str(it.get("run_id")) == str(highlight_run)
                    else it.get("run_id")
                ),
                "票据": it.get("ticket_id"),
                "去向": _friendly_text(str(it.get("destination") or "—")),
            }
            for it in items[:8]
            if isinstance(it, dict)
        ]
    )


def _primary_reason(run: dict) -> str:
    pc = run.get("parts_check") or {}
    if pc.get("shortage"):
        return "配件缺料"
    cb = run.get("conflict_bundle") or {}
    if cb.get("present"):
        return "制度冲突，须人工确认"
    reasons = (run.get("hitl") or {}).get("reasons") or []
    joined = " ".join(str(r) for r in reasons)
    if "PARTS" in joined or "缺料" in joined:
        return "配件缺料"
    if "CONFLICT" in joined or "冲突" in joined:
        return "冲突待确认"
    if "SLA" in joined:
        return "时效待确认"
    if "DEGRADE" in joined or "降级" in joined:
        return "知识源降级"
    if "ROLE" in joined:
        return "须站长确认后才能提交"
    if reasons:
        return str(reasons[0])[:80]
    if run.get("work_order_state") == "ready_for_chief":
        return "有库存，对照场景不必落箱"
    return ""


def _status_view(run: dict | None, health: dict | None = None) -> dict[str, str] | None:
    if not run:
        return None
    status = str(run.get("status") or "")
    linkage_suffix = ""
    if health and _is_live(health):
        lt = _linkage_text(run)
        if lt:
            linkage_suffix = f" · 联动 {lt}"
    if status == "waiting_hitl":
        return {
            "kind": "warn",
            "title": "待站长确认",
            "detail": _primary_reason(run) + linkage_suffix,
        }
    if status == "succeeded" and run.get("work_order_submit"):
        submit = run.get("work_order_submit") or {}
        dest = _friendly_text(str(submit.get("destination") or "提交记录"))
        tid = submit.get("ticket_id") or submit.get("id") or "—"
        return {
            "kind": "ok",
            "title": "已提交",
            "detail": f"{dest} · {tid}{linkage_suffix}",
        }
    if status == "succeeded":
        return {
            "kind": "ok",
            "title": "已完成",
            "detail": (_primary_reason(run) or "—") + linkage_suffix,
        }
    if status == "rejected":
        return {"kind": "err", "title": "已拒绝", "detail": _primary_reason(run) + linkage_suffix}
    if status == "cancelled":
        return {"kind": "err", "title": "已取消", "detail": "单据已取消" + linkage_suffix}
    if status == "failed":
        return {"kind": "err", "title": "失败", "detail": str(run.get("error") or "—") + linkage_suffix}
    return {"kind": "ok", "title": status or "运行中", "detail": _primary_reason(run) + linkage_suffix}


def _flow_step_states(run: dict | None, health: dict) -> list[tuple[str, str]]:
    steps = _flow_steps(health)
    if not run:
        return [(steps[0], "active"), (steps[1], ""), (steps[2], ""), (steps[3], "")]
    status = str(run.get("status") or "")
    if status == "waiting_hitl":
        return [(steps[0], "done"), (steps[1], "done"), (steps[2], "active"), (steps[3], "")]
    if status == "succeeded" and run.get("work_order_submit"):
        return [(s, "done") for s in steps]
    if run.get("work_order_state") == "ready_for_chief":
        return [(steps[0], "done"), (steps[1], "done"), (steps[2], "active"), (steps[3], "")]
    if status in {"rejected", "cancelled", "failed"}:
        return [(steps[0], "done"), (steps[1], "done"), (steps[2], "done"), (steps[3], "")]
    return [(steps[0], "done"), (steps[1], "active"), (steps[2], ""), (steps[3], "")]


def _render_step_row(run: dict | None, health: dict) -> None:
    chips = []
    for label, state in _flow_step_states(run, health):
        cls = f"step-chip {state}".strip()
        chips.append(f'<span class="{html.escape(cls)}">{html.escape(label)}</span>')
    st.markdown(f'<div class="step-row">{"".join(chips)}</div>', unsafe_allow_html=True)


def _render_mode_banner(health: dict) -> None:
    from app.ui.health_banner import mode_banner_kind

    kind = mode_banner_kind(health)
    if kind == "unreachable":
        st.markdown(
            '<div class="portfolio-warn unreachable">'
            "<strong>API 不可达</strong> · 无法读取 /health"
            f' · 请确认 Copilot 已在 <code>{html.escape(COPILOT_URL)}</code> 启动'
            '<span class="tier">单仓：start_standalone.cmd · 勿把本状态说成联调</span>'
            "</div>",
            unsafe_allow_html=True,
        )
        return
    if kind == "standalone":
        st.markdown(
            '<div class="portfolio-warn standalone">'
            "<strong>单仓演示</strong> · 内置知识 · 本地落箱"
            "</div>",
            unsafe_allow_html=True,
        )
        return
    rag = health.get("rag") or {}
    rag_ok = bool(rag.get("ok")) and str(health.get("rag_mode") or "") == "live"
    if kind == "l1":
        st.markdown(
            '<div class="portfolio-warn joint">'
            "<strong>L1 契约联调</strong> · HTTP 桩可达 · 证契约不证检索 · 不得称 live_verified"
            "</div>",
            unsafe_allow_html=True,
        )
        return
    rag_txt = "知识库已连接" if rag_ok else "知识库未就绪"
    label = "L2 Live" if kind == "l2" else "联调模式"
    st.markdown(
        '<div class="portfolio-warn joint">'
        f"<strong>{html.escape(label)}</strong> · {html.escape(rag_txt)} · 开单须站长确认"
        f' · <a class="mode-link" href="{html.escape(RAG_UI_URL)}" target="_blank">知识库</a>'
        "</div>",
        unsafe_allow_html=True,
    )


def _render_degrade_hint(health: dict, run: dict | None) -> None:
    rag = health.get("rag") or {}
    degraded = bool((run or {}).get("rag_degraded"))
    rag_down = _is_live(health) and not bool(rag.get("ok"))
    if not degraded and not rag_down:
        return
    if rag_down:
        st.warning("知识库未就绪，当前无法完成联调提交。")
    elif degraded:
        st.warning("知识回答已降级，须站长确认后再提交。")


def _linkage_text(run: dict) -> str:
    linkage = list(run.get("rag_linkage") or [])
    if not linkage:
        return ""
    labels = [LINKAGE_LABELS.get(x, x) for x in linkage]
    return " → ".join(labels)


def _render_linkage_line(run: dict, health: dict) -> None:
    if not _is_live(health):
        return
    text = _linkage_text(run)
    if not text:
        return
    st.markdown(
        f'<p class="linkage-line">联动：{html.escape(text)}</p>',
        unsafe_allow_html=True,
    )


def _render_status_banner(view: dict[str, str] | None) -> None:
    if not view:
        return
    kind = view.get("kind") or "idle"
    detail = view.get("detail") or ""
    detail_html = f'<p class="reason">{html.escape(detail)}</p>' if detail else ""
    st.markdown(
        f'<div class="status-banner {html.escape(kind)}">'
        f'<p class="title">{html.escape(view.get("title") or "")}</p>'
        f"{detail_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


def _render_intent_line(run: dict) -> None:
    conf = run.get("intent_confidence")
    if conf is None:
        return
    from app.domain.intent_rules import resolve_intent_confidence_threshold

    intent = str(run.get("intent") or run.get("intent_label") or "")
    label = INTENT_LABELS.get(intent, intent)
    thr = resolve_intent_confidence_threshold()
    low = float(conf) < thr
    text = f"意图 {label} · 置信 {float(conf):.0%}"
    if low:
        st.markdown(
            f'<p class="intent-warn">{html.escape(text)} · 需站长确认</p>',
            unsafe_allow_html=True,
        )


def _md_bold_html(text: str) -> str:
    safe = html.escape(_friendly_text(text or "—"))
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)


def _result_cards_html(cards: list[tuple[str, str, str]]) -> str:
    parts = ['<div class="results-grid">']
    for title, body, kind in cards:
        body_html = "<br/>".join(
            _md_bold_html(line) for line in (body or "—").splitlines() if line.strip()
        )
        parts.append(
            f'<div class="result-card {html.escape(kind)}">'
            f"<h4>{html.escape(title)}</h4>"
            f'<div class="card-body">{body_html or "—"}</div>'
            f"</div>"
        )
    parts.append("</div>")
    return "".join(parts)


def _build_result_cards(run: dict, health: dict) -> list[tuple[str, str, str]]:
    cards: list[tuple[str, str, str]] = [
        ("报修单", _fmt_service_ticket(run.get("service_ticket") or {}), "primary"),
    ]
    conflict_body = _fmt_conflict_bundle(run.get("conflict_bundle") or {})
    if conflict_body:
        cards.append(("冲突", conflict_body, "accent"))
    pc = run.get("parts_check") or {}
    parts_body = _fmt_parts_check(pc)
    if pc.get("suggested_action"):
        parts_body = f"{pc.get('suggested_action')}\n{parts_body}"
    cards.append(("配件", parts_body, "accent"))
    sla_body = _fmt_sla_linkage(
        run.get("sla_flags") or {},
        [] if _is_live(health) else list(run.get("rag_linkage") or []),
        bool(run.get("rag_degraded")),
    )
    if sla_body:
        cards.append(("时效", sla_body, "primary"))
    return cards


def _render_hitl_panel(
    run: dict,
    *,
    public_view_mode: bool,
    is_chief: bool,
    health: dict,
) -> None:
    status = str(run.get("status") or "")
    if status == "waiting_hitl":
        from app.policy.hitl_layers import LAYER_LABELS

        st.markdown('<p class="section-label">站长确认</p>', unsafe_allow_html=True)
        st.markdown('<div class="hitl-panel">', unsafe_allow_html=True)
        st.write(_friendly_text((run.get("hitl") or {}).get("prompt") or "等待确认"))
        for r in (run.get("hitl") or {}).get("reasons") or []:
            st.write(f"- {_friendly_text(str(r))}")
        pending = list((run.get("hitl") or {}).get("pending_layers") or [])
        conf: dict[str, bool] = {}
        for layer in pending:
            label = LAYER_LABELS_SHORT.get(layer) or LAYER_LABELS.get(layer, layer)
            conf[layer] = st.checkbox(
                label,
                value=False,
                key=f"hitl_layer_{run.get('run_id')}_{layer}",
            )
        note = st.text_input("备注", value="", key=f"hitl_note_{run.get('run_id')}")
        hitl_q = "?view=public" if public_view_mode else ""
        x, y, z, w = st.columns(4)
        with x:
            if st.button("批准", type="primary", key=f"hitl_approve_{run.get('run_id')}"):
                try:
                    approved = api(
                        "POST",
                        f"/runs/{run['run_id']}/hitl{hitl_q}",
                        CHIEF_KEY,
                        json={"decision": "approve", "note": note, "confirmations": conf},
                    )
                    st.session_state["last_run"] = approved
                    sub = approved.get("work_order_submit") or {}
                    if sub.get("ticket_id"):
                        st.session_state["highlight_ticket"] = sub.get("ticket_id")
                    st.session_state["highlight_run_id"] = approved.get("run_id")
                    _refresh_submit_records(health)
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))
        with y:
            if st.button("拒绝", key=f"hitl_reject_{run.get('run_id')}"):
                st.session_state["last_run"] = api(
                    "POST",
                    f"/runs/{run['run_id']}/hitl{hitl_q}",
                    CHIEF_KEY,
                    json={"decision": "reject", "note": note},
                )
                st.rerun()
        with z:
            if st.button("退回", key=f"hitl_return_{run.get('run_id')}"):
                try:
                    st.session_state["last_run"] = api(
                        "POST",
                        f"/runs/{run['run_id']}/hitl{hitl_q}",
                        CHIEF_KEY,
                        json={"decision": "return", "note": note or "请补充后重开"},
                    )
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))
        with w:
            if is_chief and st.button("取消单据", key=f"hitl_cancel_{run.get('run_id')}"):
                try:
                    st.session_state["last_run"] = api(
                        "POST",
                        f"/runs/{run['run_id']}/cancel",
                        CHIEF_KEY,
                    )
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))
        st.markdown("</div>", unsafe_allow_html=True)
        return

    if run.get("work_order_state") == "ready_for_chief":
        st.markdown('<p class="section-label">对照结果</p>', unsafe_allow_html=True)
        st.info("库存充足，不进待办。本场景用来看有库存时的差异，不必落箱。")


def _render_return_hint(run: dict) -> None:
    if not (run.get("return_for_rework") or (run.get("hitl") or {}).get("decision") == "return"):
        return
    hint = str(run.get("reopen_hint") or run.get("return_note") or "请补充信息后重新提交报修")
    st.warning(f"已退回：{hint}")


def _scene_label(pb: dict, health: dict | None = None) -> str:
    pid = str(pb.get("id") or "")
    if pid in SCENE_LABELS:
        return SCENE_LABELS[pid]
    title = str(pb.get("title") or pid)
    return title.split("·")[-1].strip() if "·" in title else title


# ——— page ———

st.set_page_config(page_title=APP_TITLE, layout="wide")
st.markdown(PAGE_STYLE, unsafe_allow_html=True)

_MAIN_PLAYBOOK_IDS = ("p1_xingsha_h103", "p1b_no_shortage_ready", "p8_parts_clerk_conflict")

if "show_advanced" not in st.session_state:
    st.session_state["show_advanced"] = False

health: dict = {}
_live_required = False
_demo_warn = False
_runtime_mode = "dev"
public_view_mode = True

with st.sidebar:
    role_name = st.selectbox("我是谁", list(PERSONAS.keys()))
    api_key = PERSONAS[role_name]
    is_chief = role_name.startswith("站长")

    try:
        health = api("GET", "/health", api_key)
        _live_required = bool(health.get("live_linkage_required"))
        _demo_warn = bool(health.get("demo_mode_warning"))
        _runtime_mode = str(health.get("runtime_mode") or "dev")
    except Exception as exc:  # noqa: BLE001
        st.error(f"服务连不上：{exc}")
        # 哨兵：避免空 dict 被模式横幅误判为「联调模式」
        health = {"_ui_unreachable": True}

    try:
        playbooks = api("GET", "/playbooks?lane=core", api_key).get("items") or []
    except Exception:
        playbooks = []
    try:
        all_pbs = api("GET", "/playbooks?lane=extended", api_key).get("items") or []
    except Exception:
        all_pbs = list(playbooks)
    main_pbs = [p for p in playbooks if p.get("id") in _MAIN_PLAYBOOK_IDS] or [
        p for p in all_pbs if p.get("id") in _MAIN_PLAYBOOK_IDS
    ]
    other_pbs = [p for p in all_pbs if p.get("id") not in _MAIN_PLAYBOOK_IDS]
    main_labels = {_scene_label(p, health): str(p["id"]) for p in main_pbs}

    scene = st.selectbox("示例场景", ["自己填写"] + list(main_labels.keys()))
    if _is_standalone(health):
        st.caption("先试缺料报修，站长确认后看落箱")
        if scene == "有库存":
            st.caption("有库存为对照：不进待办，不必落箱")
    elif _is_live(health):
        st.caption("推荐缺料报修或制度冲突")
    if scene != "自己填写" and st.button("运行示例", type="primary"):
        view_q = "?view=public" if public_view_mode else ""
        st.session_state["last_run"] = api(
            "POST", f"/playbooks/{main_labels[scene]}/run{view_q}", api_key
        )
        st.rerun()

    st.session_state["show_advanced"] = st.checkbox(
        "显示更多选项",
        value=bool(st.session_state.get("show_advanced")),
    )
    lab = bool(st.session_state.get("show_advanced"))

    if lab:
        public_view_mode = st.checkbox("隐藏敏感明细", value=True)
        st.session_state["public_view_mode"] = public_view_mode
        st.session_state["auto_submit"] = st.checkbox(
            "批准后自动提交",
            value=bool(st.session_state.get("auto_submit", False)),
        )
        oral_q = st.selectbox("常用问法", ORAL_DEMO_QUESTIONS)
        if st.button("填到输入框"):
            st.session_state["question_input"] = oral_q
            st.session_state["question"] = oral_q
            st.rerun()
        other_labels = {_scene_label(p, health): str(p["id"]) for p in other_pbs}
        if other_labels:
            och = st.selectbox("其他场景", list(other_labels.keys()))
            if st.button("运行其他场景"):
                view_q = "?view=public" if public_view_mode else ""
                st.session_state["last_run"] = api(
                    "POST", f"/playbooks/{other_labels[och]}/run{view_q}", api_key
                )
                st.rerun()
        if st.button("跑离线对照实验"):
            st.session_state["eval_report"] = api(
                "POST", "/eval/compare?engine=langgraph&live_rag=false", api_key
            )
        with st.expander("服务状态"):
            st.json(
                {
                    "runtime_mode": health.get("runtime_mode"),
                    "rag_mode": health.get("rag_mode"),
                    "linkage_claim": health.get("linkage_claim"),
                    "rag_evidence_tier": health.get("rag_evidence_tier"),
                    "live_eval_artifacts_ok": health.get("live_eval_artifacts_ok"),
                    "live_eval_all_ok": health.get("live_eval_all_ok"),
                    "submit_destination": health.get("submit_destination"),
                    "version": health.get("version"),
                }
            )

st.markdown(
    f'<div class="page-header">'
    f'<h1 class="page-title">{html.escape(APP_TITLE)}</h1>'
    f'<p class="meta">当前角色：{html.escape(role_name)}</p>'
    f"</div>",
    unsafe_allow_html=True,
)

_render_mode_banner(health)

run = st.session_state.get("last_run")
_render_step_row(run if isinstance(run, dict) else None, health)
_render_status_banner(_status_view(run if isinstance(run, dict) else None, health))
if isinstance(run, dict):
    _render_linkage_line(run, health)
_render_degrade_hint(health, run if isinstance(run, dict) else None)

_block_demo = False
if _runtime_mode != "standalone":
    _block_demo = bool(_live_required and health.get("rag_mode") != "live") or bool(_demo_warn)
if _block_demo:
    st.error("外接知识库未就绪。请先启动知识库服务，或改用本机独立模式。")

st.markdown('<p class="section-label">报修内容</p>', unsafe_allow_html=True)
_default_q = "星沙站 SY215C 故障码 H103，动臂液压无力，请开单"
if "question_input" not in st.session_state:
    st.session_state["question_input"] = st.session_state.get("question", _default_q)
question = st.text_area(
    "报修内容",
    height=90,
    key="question_input",
    label_visibility="collapsed",
)
st.session_state["question"] = question
station_choice = st.selectbox("服务站", STATION_OPTIONS, index=1)
station_param = None if station_choice == "自动识别" else station_choice
second_visit = st.checkbox("二次进站", value=False)
auto_submit = bool(st.session_state.get("auto_submit", False))
kb = "demo-kb"
if lab:
    kb = st.text_input("知识库名称", value="demo-kb")

if st.button("提交报修", type="primary", disabled=_block_demo):
    try:
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
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.error(str(exc))

if is_chief:
    st.markdown('<p class="section-label">待我确认</p>', unsafe_allow_html=True)
    try:
        recent = api("GET", "/runs?limit=30", CHIEF_KEY)
        pending_runs = [
            it
            for it in (recent.get("items") or [])
            if isinstance(it, dict) and it.get("status") == "waiting_hitl"
        ]
        if not pending_runs:
            st.caption("暂时没有")
        else:
            pick = st.selectbox(
                "选择单据",
                [str(it.get("run_id")) for it in pending_runs[:15]],
            )
            if st.button("打开单据"):
                view_q = "?view=public" if public_view_mode else ""
                st.session_state["last_run"] = api("GET", f"/runs/{pick}{view_q}", CHIEF_KEY)
                st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.caption(f"待办加载失败: {exc}")

if lab and st.session_state.get("eval_report"):
    st.subheader("离线对照实验")
    _render_eval_summary(st.session_state["eval_report"])

run = st.session_state.get("last_run")
if not run:
    if st.session_state.get("inbox") or st.session_state.get("outbox"):
        _render_submit_records(health, None)
    st.stop()

if isinstance(run, dict) and run.get("work_order_submit"):
    if _uses_inbox(health) and not st.session_state.get("inbox"):
        _refresh_submit_records(health)
    elif not _uses_inbox(health) and not st.session_state.get("outbox"):
        _refresh_submit_records(health)

_render_intent_line(run)
_render_return_hint(run)

if lab and run.get("final_summary"):
    with st.expander("技术摘要"):
        st.code(str(run.get("final_summary") or ""), language=None)

st.markdown(_result_cards_html(_build_result_cards(run, health)), unsafe_allow_html=True)

_render_hitl_panel(run, public_view_mode=public_view_mode, is_chief=is_chief, health=health)

cert = run.get("decision_certificate")
if isinstance(cert, dict) and cert and run.get("work_order_submit"):
    _render_cert_line(cert)
    if lab and cert:
        with st.expander("决策记录详情"):
            st.json(cert)

rag = run.get("rag") or {}
rag_answer = str(rag.get("answer") or "").strip()
rag_sources = _fmt_rag_sources(rag)
if rag_answer or rag_sources:
    rag_title = "参考回答" if _is_standalone(health) else "知识依据"
    with st.expander(rag_title, expanded=bool(rag_answer and run.get("rag_degraded"))):
        if rag_answer:
            st.write(rag_answer)
        if rag_sources:
            st.markdown(rag_sources)

draft_body = _fmt_work_order_draft(run.get("work_order_draft") or {})
if run.get("work_order_draft"):
    with st.expander("开单草稿", expanded=False):
        st.markdown(draft_body)

if st.session_state.get("inbox") or st.session_state.get("outbox") or run.get("work_order_submit"):
    _render_submit_records(health, run)
    if lab:
        raw = st.session_state.get("inbox") or st.session_state.get("outbox")
        if raw:
            with st.expander("记录原文"):
                st.json(raw)

if lab:
    with st.expander("运行详情"):
        st.json(
            {
                "run_id": run.get("run_id"),
                "status": run.get("status"),
                "engine": run.get("engine"),
                "rag_client_mode": run.get("rag_client_mode"),
                "work_order_state": run.get("work_order_state"),
                "scope_note": run.get("scope_note"),
                "service_ticket": run.get("service_ticket"),
                "parts_check": run.get("parts_check"),
                "conflict_bundle": run.get("conflict_bundle"),
            }
        )
    events = run.get("trace_events") or []
    chart_data = _trace_latency_chart(events)
    if chart_data:
        st.bar_chart(chart_data)
    if events and st.button("导出运行轨迹"):
        st.download_button(
            "下载",
            data=json.dumps({"run_id": run.get("run_id"), "events": events}, ensure_ascii=False, indent=2),
            file_name=f"trace_{run.get('run_id')}.json",
            mime="application/json",
        )
    if events:
        with st.expander("运行轨迹明细"):
            _render_trace_events(events)
