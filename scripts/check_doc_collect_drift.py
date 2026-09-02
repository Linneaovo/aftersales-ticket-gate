#!/usr/bin/env python3
"""禁止对外文档写死过时的 pytest collect 数字；须指向 app/eval/ssot.py。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 对外入口：写死 3xx 且像 collect 的数字视为漂移
CHECK_FILES = [
    ROOT / "README.md",
    ROOT / "docs" / "OVERVIEW.md",
    ROOT / "PLAN_B.md",
    ROOT / "ARCHITECTURE.md",
]
# 常见过时写法：collect **310** / 全量 **318**
BAD = re.compile(
    r"(collect\s*\*?\*?)\s*(3[0-2]\d)\b|(全量\s*\*?\*?)\s*(3[0-2]\d)\b|"
    r"\bPYTEST_(?:OFFLINE|FULL)_COLLECT\s*=\s*3[0-2]\d\b|"
    r"当前\s*\*?\*?3[0-2]\d\s*/\s*3[0-2]\d",
    re.IGNORECASE,
)


def main() -> int:
    bad: list[str] = []
    for path in CHECK_FILES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if BAD.search(text):
            bad.append(str(path.relative_to(ROOT)))
    if bad:
        print("[FAIL] stale pytest collect numbers in:", ", ".join(bad))
        print("       Point readers to app/eval/ssot.py instead of hardcoding.")
        return 1
    print("[OK] no hardcoded stale collect counts in public docs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
