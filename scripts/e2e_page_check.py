"""浏览器 E2E：单仓 / 联调页面主路径（Playwright + 系统 Edge）。仅终端输出，不写报告文件。

用法：
  pip install playwright
  python scripts/e2e_page_check.py
  python scripts/e2e_page_check.py --mode live
  python scripts/e2e_page_check.py --headed
"""

from __future__ import annotations

import argparse
import sys
import time

DEFAULT_URL = "http://127.0.0.1:8502"
COPILOT_URL = "http://127.0.0.1:8002"


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


def _approve_chief(page, ok, fail) -> bool:
    try:
        _sidebar_select(page, "我是谁", "站长（刘波）")
        page.wait_for_timeout(1500)
        ok("切换站长角色")

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

        approve_btn = page.get_by_role("button", name="批准")
        approve_btn.last.scroll_into_view_if_needed()
        approve_btn.last.click()
        page.wait_for_timeout(1500)
        _wait_text(page, "已提交", timeout_ms=180_000)
        ok("站长批准 → 已提交")
        return True
    except Exception as exc:  # noqa: BLE001
        fail("站长批准", str(exc))
        return False


def run_e2e(url: str, *, headed: bool, mode: str) -> tuple[list[str], list[str]]:
    from playwright.sync_api import sync_playwright

    passed: list[str] = []
    failed: list[str] = []

    def ok(step: str) -> None:
        passed.append(step)
        print(f"  [PASS] {step}")

    def fail(step: str, detail: str) -> None:
        failed.append(f"{step}: {detail}")
        print(f"  [FAIL] {step}: {detail}")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=not headed)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(url, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(3000)
        _wait_text(page, "报修内容", timeout_ms=60_000)

        body = page.inner_text("body")
        live = mode == "live" or "联调模式" in body
        if live:
            if "联调模式" in body:
                ok("顶栏联调模式")
            else:
                fail("顶栏联调模式", "未找到「联调模式」")
            if "知识库已连接" in body:
                ok("知识库已连接")
            else:
                fail("知识库状态", "未显示已连接")
        else:
            if "单仓演示" in body:
                ok("顶栏单仓模式")
            else:
                fail("顶栏单仓模式", "未找到「单仓演示」")

        records_label = "收件记录" if live else "提交记录"

        try:
            _sidebar_select(page, "示例场景", "缺料报修")
            _click_button(page, "运行示例", sidebar=True)
            _wait_text(page, "待站长确认", timeout_ms=180_000)
            ok("P1 运行示例 → 待站长确认")
            if live:
                body = page.inner_text("body")
                if "联动" in body and ("问答" in body or "检索" in body or "开单" in body):
                    ok("联动链可见")
                else:
                    fail("联动链", "未找到联动提示")
        except Exception as exc:  # noqa: BLE001
            fail("P1 运行示例", str(exc))
            browser.close()
            return passed, failed

        if not _approve_chief(page, ok, fail):
            browser.close()
            return passed, failed

        try:
            _wait_text(page, records_label, timeout_ms=30_000)
            after = page.inner_text("body")
            if "审批留痕" in after:
                ok("审批留痕可见")
            else:
                fail("审批留痕", "未找到")
            if "★" in after or "本次提交" in after:
                ok(f"{records_label}高亮")
            else:
                fail(f"{records_label}高亮", "未找到高亮标记")
        except Exception as exc:  # noqa: BLE001
            fail(records_label, str(exc))

        if not live:
            try:
                _sidebar_select(page, "示例场景", "有库存")
                _click_button(page, "运行示例", sidebar=True)
                _wait_text(page, "对照结果", timeout_ms=120_000)
                ok("P1b 有库存对照")
            except Exception as exc:  # noqa: BLE001
                fail("P1b 有库存", str(exc))

        browser.close()
    return passed, failed


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Streamlit page E2E (Playwright + Edge)")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--mode", choices=("auto", "standalone", "live"), default="auto")
    parser.add_argument("--headed", action="store_true", help="有界面运行（非 headless）")
    args = parser.parse_args()

    mode = _detect_mode() if args.mode == "auto" else args.mode
    print(f"E2E page check: {args.url}  mode={mode}\n")
    t0 = time.time()
    try:
        passed, failed = run_e2e(args.url, headed=args.headed, mode=mode)
    except ImportError:
        print("[FAIL] 请先安装: pip install playwright")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {exc}")
        return 1

    elapsed = round(time.time() - t0, 1)
    print(f"\n通过 {len(passed)}  失败 {len(failed)}  耗时 {elapsed}s")
    if failed:
        for f in failed:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
