from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    rag_base_url: str = "http://127.0.0.1:8001"
    default_kb: str = "demo-kb"
    api_key: str = "demo-key"
    agent_host: str = "127.0.0.1"
    agent_port: int = 8002
    max_iterations: int = 8
    auto_submit: bool = False
    hitl_required_on_conflict: bool = True
    ask_timeout_s: float = 120.0
    retrieve_timeout_s: float = 60.0
    draft_timeout_s: float = 60.0
    parts_ledger_path: str = str(PROJECT_ROOT / "data" / "parts_ledger.json")
    parts_ledger_url: str = ""  # 非空时走 HttpPartsLedger（WMS/ERP HTTP）
    station_profile_path: str = str(PROJECT_ROOT / "data" / "station_profile.json")
    traces_dir: str = str(PROJECT_ROOT / "data" / "traces")
    runs_db_path: str = str(PROJECT_ROOT / "data" / "runs.db")
    checkpoint_db_path: str = str(PROJECT_ROOT / "data" / "checkpoints.db")
    playbooks_dir: str = str(PROJECT_ROOT / "data" / "playbooks")
    # conflict_policy 已写死 no_arbitration（见 app.policy.rules_catalog.CONFLICT_POLICY），不再提供可切换死配置
    persist_mode: str = "slim"  # slim | full
    demo_offline: bool = False  # 强制离线 DemoRag，不连 :8001
    rag_auto_fallback: bool = False  # :8001 不可达时自动切 DemoRag（默认禁止静默离线）
    require_known_api_key: bool = True  # 默认拒绝 KEY_ROLE_MAP 外 Key
    rag_reachability_ttl_s: float = 30.0  # RAG 可达性缓存 TTL（秒）；/health 强制刷新
    cors_origins: str = "http://127.0.0.1:8502,http://localhost:8502"  # 逗号分隔；* 表示全开放
    block_runs_when_not_live: bool = False  # True 时 POST /runs 在 RAG 不可达或 demo_offline 客户端返回 503
    require_live: bool = False  # 同 block_runs_when_not_live 的语义别名（REQUIRE_LIVE=1）
    role_claim_header: str = "X-Role-Claim"  # 生产 IdP 角色声明；API 层 resolve_role 已接入
    trust_role_claim: bool = False  # True 时信任 X-Role-Claim（须 IdP 网关校验）；演示默认须与 Key 绑定
    demo_keys_path: str = str(PROJECT_ROOT / "data" / "demo_keys.json")
    orphan_checkpoint_threshold: int = 5  # 超过则 /health 提示 repair
    terminal_checkpoint_threshold: int = 3  # 终态残留 CP≥阈值 → healthy=false；1..阈值-1 → degraded；0=不计入 healthy
    hitl_wait_ttl_hours: float = 72.0  # waiting_hitl 超过 N 小时自动 failed（0=禁用）
    uvicorn_workers: int = 1  # SQLite checkpoint 须单 worker；>1 时 /health degraded
    intent_confidence_threshold: float = 0.5  # POL-INTENT-01 低置信阈值（与 gates 同源）
    engine_strict: bool = True  # 默认 True：LangGraph 异常不静默降级 fallback（容灾须显式 ENGINE_STRICT=0）
    expose_metrics: bool = True  # False 时隐藏 /metrics
    expose_demo_hints: bool = False  # True 时 /health 返回 demo_checklist
    trace_retention_max_files: int = 200  # trace 目录保留最近 N 个 jsonl；0=不裁剪
    enable_weather_pol: bool = False  # 默认关：雨季关键词门禁；须与 gates/hitl_layers/_evaluate_hitl_gates 一致
    allow_demo_parts_hints: bool = False  # True 才接受 API parts_hints 注入；playbook 直调不受影响
    allow_answer_token_hints: bool = False  # True 才从 RAG answer 扫配件词表（默认关，防误触）
    # E4 L3 / O2：与 RAG COPILOT_SUBMIT_TOKEN 同值；非空则业务 submit 带 X-Copilot-Submit-Token
    # A档：RAG demo_env 开 SUBMIT_REQUIRE_COPILOT_TOKEN=1；B档单仓可关
    copilot_submit_token: str = ""
    # O3：ask 契约失败 → degrade；draft/submit 契约失败 → 抛错（strict）
    contract_validate: str = "strict"  # strict | warn | off
    # 提交终点：file_outbox（Standalone 默认）| rag_mock_inbox（Joint / .env.demo）
    submit_destination: str = "file_outbox"
    # standalone | live | ci | ""（空则按 DEMO_OFFLINE / REQUIRE_LIVE 推导）
    copilot_runtime_mode: str = ""
    strict_startup: bool = False  # True 时 standalone/live 模式错配直接拒绝启动


@lru_cache
def get_settings() -> Settings:
    return Settings()


def resolve_runtime_mode(settings: Settings | None = None) -> str:
    """对外 runtime_mode：standalone | live | ci | dev。"""
    s = settings or get_settings()
    explicit = (getattr(s, "copilot_runtime_mode", None) or "").strip().lower()
    if explicit in {"standalone", "live", "ci"}:
        return explicit
    if s.demo_offline and not s.require_live and not s.block_runs_when_not_live:
        return "standalone"
    if s.require_live or s.block_runs_when_not_live:
        return "live"
    return "dev"


def submit_destination_name(settings: Settings | None = None) -> str:
    s = settings or get_settings()
    mode = (getattr(s, "submit_destination", None) or "file_outbox").strip().lower()
    if mode in {"file", "file_outbox"}:
        return "file_outbox"
    return "rag_mock_inbox"


def validate_runtime_mode(settings: Settings | None = None) -> list[str]:
    """启动/health 同源：模式错配 → warning 列表（standalone 须 demo_offline + file_outbox）。"""
    s = settings or get_settings()
    mode = resolve_runtime_mode(s)
    submit_dest = submit_destination_name(s)
    warnings: list[str] = []
    if mode == "standalone" and submit_dest != "file_outbox":
        warnings.append(
            "standalone_submit_mismatch: COPILOT_RUNTIME_MODE=standalone 须 SUBMIT_DESTINATION=file_outbox"
        )
    if mode == "standalone" and not s.demo_offline:
        warnings.append("standalone_knowledge_mismatch: 建议 DEMO_OFFLINE=1 使用 Fixture 知识源")
    if mode == "live" and s.demo_offline:
        warnings.append("live_fixture_forbidden: Live 模式禁止 DEMO_OFFLINE=1")
    if int(getattr(s, "uvicorn_workers", 1) or 1) > 1:
        warnings.append("multi_worker_forbidden: SQLite checkpoint 须 UVICORN_WORKERS=1")
    cp = Path(s.checkpoint_db_path)
    try:
        cp.parent.mkdir(parents=True, exist_ok=True)
        test = cp.parent / ".write_probe"
        test.write_text("ok", encoding="utf-8")
        test.unlink(missing_ok=True)
    except OSError as exc:
        warnings.append(f"checkpoint_db_not_writable: {exc}")
    return warnings


def validate_mode(settings: Settings | None = None) -> list[str]:
    """别名：与 validate_runtime_mode 同源（计划/文档用语）。"""
    return validate_runtime_mode(settings)


def strict_runtime_errors(settings: Settings | None = None) -> list[str]:
    """standalone/live 模式错配 + 多 worker → 启动 fail-fast 错误列表。

    multi-worker 始终列入（SQLite checkpoint 非跨进程安全），不依赖 STRICT_STARTUP。
    """
    s = settings or get_settings()
    mode = resolve_runtime_mode(s)
    submit_dest = submit_destination_name(s)
    errors: list[str] = []
    if mode == "standalone":
        if submit_dest != "file_outbox":
            errors.append("standalone 须 SUBMIT_DESTINATION=file_outbox")
        if not s.demo_offline:
            errors.append("standalone 须 DEMO_OFFLINE=1")
    if mode == "live":
        if s.demo_offline:
            errors.append("live 模式禁止 DEMO_OFFLINE=1")
        if submit_dest != "rag_mock_inbox":
            errors.append("live 须 SUBMIT_DESTINATION=rag_mock_inbox")
    if int(getattr(s, "uvicorn_workers", 1) or 1) > 1:
        errors.append("SQLite checkpoint 须 UVICORN_WORKERS=1")
    return errors


def multi_worker_forbidden(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return int(getattr(s, "uvicorn_workers", 1) or 1) > 1
