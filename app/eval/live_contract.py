"""Live 脚本与 Portfolio JSON 的契约常量（防证据过期）。"""

from __future__ import annotations

import hashlib

# 脚本改 checklist 时必须同步 bump；重跑 live_* 写入 JSON。
LIVE_FUNCTION_SCRIPT_VERSION = "2026-08-28.p0"
LIVE_MANUAL_SCRIPT_VERSION = "2026-08-28.p0"

# 全路径跑通时的固定条数（脚本内不得因 skip 少写结果）
LIVE_FUNCTION_EXPECTED_TOTAL = 29
LIVE_MANUAL_EXPECTED_TOTAL = 11


def checklist_hash(names: list[str]) -> str:
    blob = "|".join(names).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]
