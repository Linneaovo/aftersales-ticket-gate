#!/usr/bin/env python3
"""生成治理 Scorecard（禁止手填）。

  python scripts/build_governance_scorecard.py
  python scripts/build_governance_scorecard.py --profile standalone
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build governance scorecard from artifacts")
    parser.add_argument(
        "--profile",
        choices=("full", "standalone"),
        default="full",
        help="full=含 Joint 产物；standalone=无 :8001 亦可毕业",
    )
    parser.add_argument(
        "--out",
        default="",
        help="output path (default depends on profile)",
    )
    args = parser.parse_args()
    from app.eval.governance_scorecard import STANDALONE_SCORECARD_PATH, SCORECARD_PATH, write_scorecard

    out = Path(args.out) if args.out else (
        STANDALONE_SCORECARD_PATH if args.profile == "standalone" else SCORECARD_PATH
    )
    card = write_scorecard(out, profile=args.profile)
    print(json.dumps({"wrote": str(out), "profile": args.profile, "all_ok": card.get("all_ok")}, ensure_ascii=False))
    for m in card.get("metrics") or []:
        flag = "OK" if m.get("ok") else ("SKIP" if not m.get("required", True) and not m.get("ok") else "FAIL")
        if not m.get("required", True) and not m.get("ok"):
            flag = "ADV"
        print(f"  [{flag}] {m.get('name')}: {m.get('detail') or m.get('value')}")
    return 0 if card.get("all_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
