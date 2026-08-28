"""反证演示：停 RAG → POST /runs 失败 → 启 RAG → 成功（约 2 分钟彩排）。

用法（需 Copilot :8002 已启动，.env.demo 已复制）：
  python scripts\\rehearse_rag_failure.py

说明：本脚本只验证 Copilot 侧行为；停/启 RAG 需人工操作或另开终端。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
COPILOT = "http://127.0.0.1:8002"
RAG = "http://127.0.0.1:8001"
TECH = {"X-API-Key": "demo-technician", "Content-Type": "application/json"}


def rag_up() -> bool:
    try:
        r = httpx.get(f"{RAG}/health", timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False


def copilot_health() -> dict:
    r = httpx.get(f"{COPILOT}/health", timeout=10.0)
    r.raise_for_status()
    return r.json()


def post_run() -> tuple[int, dict | str]:
    r = httpx.post(
        f"{COPILOT}/runs",
        headers=TECH,
        json={"question": "SY215C H103请报修处理", "station": "长沙星沙服务站"},
        timeout=120.0,
    )
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text[:300]


def main() -> int:
    print("=== RAG 反证彩排 ===\n")
    print("1) 检查当前状态")
    rag_ok = rag_up()
    h = copilot_health()
    print(f"   RAG :8001 = {'UP' if rag_ok else 'DOWN'}")
    print(f"   Copilot rag_mode={h.get('rag_mode')} demo_warn={h.get('demo_mode_warning')}")

    if not h.get("live_linkage_required"):
        print("\n[WARN] live_linkage_required=false — 建议 copy .env.demo .env 后再彩排")

    print("\n2) POST /runs（当前 RAG 状态）")
    code, body = post_run()
    if rag_ok:
        if code == 200 and isinstance(body, dict):
            linkage = body.get("rag_linkage") or []
            print(f"   HTTP {code} status={body.get('status')} linkage={linkage}")
            if len(linkage) < 2:
                print("   [WARN] rag_linkage 长度 < 2")
        else:
            print(f"   意外: HTTP {code} {body}")
    else:
        if code == 503:
            print(f"   [OK] RAG 不可达时 POST /runs 返回 503（符合预期）")
            print(f"   detail: {body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)[:200]}")
        elif code == 200:
            print("   [FAIL] RAG 已停但 POST /runs 仍成功 — 可能 RAG_AUTO_FALLBACK=1")
            return 1
        else:
            print(f"   HTTP {code}: {body}")

    print("\n3) 彩排话术")
    print("   · 停 RAG → curl /health 见 degraded → POST /runs 503")
    print("   · 启 RAG → 同剧本成功 → 展示 rag_linkage 含 ask")
    print("\n完成。现场演示时手动停/启 enterprise-rag 即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
