"""缺料门禁 A/B 反证：同话术、不同配件库存 → POL-PARTS-01 有无。

离线 FakeRag 即可复现（不依赖 :8001）。
--live 另跑 P1/P1b 剧本 A/B（须 :8002 rag_mode=live）。

用法：
  python scripts/parts_gate_ab_test.py
  python scripts/parts_gate_ab_test.py --live
  → data/eval/parts_gate_ab.json（offline）；live 结果打印/可选落盘
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.eval.parts_gate_ab import nest_parts_gate_ab, run_parts_gate_ab, run_parts_gate_ab_live  # noqa: E402

OUT = ROOT / "data" / "eval" / "parts_gate_ab.json"
OUT_LIVE = ROOT / "data" / "eval" / "parts_gate_ab_live.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="also run Live P1/P1b A/B")
    args = parser.parse_args()

    report = run_parts_gate_ab()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"offline all_ok={report['all_ok']} rag_mode={report.get('rag_mode')}")
    for name, row in report["cases"].items():
        r = row["result"]
        print(
            f"  {name}: passed={row['passed']} status={r['status']} "
            f"POL-PARTS-01={r['has_pol_parts_01']} shortage={r['shortage']}"
        )

    live_ok = True
    if args.live:
        live = run_parts_gate_ab_live()
        OUT_LIVE.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {OUT_LIVE}")
        print(
            f"live present={live.get('present')} all_ok={live.get('all_ok')} "
            f"skip={live.get('skip_reason')!r}"
        )
        for name, row in (live.get("cases") or {}).items():
            r = row.get("result") or {}
            print(
                f"  {name}: passed={row.get('passed')} status={r.get('status')} "
                f"POL-PARTS-01={r.get('has_pol_parts_01')} shortage={r.get('shortage')}"
            )
        nested = nest_parts_gate_ab(offline=report, live=live)
        print(f"nested offline_ok={nested['offline']['all_ok']} live_ok={nested['live']['all_ok']}")
        live_ok = bool(live.get("present") and live.get("all_ok"))

    return 0 if report["all_ok"] and live_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
