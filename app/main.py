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
from app.branding import APP_TITLE_FULL, PRODUCT_ONE_LINER, SIBLING_REPO_SLUG
from app.config import get_settings, resolve_runtime_mode, strict_runtime_errors, submit_destination_name, validate_runtime_mode
from app.eval.compare import compare_cases
from app.graph.builder import clear_checkpoint_thread
from app.graph.runner import apply_hitl, create_initial_state, public_view, run_until_pause
from app.graph.state import merge_state
from app.logging_config import setup_logging
from app.playbooks.runner import run_playbook_from_data, validate_playbook_result
from app.playbooks.validate import load_playbook
from app.policy.gates import assert_known_api_key, is_station_chief, resolve_role, role_from_api_key
from app.policy.role_graph import ROLE_MATRIX, expected_path_for_role
from app.policy.rules_catalog import CONFLICT_POLICY, list_policies
from app.tools.rag_client import RagClient, RagToolError, summarize_rag_health
from app.tools.rag_factory import (
    build_rag_client,
    is_rag_reachable,
    knowledge_port_of,
    rag_client_mode,
    reset_rag_reachability_cache,
)
from app.tools.submit_destination import FileOutboxDestination
from app.tracing.store import (
    audit_persistence,
    init_db,
    list_recent_runs,
    load_run,
    repair_persistence,
    run_status_counts,
    save_run_snapshot,
    submit_gate_blocked_counts,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    settings = get_settings()
    Path(settings.traces_dir).mkdir(parents=True, exist_ok=True)
    reset_rag_reachability_cache()
    mode_warnings = validate_runtime_mode(settings)
    if mode_warnings:
        import logging

        for w in mode_warnings:
            logging.getLogger("copilot.startup").warning(w)
    strict_errors = strict_runtime_errors(settings)
    if strict_errors:
        import logging
        import sys

        from app.config import multi_worker_forbidden

        log = logging.getLogger("copilot.startup")
        # multi-worker 始终 fail-fast；其余模式错配仅在 STRICT_STARTUP=1 时退出
        fatal = settings.strict_startup or multi_worker_forbidden(settings)
        for err in strict_errors:
            if fatal:
                log.error("strict_startup: %s", err)
            else:
                log.warning("runtime_mode_mismatch: %s", err)
        if fatal:
            sys.exit(1)
    audit = audit_persistence()
    if not audit.get("healthy"):
        import logging

        logging.getLogger("copilot.startup").warning(
            "persistence unhealthy: orphan=%s terminal_cp=%s — running repair",
            audit.get("orphan_count"),
            audit.get("terminal_with_cp_count"),
        )
        repair_persistence(dry_run=False)
    yield


app = FastAPI(
    title=APP_TITLE_FULL,
    description=(
        f"{PRODUCT_ONE_LINER} "
        f"确定性规则编排（非 Multi-Agent / 非本地 LLM）· 可插拔知识源（Fixture 或 {SIBLING_REPO_SLUG}）· "
        "门禁/HITL/file_outbox 或 rag_mock_inbox（is_production_ticket=false，不含 ERP 派工）"
    ),
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
    if resolve_runtime_mode(settings) == "standalone":
        return False
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


def _read_live_eval_meta() -> dict[str, Any]:
    """Portfolio 验收证据：仅读 live_*.json，不引用 stale smoke_report。"""
    from app.eval.live_contract import (
        LIVE_FUNCTION_EXPECTED_TOTAL,
        LIVE_FUNCTION_SCRIPT_VERSION,
        LIVE_MANUAL_EXPECTED_TOTAL,
        LIVE_MANUAL_SCRIPT_VERSION,
    )

    eval_dir = Path(get_settings().playbooks_dir).parent / "eval"
    out: dict[str, Any] = {}
    live_files = {
        "live_integration_manual": (
            eval_dir / "live_integration_manual.json",
            LIVE_MANUAL_SCRIPT_VERSION,
            LIVE_MANUAL_EXPECTED_TOTAL,
        ),
        "live_function_test": (
            eval_dir / "live_function_test.json",
            LIVE_FUNCTION_SCRIPT_VERSION,
            LIVE_FUNCTION_EXPECTED_TOTAL,
        ),
    }
    summaries: list[str] = []
    all_ok = True
    stale: list[str] = []
    latest_mtime: float | None = None
    for key, (path, expect_ver, expect_total) in live_files.items():
        if not path.exists():
            all_ok = False
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            passed = int(data.get("passed") or 0)
            total = int(data.get("total") or 0)
            file_ok = bool(data.get("all_ok")) if "all_ok" in data else passed == total
            ver = str(data.get("script_version") or "")
            version_ok = ver == expect_ver
            total_ok = total == expect_total
            if not version_ok or not total_ok:
                stale.append(f"{key}:ver={ver or '?'}≠{expect_ver}|total={total}≠{expect_total}")
                file_ok = False
            all_ok = all_ok and file_ok and total > 0
            summaries.append(f"{key}:{passed}/{total}")
            out[f"{key}_passed"] = passed
            out[f"{key}_total"] = total
            out[f"{key}_all_ok"] = file_ok
            out[f"{key}_script_version"] = ver
            mtime = path.stat().st_mtime
            latest_mtime = mtime if latest_mtime is None else max(latest_mtime, mtime)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            all_ok = False
    if summaries:
        out["live_eval_summary"] = " · ".join(summaries)
        out["live_eval_all_ok"] = all_ok
        if stale:
            out["live_eval_stale"] = stale
        if latest_mtime is not None:
            out["live_eval_at"] = latest_mtime

    joint_path = eval_dir / "joint_evidence_pack.json"
    if joint_path.exists():
        try:
            joint = json.loads(joint_path.read_text(encoding="utf-8"))
            out["joint_evidence_live_verified"] = bool(joint.get("live_verified"))
            out["joint_evidence_claimable"] = bool(joint.get("portfolio_claimable"))
            out["joint_evidence_mode"] = joint.get("mode")
            out["parts_gate_ab_live_ok"] = bool(joint.get("parts_gate_ab_live_ok"))
            if joint.get("portfolio_warning"):
                out["joint_evidence_warning"] = joint.get("portfolio_warning")
        except (json.JSONDecodeError, OSError, TypeError):
            out["joint_evidence_live_verified"] = False
    return out


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
    orphan_n = int(persistence.get("orphan_count") or len(persistence.get("orphan_checkpoints") or []))
    terminal_cp_n = int(
        persistence.get("terminal_with_cp_count") or len(persistence.get("terminal_runs_with_checkpoint") or [])
    )
    terminal_thr = int(
        persistence.get("terminal_checkpoint_threshold")
        or getattr(settings, "terminal_checkpoint_threshold", 3)
        or 3
    )
    persistence_hint = None
    if not persistence.get("healthy"):
        if orphan_n or persistence.get("waiting_hitl_without_checkpoint"):
            persistence_hint = "运行 POST /persistence/repair 或 python scripts/reset_demo_state.py"
        elif terminal_cp_n >= terminal_thr:
            persistence_hint = (
                f"terminal_with_cp_count={terminal_cp_n}>={terminal_thr}，建议 POST /persistence/repair"
            )
        else:
            persistence_hint = "运行 POST /persistence/repair 或 python scripts/reset_demo_state.py"
    elif persistence.get("degraded"):
        persistence_hint = (
            f"terminal_with_cp_count={terminal_cp_n}（未达阈值 {terminal_thr}），建议择机 repair"
        )

    recent = list_recent_runs(limit=1)
    last_run_status = recent[0]["status"] if recent else None

    from app.tools.circuit_breaker import circuit_snapshot

    rag_circuit = circuit_snapshot(f"rag:{settings.rag_base_url.rstrip('/')}")

    from app.domain.parts_catalog import parts_ledger_fingerprint
    from app.tools.rag_contract import CONTRACT_VERSION, read_last_contract_check_summary

    ledger_fp = parts_ledger_fingerprint()
    contract_summary = read_last_contract_check_summary()

    live_meta = _read_live_eval_meta()
    # O4：仅当当前 live 且本轮探测成功才宣称当场 live_verified
    disk_verified = bool(live_meta.get("joint_evidence_live_verified"))
    runtime_live_ok = rag_mode == "live" and bool(rag_status.get("ok"))
    if disk_verified and not runtime_live_ok:
        live_meta["joint_evidence_stale_vs_runtime"] = True
        live_meta["joint_evidence_live_verified"] = False
    elif not runtime_live_ok:
        live_meta["joint_evidence_live_verified"] = False

    runtime_mode = resolve_runtime_mode(settings)
    submit_dest = submit_destination_name(settings)
    if settings.demo_offline:
        knowledge_port = "fixture"
    elif rag_mode == "live":
        knowledge_port = "http"
    elif settings.rag_auto_fallback:
        knowledge_port = "fixture"
    else:
        knowledge_port = "none"

    mode_warnings: list[str] = validate_runtime_mode(settings)
    if runtime_mode == "live" and knowledge_port == "fixture":
        mode_warnings.append("live_fixture_forbidden: Live 模式禁止 Fixture 冒充联调")

    standalone_ok = None
    standalone_path = Path(settings.playbooks_dir).parent / "eval" / "standalone_scorecard.json"
    if standalone_path.exists():
        try:
            sc = json.loads(standalone_path.read_text(encoding="utf-8"))
            standalone_ok = bool(sc.get("all_ok"))
        except (json.JSONDecodeError, OSError, TypeError):
            standalone_ok = False

    base_ok = bool(
        rag_status.get("ok")
        or settings.rag_auto_fallback
        or settings.demo_offline
        or runtime_mode == "standalone"
    )
    # 模式错配 → degraded（仍可探活，但不得宣称健康自立）
    status_ok = base_ok and not mode_warnings

    return {
        "status": "ok" if status_ok else "degraded",
        "version": __version__,
        "runtime_mode": runtime_mode,
        "knowledge_port": knowledge_port,
        "submit_destination": submit_dest,
        "standalone_scorecard_ok": standalone_ok,
        "mode_warnings": mode_warnings,
        "rag_base_url": settings.rag_base_url,
        "rag_mode": rag_mode,
        "rag_auto_fallback": settings.rag_auto_fallback,
        "demo_offline": settings.demo_offline,
        "demo_mode_warning": demo_mode_warning and runtime_mode != "standalone",
        "live_linkage_required": _live_required(settings),
        "block_runs_when_not_live": settings.block_runs_when_not_live or settings.require_live,
        "default_kb": settings.default_kb,
        "hitl_required_on_conflict": settings.hitl_required_on_conflict,
        "conflict_policy": CONFLICT_POLICY,
        "require_known_api_key": settings.require_known_api_key,
        "engine": "langgraph",
        "engine_strict": settings.engine_strict,
        "fallback_engine": "fallback",
        "persist_mode": settings.persist_mode,
        "persistence": persistence,
        "persistence_ok": bool(persistence.get("healthy")),
        "persistence_hint": persistence_hint,
        "single_worker_ok": int(getattr(settings, "uvicorn_workers", 1) or 1) <= 1,
        "uvicorn_workers": int(getattr(settings, "uvicorn_workers", 1) or 1),
        "last_run_status": last_run_status,
        "rag_circuit": rag_circuit,
        "parts_ledger_mtime": ledger_fp.get("parts_ledger_mtime"),
        "parts_ledger_sha256": ledger_fp.get("parts_ledger_sha256"),
        "parts_item_count": ledger_fp.get("parts_item_count"),
        "rag_contract_version": CONTRACT_VERSION,
        "live_rag_contract_check": contract_summary,
        **live_meta,
        "rag": rag_status,
        "hint": None
        if runtime_mode == "standalone"
        else (
            None
            if rag_mode == "live" and rag_status.get("ok")
            else (
                "RAG 不可达且 RAG_AUTO_FALLBACK=1：POST /runs 将使用 Fixture 知识源（live 联调请设 RAG_AUTO_FALLBACK=0；单仓请 copy .env.standalone .env）"
                if settings.rag_auto_fallback and not settings.demo_offline
                else "RAG degraded：建议关闭 auto_submit，关键开单须站长人确"
            )
        ),
        **(
            {
                "demo_checklist": [
                    "单仓: copy .env.standalone .env → preflight --standalone",
                    "联调: copy .env.demo .env → preflight --require-rag",
                    "演示前: python scripts/reset_demo_state.py",
                    "改台账 JSON: 无需重启（/health 核对 parts_ledger_sha256）",
                    "改代码后: 重启 Copilot :8002",
                ]
            }
            if settings.expose_demo_hints
            else {}
        ),
        "orchestration": {
            "supervisor": "deterministic_rule_router",
            "quality": "rule_based_critic",
            "llm_location": "enterprise-rag_only_when_http",
            "local_llm": False,
            "not_multi_agent": True,
            "knowledge_port": knowledge_port,
            "submit_destination": submit_dest,
            "is_production_ticket": False,
            "scope": "work_order_copilot_not_erp_dispatch",
            "naming_note": "repo/intent may say dispatch; product scope is work-order gatekeeping only",
            "parts_ledger": "demo_json_or_http_mock_not_production_wms",
            "sla_model": "keyword_trigger_plus_deadline_stamp_not_live_timer_service",
        },
        "demo_honesty": {
            "station_profile": "structured_demo_ops_fields_not_dealer_crm",
            "parts_ledger": "scripted_stock_for_POL_gates; change stock to reverse-prove POL-PARTS-01",
            "fixture_knowledge": "knowledge_port=fixture is first-class for standalone; not silent live fake",
            "joint_evidence_pack": "optional_bonus; only_claim_live_when_live_verified=true",
        },
    }


@app.get("/persistence/audit")
def persistence_audit(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    if get_settings().require_known_api_key:
        _resolve_key(None, x_api_key)
    return audit_persistence()


@app.post("/admin/reload-ledger")
def admin_reload_ledger(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """开发态：清台账/主数据缓存并回指纹（须已知 demo Key）。"""
    _require_known_key(x_api_key)
    from app.domain.parts_catalog import parts_ledger_fingerprint
    from app.domain.parts_master import reset_parts_master_cache

    reset_parts_master_cache()
    fp = parts_ledger_fingerprint()
    return {"ok": True, "reloaded": True, **fp}

@app.get("/metrics", response_class=PlainTextResponse)
def metrics_prometheus(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> PlainTextResponse:
    """Prometheus 文本格式计数器（演示级；EXPOSE_METRICS=0 时不可用）。"""
    if not get_settings().expose_metrics:
        raise HTTPException(404, "metrics disabled (EXPOSE_METRICS=0)")
    if get_settings().require_known_api_key:
        if not (x_api_key or "").strip():
            raise HTTPException(401, "须 X-API-Key（已知演示 Key）")
        try:
            assert_known_api_key(x_api_key)
        except ValueError as exc:
            raise HTTPException(401, str(exc)) from exc
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
    gate_blocked = submit_gate_blocked_counts()
    if gate_blocked:
        lines.extend(
            [
                "# HELP copilot_submit_gate_blocked_total Submit gate blocked runs by error_code",
                "# TYPE copilot_submit_gate_blocked_total counter",
            ]
        )
        for code, n in sorted(gate_blocked.items()):
            lines.append(f'copilot_submit_gate_blocked_total{{error_code="{code}"}} {n}')
    live_eval = _read_live_eval_meta()
    if live_eval.get("live_eval_at"):
        lines.extend(
            [
                "# HELP copilot_live_eval_at Unix timestamp of latest live_*.json eval artifact",
                "# TYPE copilot_live_eval_at gauge",
                f"copilot_live_eval_at {int(live_eval['live_eval_at'])}",
                "# HELP copilot_live_eval_all_ok Whether all committed live eval JSONs report all_ok",
                "# TYPE copilot_live_eval_all_ok gauge",
                f"copilot_live_eval_all_ok {1 if live_eval.get('live_eval_all_ok') else 0}",
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
    # API parts_hints 默认丢弃，避免演示注入冒充 RAG draft；须 ALLOW_DEMO_PARTS_HINTS=1
    force_hints = list(body.parts_hints or []) if settings.allow_demo_parts_hints else []
    question = body.question
    parent_id = (body.parent_run_id or "").strip() or None
    if parent_id:
        parent = load_run(parent_id)
        if not parent:
            raise HTTPException(404, f"parent_run_id 不存在: {parent_id}")
        if not (
            parent.get("return_for_rework")
            or (parent.get("hitl") or {}).get("decision") in {"return", "edit"}
        ):
            raise HTTPException(400, "parent_run_id 须为已 return 退回补件的 run")
        ret_note = str((parent.get("hitl") or {}).get("note") or "").strip()
        parent_q = str(parent.get("raw_input") or "").strip()
        prefix = f"[基于退回 run={parent_id}"
        if ret_note:
            prefix += f" note={ret_note}"
        prefix += "] "
        # 若调用方未改写问题，默认沿用原问题并附退回说明
        if question.strip() == parent_q or not question.strip():
            question = prefix + parent_q
        elif not question.startswith("["):
            question = prefix + question
    try:
        client = build_rag_client(key, parts=force_hints or None)
    except RagToolError as exc:
        raise HTTPException(exc.status_code or 503, str(exc)) from exc
    _guard_live_client(settings, client)
    state = create_initial_state(
        question,
        api_key=key,
        role=role,
        knowledge_base=body.knowledge_base,
        history=body.history,
        auto_submit=body.auto_submit,
        max_iterations=body.max_iterations,
        parts_force_hints=force_hints,
        station=body.station,
        second_visit=body.second_visit,
        sla_class=body.sla_class,
        engine="langgraph",
        parent_run_id=parent_id,
    )
    if rag_client_mode(client) == "demo_offline":
        state = merge_state(state, rag_offline_mode=True)
    state = run_until_pause(state, client=client, persist=True)  # type: ignore[arg-type]
    view_out = public_view(state, view=view)
    view_out["knowledge_port"] = knowledge_port_of(client)
    view_out["runtime_mode"] = resolve_runtime_mode(settings)
    view_out["submit_destination"] = submit_destination_name(settings)
    return view_out


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
    decision = body.normalized_decision()
    if decision == "return" and not (body.note or "").strip():
        raise HTTPException(400, "退回补件(return)必须填写 note 说明（不改草稿字段，须重新开单）")
    if decision == "approve":
        from app.policy.hitl_layers import compute_pending_layers, missing_layer_confirmations

        pending = list((state.get("hitl") or {}).get("pending_layers") or []) or compute_pending_layers(
            state
        )
        missing = missing_layer_confirmations(pending, body.confirmations)
        if missing:
            raise HTTPException(
                400,
                f"分层人确未勾选完整: missing={missing}; pending_layers={pending}。"
                "单一 approve 不能一键放行冲突/缺料/SLA 等业务门禁。",
            )
    client = build_rag_client(str(state.get("api_key") or key))
    state = apply_hitl(
        state,
        decision,
        body.note,
        client=client,
        persist=True,
        approver_api_key=key,
        confirmations=body.confirmations,
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


# 主路径剧本（E6）：默认 /playbooks?lane=core 只列这些
CORE_PLAYBOOK_IDS = ("p1_xingsha_h103", "p1b_no_shortage_ready", "p8_parts_clerk_conflict")


def _playbooks_dir() -> Path:
    return Path(get_settings().playbooks_dir)


@app.get("/playbooks")
def list_playbooks(
    lane: str = Query(default="core", description="core=主路径；extended=全部；all=同 extended"),
) -> dict[str, Any]:
    items = []
    root = _playbooks_dir()
    lane_norm = (lane or "core").strip().lower()
    if root.exists():
        for path in sorted(root.glob("*.json")):
            if lane_norm == "core" and path.stem not in CORE_PLAYBOOK_IDS:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            items.append(
                {
                    "id": path.stem,
                    "title": data.get("title") or path.stem,
                    "question": data.get("question"),
                    "api_key": data.get("api_key"),
                    "expect_status": data.get("expect_status"),
                    "station": data.get("station"),
                    "lane": "core" if path.stem in CORE_PLAYBOOK_IDS else "extended",
                }
            )
    return {"items": items, "lane": "extended" if lane_norm in {"extended", "all"} else "core"}


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
    from app.policy.rules_catalog import CORE_POLICIES, POLICY_CATALOG_VERSION

    return {
        "items": list_policies(),
        "conflict_policy": CONFLICT_POLICY,
        "policy_catalog_version": POLICY_CATALOG_VERSION,
        "core_policies": list(CORE_POLICIES),
        # 兼容旧客户端字段名
        "interview_core_policies": list(CORE_POLICIES),
    }


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


@app.get("/outbox")
def list_outbox(
    limit: int = 10,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """本仓 file_outbox 回读（Standalone 主落箱；非 ERP）。"""
    _resolve_key(None, x_api_key)
    dest = FileOutboxDestination()
    items = dest.list_tickets(limit=limit)
    return {
        "destination": "file_outbox",
        "is_production_ticket": False,
        "count": len(items),
        "items": items,
    }


@app.get("/outbox/{run_id}")
def get_outbox_ticket(
    run_id: str,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _resolve_key(None, x_api_key)
    ticket = FileOutboxDestination().get_ticket(run_id)
    if not ticket:
        raise HTTPException(404, f"outbox ticket not found: {run_id}")
    return ticket


@app.get("/inbox")
def inbox_proxy(
    limit: int = 10,
    lane: str = "all",
    source: str | None = None,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """回读 RAG mock 收件箱（Joint 加分路径；Standalone 请用 /outbox）。"""
    key = _resolve_key(None, x_api_key)
    client = build_rag_client(key)
    try:
        return client.list_inbox(limit=limit, lane=lane, source=source)
    except RagToolError as exc:
        raise HTTPException(exc.status_code or 503, str(exc)) from exc
