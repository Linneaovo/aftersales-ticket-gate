"""数字 SSOT（文档与证据包对齐；增删测例后更新本常量）。"""

from __future__ import annotations

import subprocess

# pytest --collect-only -q -m "not integration"
PYTEST_OFFLINE_COLLECT = 376
# 含 @pytest.mark.integration 的全量 collect
PYTEST_FULL_COLLECT = 384


def resolve_git_sha() -> str | None:
    """绑定评测产物与代码版本；非 git 仓或失败时返回 None。"""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
        sha = out.strip()
        return sha or None
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None
