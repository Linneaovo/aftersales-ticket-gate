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
    # 避免 scripts 入口经 app.tracing.__init__ → graph → store 的环状导入
    import importlib

    store = importlib.import_module("app.tracing.store")
    report = store.reset_all_persistence()
    repair = store.repair_persistence(dry_run=False)
    print(json.dumps({"ok": True, **report, "repair": repair}, ensure_ascii=False, indent=2))
    print("Demo state reset complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
