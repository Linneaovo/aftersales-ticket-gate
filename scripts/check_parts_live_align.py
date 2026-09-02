"""Live 推荐件号 ↔ parts_ledger 对齐检查（离线可跑）。

- allowlist ⊆ ledger part_no
- 缺料主件 stock==0；对照件 stock>0

用法：
  python scripts/check_parts_live_align.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "data" / "parts_live_allowlist.json"
LEDGER = ROOT / "data" / "parts_ledger.json"


def check(allowlist_path: Path = ALLOWLIST, ledger_path: Path = LEDGER) -> dict:
    errors: list[str] = []
    if not allowlist_path.exists():
        return {"ok": False, "errors": [f"missing allowlist: {allowlist_path}"]}
    if not ledger_path.exists():
        return {"ok": False, "errors": [f"missing ledger: {ledger_path}"]}

    allow = json.loads(allowlist_path.read_text(encoding="utf-8"))
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    items = [i for i in (ledger.get("items") or []) if isinstance(i, dict)]
    by_no = {str(i.get("part_no") or "").strip().upper(): i for i in items if i.get("part_no")}

    part_nos = [str(p).strip() for p in (allow.get("part_nos") or []) if p]
    shortage = [str(p).strip() for p in (allow.get("shortage_part_nos") or []) if p]
    controls = [str(p).strip() for p in (allow.get("in_stock_controls") or []) if p]

    if not part_nos:
        errors.append("allowlist.part_nos empty")

    for pn in part_nos:
        if pn.upper() not in by_no:
            errors.append(f"allowlist part_no missing from ledger: {pn}")

    for pn in shortage:
        row = by_no.get(pn.upper())
        if row is None:
            errors.append(f"shortage part not in ledger: {pn}")
            continue
        if int(row.get("stock") or 0) != 0:
            errors.append(f"shortage part {pn} stock={row.get('stock')} expected 0")

    for pn in controls:
        row = by_no.get(pn.upper())
        if row is None:
            errors.append(f"control part not in ledger: {pn}")
            continue
        if int(row.get("stock") or 0) <= 0:
            errors.append(f"control part {pn} stock={row.get('stock')} expected >0")

    return {
        "ok": not errors,
        "allowlist": str(allowlist_path.relative_to(ROOT)),
        "ledger": str(ledger_path.relative_to(ROOT)),
        "part_nos": part_nos,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Live parts allowlist ↔ ledger align")
    parser.add_argument("--allowlist", default=str(ALLOWLIST))
    parser.add_argument("--ledger", default=str(LEDGER))
    args = parser.parse_args()
    report = check(Path(args.allowlist), Path(args.ledger))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report.get("ok"):
        print("[OK] parts live allowlist subset of ledger; shortage/control stocks aligned")
        return 0
    print("[FAIL] parts live align")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
