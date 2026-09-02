"""启动守卫：多 worker / 模式错配 / validate_mode 别名。"""

from __future__ import annotations

from app.config import (
    Settings,
    multi_worker_forbidden,
    strict_runtime_errors,
    validate_mode,
    validate_runtime_mode,
)


def test_validate_mode_aliases_runtime_mode():
    s = Settings(copilot_runtime_mode="standalone", demo_offline=True, submit_destination="file_outbox")
    assert validate_mode(s) == validate_runtime_mode(s)


def test_multi_worker_always_in_strict_errors():
    s = Settings(
        copilot_runtime_mode="standalone",
        demo_offline=True,
        submit_destination="file_outbox",
        uvicorn_workers=2,
    )
    assert multi_worker_forbidden(s) is True
    errs = strict_runtime_errors(s)
    assert any("UVICORN_WORKERS" in e or "workers" in e.lower() for e in errs)


def test_standalone_mismatch_in_strict_errors():
    s = Settings(
        copilot_runtime_mode="standalone",
        demo_offline=False,
        submit_destination="rag_mock_inbox",
        uvicorn_workers=1,
    )
    errs = strict_runtime_errors(s)
    assert any("file_outbox" in e for e in errs)
    assert any("DEMO_OFFLINE" in e for e in errs)
