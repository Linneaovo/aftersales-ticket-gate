#!/usr/bin/env python3
"""轮询 HTTP 直到 2xx 或超时（供 start_*.cmd 启动闸门）。"""

from __future__ import annotations

import argparse
import sys
import time

import httpx


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True)
    p.add_argument("--timeout-s", type=float, default=45.0)
    p.add_argument("--interval-s", type=float, default=1.0)
    args = p.parse_args()
    deadline = time.monotonic() + max(1.0, args.timeout_s)
    last_err = "unreachable"
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(args.url, timeout=2.0)
            if 200 <= resp.status_code < 300:
                print(f"[OK] ready {args.url} status={resp.status_code}")
                return 0
            last_err = f"status={resp.status_code}"
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
        time.sleep(max(0.2, args.interval_s))
    print(f"[FAIL] not ready {args.url} after {args.timeout_s:.0f}s ({last_err})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
