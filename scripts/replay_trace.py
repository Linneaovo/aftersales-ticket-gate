"""答辩备用：回放已保存 trace，避免 Live RAG 120s 空等。

用法：
  python scripts/replay_trace.py <run_id>
  python scripts/replay_trace.py --latest
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
COP = "http://127.0.0.1:8002"
TECH = {"X-API-Key": "demo-technician"}


def main() -> int:
    run_id = None
    if len(sys.argv) > 1 and sys.argv[1] == "--latest":
        resp = httpx.get(f"{COP}/runs?limit=1", headers=TECH, timeout=15.0)
        items = resp.json().get("items") or []
        if not items:
            print("无 run 记录")
            return 1
        run_id = items[0].get("run_id")
    elif len(sys.argv) > 1:
        run_id = sys.argv[1]
    else:
        print("用法: replay_trace.py <run_id> | --latest")
        return 1

    trace = httpx.get(f"{COP}/runs/{run_id}/trace", headers=TECH, timeout=30.0)
    if trace.status_code != 200:
        print(trace.text)
        return 1
    body = trace.json()
    events = body.get("events") or []
    print(f"run_id={run_id} status={body.get('status')} engine={body.get('engine')}")
    print(f"nodes: {' → '.join(e.get('node') or '?' for e in events)}")
    out = ROOT / "data" / "eval" / f"replay_{run_id}.json"
    out.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
