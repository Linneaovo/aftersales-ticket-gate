"""跑 ACL 双层矩阵并落盘 data/eval/acl_matrix.json。

用法：
  python scripts/run_acl_matrix.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from app.eval.acl_matrix import write_acl_matrix

    report = write_acl_matrix()
    print(json.dumps({k: report[k] for k in ("schema", "all_ok", "passed", "total", "matrix")}, ensure_ascii=False, indent=2))
    for c in report.get("cases") or []:
        mark = "OK" if c.get("ok") else "FAIL"
        print(f"  [{mark}] {c.get('id')}: status={c.get('status')} rag={c.get('rag_called')} errors={c.get('errors')}")
    return 0 if report.get("all_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
