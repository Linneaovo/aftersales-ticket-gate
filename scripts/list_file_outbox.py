"""列出 FileOutbox 条目（演示端口；非 ERP）。

用法：
  python scripts/list_file_outbox.py
  set SUBMIT_DESTINATION=file_outbox 后提交的 run 会出现在 data/outbox/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from app.tools.submit_destination import FileOutboxDestination

    parser = argparse.ArgumentParser(description="List file_outbox tickets (demo only)")
    parser.add_argument("--dir", default="", help="outbox dir override")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    dest = FileOutboxDestination(outbox_dir=Path(args.dir) if args.dir else None)
    rows = dest.list_tickets(limit=args.limit)
    print(json.dumps({"destination": "file_outbox", "count": len(rows), "items": rows}, ensure_ascii=False, indent=2))
    print(f"[note] is_production_ticket=false · not ERP · dir={dest.outbox_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
