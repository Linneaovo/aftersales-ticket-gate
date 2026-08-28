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
    conflict_policy: str = "no_arbitration"
    persist_mode: str = "slim"  # slim | full
    demo_offline: bool = False  # 强制离线 DemoRag，不连 :8001
    rag_auto_fallback: bool = False  # :8001 不可达时自动切 DemoRag（演示 live 请保持 0）
    require_known_api_key: bool = False  # True 时拒绝 KEY_ROLE_MAP 外 Key
    rag_reachability_ttl_s: float = 30.0  # RAG 可达性缓存 TTL（秒）；/health 强制刷新
    cors_origins: str = "http://127.0.0.1:8502,http://localhost:8502"  # 逗号分隔；* 表示全开放
    block_runs_when_not_live: bool = False  # True 时 POST /runs 在 RAG 不可达或 demo_offline 客户端返回 503
    require_live: bool = False  # 同 block_runs_when_not_live 的语义别名（REQUIRE_LIVE=1）
    role_claim_header: str = "X-Role-Claim"  # 生产 IdP 角色声明；API 层 resolve_role 已接入
    trust_role_claim: bool = False  # True 时信任 X-Role-Claim（须 IdP 网关校验）；演示默认须与 Key 绑定
    demo_keys_path: str = str(PROJECT_ROOT / "data" / "demo_keys.json")
    orphan_checkpoint_threshold: int = 5  # 超过则 /health 提示 repair
    engine_strict: bool = False  # True 时 LangGraph 异常不静默降级 fallback
    expose_metrics: bool = True  # False 时隐藏 /metrics（演示可关）
    expose_demo_hints: bool = False  # True 时 /health 返回 demo_checklist


@lru_cache
def get_settings() -> Settings:
    return Settings()
