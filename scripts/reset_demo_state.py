"""一键清理演示持久化数据：runs.db + checkpoints.db + traces/*.jsonl

用法：
  .\\.venv\\Scripts\\python.exe scripts\\reset_demo_state.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from app.tracing.store import repair_persistence, reset_all_persistence

    report = reset_all_persistence()
    repair = repair_persistence(dry_run=False)
    print(json.dumps({"ok": True, **report, "repair": repair}, ensure_ascii=False, indent=2))
    print("Demo state reset complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
