"""演示截图：Standalone P1 缺料 → 站长批准 → Outbox（Playwright + Edge）。

用法（需 :8002 + :8502 已启动）：
  python scripts/capture_demo_screenshots.py
  python scripts/capture_demo_screenshots.py --out docs/assets
"""

from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8502"
COPILOT_URL = "http://127.0.0.1:8002"
DEFAULT_OUT = Path("docs/assets")


def _detect_mode() -> str:
    import httpx

    try:
        h = httpx.get(
            f"{COPILOT_URL}/health",
            headers={"X-API-Key": "demo-technician"},
            timeout=10,
        ).json()
        if str(h.get("rag_mode") or "") == "live":
            return "live"
    except Exception:  # noqa: BLE001
        pass
    return "standalone"


def _wait_text(page, text: str, *, timeout_ms: int = 120_000) -> None:
    page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout_ms)


def _sidebar_select(page, label: str, option: str) -> None:
    sidebar = page.locator('[data-testid="stSidebar"]')
    box = sidebar.locator('[data-testid="stSelectbox"]').filter(has_text=label).first
    if box.count() == 0:
        box = sidebar.locator('[data-testid="stSelectbox"]').nth(0 if label == "我是谁" else 1)
    box.click()
    page.get_by_role("option", name=option).click()
    page.wait_for_timeout(800)


def _click_button(page, name: str, *, sidebar: bool = False) -> None:
    root = page.locator('[data-testid="stSidebar"]') if sidebar else page
    root.get_by_role("button", name=name).click()
    page.wait_for_timeout(1200)


def capture(url: str, out_dir: Path, *, mode: str) -> list[Path]:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(url, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(3000)
        _wait_text(page, "报修内容", timeout_ms=60_000)

        # P1：缺料报修 → 待站长确认
        _sidebar_select(page, "示例场景", "缺料报修")
        _click_button(page, "运行示例", sidebar=True)
        _wait_text(page, "待站长确认", timeout_ms=180_000)
        page.wait_for_timeout(1000)

        pending = out_dir / "demo-hitl-pending.png"
        page.screenshot(path=str(pending), full_page=True)
        saved.append(pending)
        print(f"  [OK] {pending}")

        # 切换站长、勾选确认层（批准前）
        _sidebar_select(page, "我是谁", "站长（刘波）")
        page.wait_for_timeout(1500)

        open_doc = page.get_by_role("button", name="打开单据")
        if open_doc.count():
            open_doc.first.click()
            page.wait_for_timeout(2000)

        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(800)

        for label in ("缺料确认", "制度", "时效", "降级", "服务站", "台账", "户外", "意图"):
            row = page.locator('[data-testid="stCheckbox"]').filter(has_text=label)
            if row.count():
                row.first.scroll_into_view_if_needed()
                row.first.click()
                page.wait_for_timeout(200)

        approve = out_dir / "demo-hitl-approve.png"
        page.screenshot(path=str(approve), full_page=True)
        saved.append(approve)
        print(f"  [OK] {approve}")

        # 批准 → Outbox
        approve_btn = page.get_by_role("button", name="批准")
        approve_btn.last.scroll_into_view_if_needed()
        approve_btn.last.click()
        page.wait_for_timeout(1500)
        _wait_text(page, "已提交", timeout_ms=180_000)

        records_label = "收件记录" if mode == "live" else "提交记录"
        _wait_text(page, records_label, timeout_ms=60_000)
        # 滚到提交/收件记录区块，便于 README 展示 Outbox
        page.locator("#submit-records").scroll_into_view_if_needed()
        page.wait_for_timeout(1200)

        outbox = out_dir / "demo-outbox.png"
        page.screenshot(path=str(outbox), full_page=True)
        saved.append(outbox)
        print(f"  [OK] {outbox}")

        browser.close()

    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture README demo screenshots")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--mode", choices=("auto", "standalone", "live"), default="auto")
    args = parser.parse_args()

    mode = _detect_mode() if args.mode == "auto" else args.mode
    print(f"Capturing demo screenshots: {args.url} -> {args.out}  mode={mode}\n")
    try:
        files = capture(args.url, args.out, mode=mode)
    except ImportError:
        print("[FAIL] 请先安装: pip install playwright")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {exc}")
        return 1

    print(f"\n完成，共 {len(files)} 张截图")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
