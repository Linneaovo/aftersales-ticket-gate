from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app import __version__
from app.api.schemas import HitlDecisionRequest, RunCreateRequest
from app.config import get_settings
from app.eval.compare import compare_cases
from app.graph.builder import clear_checkpoint_thread
from app.graph.runner import apply_hitl, create_initial_state, public_view, run_until_pause
from app.graph.state import merge_state
from app.logging_config import setup_logging
from app.playbooks.runner import run_playbook_from_data, validate_playbook_result
from app.playbooks.validate import load_playbook
from app.policy.gates import assert_known_api_key, is_station_chief, resolve_role, role_from_api_key
from app.policy.role_graph import ROLE_MATRIX, expected_path_for_role
from app.policy.rules_catalog import list_policies
from app.tools.rag_client import RagClient, RagToolError, summarize_rag_health
from app.tools.rag_factory import (
    build_rag_client,
    is_rag_reachable,
    rag_client_mode,
    reset_rag_reachability_cache,
)
from app.tracing.store import audit_persistence, init_db, list_recent_runs, load_run, repair_persistence, run_status_counts, save_run_snapshot


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    settings = get_settings()
    Path(settings.traces_dir).mkdir(parents=True, exist_ok=True)
    reset_rag_reachability_cache()
    yield


app = FastAPI(
    title="长株潭工程机械售后开单协同 Copilot",
    description="LangGraph 门禁编排 · 知识层 enterprise-rag · 行动层工单编排/质检/人确/mock 收件箱（不含 ERP 派工调度）",
    version=__version__,
    lifespan=lifespan,
)


def _cors_origins() -> list[str]:
    raw = (get_settings().cors_origins or "*").strip()
    if raw == "*":
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve_key(body_key: str | None, header_key: str | None) -> str:
    settings = get_settings()
    raw = (body_key or header_key or settings.api_key).strip()
    try:
        return assert_known_api_key(raw)
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc


def _resolve_role(
    body_key: str | None,
    header_key: str | None,
    role_claim: str | None,
) -> tuple[str, str]:
    key = _resolve_key(body_key, header_key)
    try:
        role = resolve_role(key, role_claim)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return key, role


def _require_chief_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str:
    key = _resolve_key(None, x_api_key)
    if not is_station_chief(api_key=key):
        role = role_from_api_key(key)
        raise HTTPException(403, f"须站长角色 API Key（当前 role={role}）")
    return key


def _require_known_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str:
    return _resolve_key(None, x_api_key)


def _live_required(settings: Any) -> bool:
    return bool(
        settings.block_runs_when_not_live
        or settings.require_live
        or (not settings.rag_auto_fallback and not settings.demo_offline)
    )


def _guard_live_linkage(settings: Any) -> None:
    """live 模式下 RAG 不可达或 DemoRag 客户端时拒绝写 run。"""
    live_req = _live_required(settings)
    if not live_req:
        return
    if not is_rag_reachable(force_check=True):
        raise HTTPException(
            503,
            "RAG 不可达（live 模式）。请先启动 enterprise-rag :8001 或检查 RAG_BASE_URL",
        )


def _guard_live_client(settings: Any, client: Any) -> None:
    _guard_live_linkage(settings)
    if _live_required(settings) and rag_client_mode(client) == "demo_offline":
        raise HTTPException(
            503,
            "当前为 DemoRag 离线客户端，live 模式禁止静默兜底。请启动 :8001 并设 RAG_AUTO_FALLBACK=0",
        )


def _read_smoke_meta() -> dict[str, Any]:
    path = Path(get_settings().playbooks_dir).parent / "eval" / "smoke_report.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "smoke_passed_at": path.stat().st_mtime,
            "smoke_passed": bool(data.get("passed")),
            "smoke_mode": data.get("mode"),
        }
    except (json.JSONDecodeError, OSError):
        return {}


@app.get("/health")
def health() -> dict[str, Any]:
    settings = get_settings()
    rag_status: dict[str, Any] = {"ok": False, "detail": "unreachable", "degraded": True}
    rag_mode = "demo_offline" if settings.demo_offline else "unknown"
    demo_mode_warning = False
    try:
        if settings.demo_offline:
            rag_status = {
                "ok": True,
                "degraded": True,
                "mode": "demo_offline",
                "detail": "DEMO_OFFLINE=1，使用本地 DemoRag",
            }
            rag_mode = "demo_offline"
            demo_mode_warning = True
        else:
            reachable = is_rag_reachable(force_check=True)
            if not reachable:
                raise RagToolError("enterprise-rag 不可达", 503)
            payload = RagClient().health()
            summary = summarize_rag_health(payload if isinstance(payload, dict) else {})
            rag_status = {
                "ok": not summary.get("degraded"),
                "degraded": summary.get("degraded"),
                "mode": "live",
                "summary": summary,
                "payload": payload,
            }
            rag_mode = "live"
    except RagToolError as exc:
        rag_status = {
            "ok": False,
            "degraded": True,
            "mode": "unreachable",
            "detail": str(exc),
            "status_code": exc.status_code,
            "auto_fallback": settings.rag_auto_fallback,
        }
        rag_mode = "demo_offline" if settings.rag_auto_fallback else "unreachable"
        demo_mode_warning = bool(settings.rag_auto_fallback)
    except Exception as exc:  # noqa: BLE001
        rag_status = {"ok": False, "degraded": True, "mode": "unreachable", "detail": str(exc)}
        rag_mode = "demo_offline" if settings.rag_auto_fallback else "unreachable"
        demo_mode_warning = bool(settings.rag_auto_fallback)

    if settings.rag_auto_fallback and rag_mode != "live":
        demo_mode_warning = True

    persistence = audit_persistence()
    orphan_n = len(persistence.get("orphan_checkpoints") or [])
    persistence_hint = None
    if not persistence.get("healthy"):
        persistence_hint = "运行 POST /persistence/repair 或 python scripts/reset_demo_state.py"
    elif orphan_n >= int(settings.orphan_checkpoint_threshold or 5):
        persistence_hint = f"orphan_checkpoints={orphan_n}，建议演示前 reset_demo_state"

    recent = list_recent_runs(limit=1)
    last_run_status = recent[0]["status"] if recent else None

    return {
        "status": "ok" if (rag_status.get("ok") or settings.rag_auto_fallback or settings.demo_offline) else "degraded",
        "version": __version__,
        "rag_base_url": settings.rag_base_url,
        "rag_mode": rag_mode,
        "rag_auto_fallback": settings.rag_auto_fallback,
        "demo_offline": settings.demo_offline,
        "demo_mode_warning": demo_mode_warning,
        "live_linkage_required": _live_required(settings),
        "block_runs_when_not_live": settings.block_runs_when_not_live or settings.require_live,
        "default_kb": settings.default_kb,
        "hitl_required_on_conflict": settings.hitl_required_on_conflict,
        "conflict_policy": settings.conflict_policy,
        "engine": "langgraph",
        "engine_strict": settings.engine_strict,
        "fallback_engine": "fallback",
        "persist_mode": settings.persist_mode,
        "persistence": persistence,
        "persistence_ok": bool(persistence.get("healthy")),
        "persistence_hint": persistence_hint,
        "last_run_status": last_run_status,
        **_read_smoke_meta(),
        "rag": rag_status,
        "hint": None
        if rag_mode == "live" and rag_status.get("ok")
        else (
            "RAG 不可达且 RAG_AUTO_FALLBACK=1：POST /runs 将使用 DemoRag 离线兜底（答辩请设 RAG_AUTO_FALLBACK=0）"
            if settings.rag_auto_fallback and not settings.demo_offline
            else "RAG degraded：建议关闭 auto_submit，关键开单须站长人确"
        ),
        **(
            {
                "demo_checklist": [
                    "答辩前: copy .env.demo .env",
                    "开场: curl http://127.0.0.1:8002/health 确认 rag_mode=live",
                    "演示前: python scripts/reset_demo_state.py && curl /persistence/audit",
                ]
            }
            if settings.expose_demo_hints
            else {}
        ),
        "orchestration": {
            "supervisor": "deterministic_rule_router",
            "quality": "rule_based_critic",
            "llm_location": "enterprise-rag_only",
        },
    }


@app.get("/persistence/audit")
def persistence_audit(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    if get_settings().require_known_api_key:
        _resolve_key(None, x_api_key)
    return audit_persistence()


@app.get("/metrics", response_class=PlainTextResponse)
def metrics_prometheus() -> PlainTextResponse:
    """Prometheus 文本格式计数器（演示级；EXPOSE_METRICS=0 时不可用）。"""
    if not get_settings().expose_metrics:
        raise HTTPException(404, "metrics disabled (EXPOSE_METRICS=0)")
    counts = run_status_counts()
    total = sum(counts.values())
    hitl_wait = counts.get("waiting_hitl", 0)
    lines = [
        "# HELP copilot_run_total Total runs by terminal status",
        "# TYPE copilot_run_total counter",
    ]
    for status, n in sorted(counts.items()):
        lines.append(f'copilot_run_total{{status="{status}"}} {n}')
    lines.extend(
        [
            "# HELP copilot_hitl_wait_total Runs currently waiting for chief HITL",
            "# TYPE copilot_hitl_wait_total gauge",
            f"copilot_hitl_wait_total {hitl_wait}",
            "# HELP copilot_run_all_total All persisted runs",
            "# TYPE copilot_run_all_total gauge",
            f"copilot_run_all_total {total}",
        ]
    )
    smoke = _read_smoke_meta()
    if smoke.get("smoke_passed_at"):
        lines.extend(
            [
                "# HELP copilot_smoke_passed_at Unix timestamp of last smoke_report.json",
                "# TYPE copilot_smoke_passed_at gauge",
                f"copilot_smoke_passed_at {int(smoke['smoke_passed_at'])}",
            ]
        )
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.post("/persistence/repair")
def persistence_repair(
    dry_run: bool = Query(default=False),
    x_api_key: str = Header(alias="X-API-Key"),
) -> dict[str, Any]:
    _require_chief_key(x_api_key)
    return repair_persistence(dry_run=dry_run)


@app.post("/runs")
def create_run(
    body: RunCreateRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_role_claim: str | None = Header(default=None, alias="X-Role-Claim"),
    view: str = Query(default="default", description="default | public（严格脱敏）"),
) -> dict[str, Any]:
    key, role = _resolve_role(body.api_key, x_api_key, x_role_claim)
    settings = get_settings()
    _guard_live_linkage(settings)
    try:
        client = build_rag_client(key, parts=list(body.parts_hints or []))
    except RagToolError as exc:
        raise HTTPException(exc.status_code or 503, str(exc)) from exc
    _guard_live_client(settings, client)
    state = create_initial_state(
        body.question,
        api_key=key,
        role=role,
        knowledge_base=body.knowledge_base,
        history=body.history,
        auto_submit=body.auto_submit,
        max_iterations=body.max_iterations,
        parts_force_hints=list(body.parts_hints or []),
        station=body.station,
        second_visit=body.second_visit,
        sla_class=body.sla_class,
        engine="langgraph",
    )
    if rag_client_mode(client) == "demo_offline":
        state = merge_state(state, rag_offline_mode=True)
    state = run_until_pause(state, client=client, persist=True)  # type: ignore[arg-type]
    return public_view(state, view=view)


@app.get("/runs")
def runs_list(
    limit: int = 20,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _resolve_key(None, x_api_key)
    return {"items": list_recent_runs(limit=limit)}


@app.get("/runs/{run_id}")
def get_run(
    run_id: str,
    view: str = Query(default="default"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _resolve_key(None, x_api_key)
    state = load_run(run_id)
    if not state:
        raise HTTPException(404, "run 不存在")
    return public_view(state, view=view)


@app.get("/runs/{run_id}/trace")
def get_trace(
    run_id: str,
    view: str = Query(default="default", description="default | public（脱敏 trace）"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _resolve_key(None, x_api_key)
    state = load_run(run_id)
    if not state:
        raise HTTPException(404, "run 不存在")
    events = state.get("trace_events") or []
    if view == "public":
        events = []
    return {
        "run_id": run_id,
        "status": state.get("status"),
        "engine": state.get("engine"),
        "execution_path": state.get("execution_path"),
        "engine_degraded": state.get("engine_degraded"),
        "work_order_state": state.get("work_order_state"),
        "events": events,
        "view_mode": view,
    }


@app.post("/runs/{run_id}/hitl")
def decide_hitl(
    run_id: str,
    body: HitlDecisionRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    view: str = Query(default="default"),
) -> dict[str, Any]:
    state = load_run(run_id)
    if not state:
        raise HTTPException(404, "run 不存在")
    if state.get("status") != "waiting_hitl":
        raise HTTPException(409, f"当前状态不可人确: {state.get('status')}")
    key = _resolve_key(None, x_api_key) or str(state.get("api_key") or "")
    if not is_station_chief(api_key=key):
        role = role_from_api_key(key)
        raise HTTPException(
            403,
            f"人确须站长角色权限（当前角色={role}）。演示环境请使用站长 API Key，生产接 SSO 角色映射。",
        )
    if body.decision == "edit" and not (body.note or "").strip():
        raise HTTPException(400, "改单(edit)必须填写 note 说明")
    client = build_rag_client(str(state.get("api_key") or key))
    state = apply_hitl(
        state,
        body.decision,
        body.note,
        client=client,
        persist=True,
        approver_api_key=key,
    )
    return public_view(state, view=view)


@app.post("/runs/{run_id}/cancel")
def cancel_run(
    run_id: str,
    x_api_key: str = Header(alias="X-API-Key"),
) -> dict[str, Any]:
    _require_chief_key(x_api_key)
    state = load_run(run_id)
    if not state:
        raise HTTPException(404, "run 不存在")
    state = merge_state(
        state,
        status="cancelled",
        final_summary="已取消",
        next_action="end",
    )
    save_run_snapshot(state)  # type: ignore[arg-type]
    clear_checkpoint_thread(run_id)
    return public_view(state)  # type: ignore[arg-type]


def _playbooks_dir() -> Path:
    return Path(get_settings().playbooks_dir)


@app.get("/playbooks")
def list_playbooks() -> dict[str, Any]:
    items = []
    root = _playbooks_dir()
    if root.exists():
        for path in sorted(root.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            items.append(
                {
                    "id": path.stem,
                    "title": data.get("title") or path.stem,
                    "question": data.get("question"),
                    "api_key": data.get("api_key"),
                    "expect_status": data.get("expect_status"),
                    "station": data.get("station"),
                }
            )
    return {"items": items}


@app.post("/playbooks/{playbook_id}/run")
def run_playbook(
    playbook_id: str,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    view: str = Query(default="default"),
) -> dict[str, Any]:
    try:
        data = load_playbook(playbook_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "剧本不存在") from exc
    key = _resolve_key(data.get("api_key"), x_api_key)
    settings = get_settings()
    _guard_live_linkage(settings)
    hints = data.get("parts_hints") or data.get("parts_hint") or []
    if isinstance(hints, str):
        hints = [hints]
    try:
        client = build_rag_client(key, parts=list(hints))
    except RagToolError as exc:
        raise HTTPException(exc.status_code or 503, str(exc)) from exc
    _guard_live_client(settings, client)
    state = run_playbook_from_data(data, client=client, engine="langgraph", persist=True)
    out = public_view(state, view=view)
    out["playbook_id"] = playbook_id
    validation = validate_playbook_result(data, state)
    out["playbook_meta"] = {
        "title": data.get("title"),
        "business_background": data.get("business_background"),
        "expect_status": data.get("expect_status"),
        "expect_intent": data.get("expect_intent"),
        "expect_trace_prefix": data.get("expect_trace_prefix"),
        "expect_hitl_reasons": data.get("expect_hitl_reasons"),
        "validation_passed": validation.get("passed"),
        "validation_diffs": validation.get("diffs"),
    }
    return out


@app.post("/playbooks/{playbook_id}/validate")
def validate_playbook(
    playbook_id: str,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    engine: str = Query(default="langgraph"),
) -> dict[str, Any]:
    """跑剧本并返回 expect vs actual diff（规格回归，非生产验收）。"""
    try:
        data = load_playbook(playbook_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "剧本不存在") from exc
    key = _resolve_key(data.get("api_key"), x_api_key)
    settings = get_settings()
    _guard_live_linkage(settings)
    hints = data.get("parts_hints") or data.get("parts_hint") or []
    if isinstance(hints, str):
        hints = [hints]
    try:
        client = build_rag_client(key, parts=list(hints))
    except RagToolError as exc:
        raise HTTPException(exc.status_code or 503, str(exc)) from exc
    _guard_live_client(settings, client)
    state = run_playbook_from_data(data, client=client, engine=engine, persist=False)
    report = validate_playbook_result(data, state)
    report["playbook_id"] = playbook_id
    report["run_summary"] = {
        "run_id": state.get("run_id"),
        "status": state.get("status"),
        "intent": state.get("intent"),
        "engine": state.get("engine"),
        "engine_degraded": state.get("engine_degraded"),
        "rag_offline_mode": state.get("rag_offline_mode"),
    }
    return report


@app.get("/policies")
def policies_list() -> dict[str, Any]:
    return {"items": list_policies(), "conflict_policy": get_settings().conflict_policy}


@app.get("/roles/matrix")
def roles_matrix() -> dict[str, Any]:
    return {"items": ROLE_MATRIX}


@app.get("/roles/path")
def role_path(role: str = "technician", intent: str = "fault_dispatch") -> dict[str, Any]:
    return expected_path_for_role(role, intent)


@app.get("/eval/summary")
def eval_summary(
    live_rag: bool = Query(default=False),
    engine: str = Query(default="langgraph"),
    baseline_http_only: bool = Query(default=True, description="baseline 跳过 Copilot classify，纯 HTTP 直通"),
) -> dict[str, Any]:
    cases_path = Path(get_settings().playbooks_dir).parent / "eval" / "cases.jsonl"
    n = 0
    if cases_path.exists():
        n = sum(1 for line in cases_path.read_text(encoding="utf-8").splitlines() if line.strip())
    report = compare_cases(live_rag=live_rag, engine=engine, baseline_http_only=baseline_http_only)
    return {
        "cases_file": str(cases_path),
        "case_count": n,
        "baseline_compare": report.get("summary"),
        "live_rag": live_rag,
        "engine": engine,
        "compare_report_path": "data/eval/compare_report.json",
    }


@app.post("/eval/compare")
def eval_compare(
    live_rag: bool = Query(default=False),
    engine: str = Query(default="langgraph"),
    baseline_http_only: bool = Query(default=True, description="baseline 跳过 Copilot classify，纯 HTTP 直通"),
    x_api_key: str = Header(alias="X-API-Key"),
) -> dict[str, Any]:
    _require_known_key(x_api_key)
    return compare_cases(live_rag=live_rag, engine=engine, baseline_http_only=baseline_http_only)


@app.get("/inbox")
def inbox_proxy(
    limit: int = 10,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """回读 RAG mock 收件箱，证明开单协同落到知识层侧（非 ERP 派工调度）。"""
    key = _resolve_key(None, x_api_key)
    client = build_rag_client(key)
    try:
        return client.list_inbox(limit=limit)
    except RagToolError as exc:
        raise HTTPException(exc.status_code or 503, str(exc)) from exc
