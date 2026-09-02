#!/usr/bin/env python3
"""运行 HITL 闭集门禁评测并写入 data/eval/hitl_gate_report.json。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="HITL gate goldset eval (offline)")
    parser.add_argument(
        "--cases",
        default=str(ROOT / "data" / "eval" / "goldsets" / "hitl_gate_cases.jsonl"),
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "data" / "eval" / "hitl_gate_report.json"),
    )
    args = parser.parse_args()

    from app.config import get_settings
    from app.eval.hitl_gate_eval import write_hitl_gate_report
    from app.graph.builder import reset_graph_cache

    # 隔离 checkpoint，避免污染演示 db
    import os
    import tempfile

    td = tempfile.mkdtemp(prefix="hitl_gate_")
    os.environ["CHECKPOINT_DB_PATH"] = str(Path(td) / "checkpoints.db")
    get_settings.cache_clear()
    reset_graph_cache()

    report = write_hitl_gate_report(Path(args.out), cases_path=Path(args.cases))
    print(json.dumps({"wrote": args.out, "all_ok": report.get("all_ok"), "metrics": report.get("metrics")}, ensure_ascii=False, indent=2))
    failed = [r["id"] for r in (report.get("results") or []) if not r.get("ok")]
    if failed:
        print(f"[FAIL] cases={failed}")
        return 1
    print("[OK] hitl gate goldset")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
