"""页面功能回归：模拟 Streamlit UI 调用的全部 API 路径（单仓 / 联调）。"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8002"
TECH = "demo-technician"
PARTS = "demo-parts"
CHIEF = "demo-chief"


@dataclass
class Report:
    mode: str = ""
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def ok(self, name: str) -> None:
        self.passed.append(name)
        print(f"  [PASS] {name}")

    def fail(self, name: str, detail: str) -> None:
        self.failed.append(f"{name}: {detail}")
        print(f"  [FAIL] {name}: {detail}")

    def skip(self, name: str, reason: str) -> None:
        self.skipped.append(f"{name}: {reason}")
        print(f"  [SKIP] {name}: {reason}")

    def summary(self) -> int:
        print("\n" + "=" * 60)
        print(f"模式: {self.mode}")
        print(f"通过: {len(self.passed)}  失败: {len(self.failed)}  跳过: {len(self.skipped)}")
        if self.failed:
            print("\n失败项:")
            for f in self.failed:
                print(f"  - {f}")
        return 1 if self.failed else 0


def hdr(key: str) -> dict[str, str]:
    return {"X-API-Key": key, "Content-Type": "application/json"}


def run_common_tests(r: Report) -> None:
    """两种模式共用的页面能力（剧本、报修、HITL、草稿、参考回答等）。"""
    with httpx.Client(base_url=BASE, timeout=180.0) as c:
        h = c.get("/health", headers=hdr(TECH)).json()
        r.mode = str(h.get("runtime_mode") or "?")
        dest = str(h.get("submit_destination") or "")

        pbs = c.get("/playbooks?lane=core", headers=hdr(TECH)).json().get("items") or []
        ids = {p.get("id") for p in pbs}
        for pid in ("p1_xingsha_h103", "p1b_no_shortage_ready", "p8_parts_clerk_conflict"):
            if pid in ids:
                r.ok(f"playbooks.core.{pid}")
            else:
                r.fail(f"playbooks.core.{pid}", "missing")

        p1 = c.post("/playbooks/p1_xingsha_h103/run?view=public", headers=hdr(TECH)).json()
        if p1.get("status") != "waiting_hitl":
            r.fail("P1.status", str(p1.get("status")))
        else:
            r.ok("P1 → waiting_hitl")
        if not (p1.get("parts_check") or {}).get("shortage"):
            r.fail("P1.parts_shortage", "expected shortage")
        else:
            r.ok("P1 配件缺料")
        run_id = p1.get("run_id")
        if not run_id:
            r.fail("P1.run_id", "missing")
            return

        pending = [
            x
            for x in (c.get("/runs?limit=30", headers=hdr(CHIEF)).json().get("items") or [])
            if x.get("status") == "waiting_hitl"
        ]
        if run_id in {x.get("run_id") for x in pending}:
            r.ok("站长待办列表")
        else:
            r.fail("chief.pending_list", f"{run_id} missing")

        opened = c.get(f"/runs/{run_id}?view=public", headers=hdr(CHIEF)).json()
        if opened.get("run_id") == run_id:
            r.ok("打开单据")
        else:
            r.fail("GET /runs/{id}", "mismatch")

        rid_rej = c.post("/playbooks/p1_xingsha_h103/run?view=public", headers=hdr(TECH)).json().get("run_id")
        rejected = c.post(
            f"/runs/{rid_rej}/hitl?view=public",
            headers=hdr(CHIEF),
            json={"decision": "reject", "note": "test"},
        ).json()
        if rejected.get("status") == "rejected":
            r.ok("HITL 拒绝")
        else:
            r.fail("HITL.reject", str(rejected.get("status")))

        rid_ret = c.post("/playbooks/p1_xingsha_h103/run?view=public", headers=hdr(TECH)).json().get("run_id")
        returned = c.post(
            f"/runs/{rid_ret}/hitl?view=public",
            headers=hdr(CHIEF),
            json={"decision": "return", "note": "请补充"},
        ).json()
        if (returned.get("hitl") or {}).get("decision") == "return":
            r.ok("HITL 退回")
        else:
            r.fail("HITL.return", str(returned.get("hitl")))

        p1a = c.post("/playbooks/p1_xingsha_h103/run?view=public", headers=hdr(TECH)).json()
        rid = p1a.get("run_id")
        layers = list((p1a.get("hitl") or {}).get("pending_layers") or [])
        approved = c.post(
            f"/runs/{rid}/hitl?view=public",
            headers=hdr(CHIEF),
            json={"decision": "approve", "note": "test", "confirmations": {x: True for x in layers}},
        ).json()
        if approved.get("status") == "succeeded":
            r.ok("HITL 批准")
        else:
            r.fail("HITL.approve", str(approved.get("status")))
        if approved.get("work_order_submit"):
            r.ok("work_order_submit")
        else:
            r.fail("work_order_submit", "missing")
        if approved.get("decision_certificate"):
            r.ok("decision_certificate")
        else:
            r.fail("decision_certificate", "missing")

        if dest == "file_outbox":
            items = (c.get("/outbox?limit=10", headers=hdr(CHIEF)).json().get("items") or [])
            label = "GET /outbox"
        else:
            items = (c.get("/inbox?limit=10", headers=hdr(CHIEF)).json().get("items") or [])
            label = "GET /inbox"
        if items:
            r.ok(f"{label} 有记录")
        else:
            r.fail(label, "empty after approve")

        rid_cancel = c.post("/playbooks/p1_xingsha_h103/run?view=public", headers=hdr(TECH)).json().get("run_id")
        cancelled = c.post(f"/runs/{rid_cancel}/cancel", headers=hdr(CHIEF)).json()
        if cancelled.get("status") == "cancelled":
            r.ok("取消单据")
        else:
            r.fail("cancel", str(cancelled.get("status")))

        p1b = c.post("/playbooks/p1b_no_shortage_ready/run?view=public", headers=hdr(TECH)).json()
        if p1b.get("work_order_state") == "ready_for_chief" and p1b.get("status") != "waiting_hitl":
            r.ok("P1b 有库存对照")
        else:
            r.fail("P1b", f"state={p1b.get('work_order_state')} status={p1b.get('status')}")

        p8 = c.post("/playbooks/p8_parts_clerk_conflict/run?view=public", headers=hdr(PARTS)).json()
        if (p8.get("conflict_bundle") or {}).get("present"):
            r.ok("P8 制度冲突")
        else:
            r.fail("P8", "no conflict")

        manual = c.post(
            "/runs?view=public",
            headers=hdr(TECH),
            json={
                "question": "星沙站 SY215C 故障码 H103，动臂液压无力，请开单",
                "knowledge_base": "demo-kb",
                "api_key": TECH,
                "auto_submit": False,
                "second_visit": False,
                "station": "长沙星沙服务站",
            },
        ).json()
        if manual.get("status") in {"waiting_hitl", "succeeded"}:
            r.ok("手动提交报修")
        else:
            r.fail("POST /runs", str(manual.get("status")))
        if manual.get("rag") or p1.get("rag"):
            r.ok("参考回答 rag 字段")
        else:
            r.fail("rag", "missing")
        if manual.get("work_order_draft") or p1.get("work_order_draft"):
            r.ok("开单草稿")
        else:
            r.fail("work_order_draft", "missing")

        try:
            ev = c.post("/eval/compare?engine=langgraph&live_rag=false", headers=hdr(TECH)).json()
            if ev.get("summary"):
                r.ok("离线对照实验")
            else:
                r.fail("eval/compare", "no summary")
        except Exception as exc:  # noqa: BLE001
            r.fail("eval/compare", str(exc))


def run_standalone_checks(r: Report) -> None:
    with httpx.Client(base_url=BASE, timeout=30.0) as c:
        h = c.get("/health", headers=hdr(TECH)).json()
        if h.get("runtime_mode") != "standalone":
            r.fail("standalone.runtime_mode", str(h.get("runtime_mode")))
        else:
            r.ok("standalone.runtime_mode")
        if h.get("submit_destination") != "file_outbox":
            r.fail("standalone.file_outbox", str(h.get("submit_destination")))
        else:
            r.ok("standalone.file_outbox")
        if h.get("persistence_ok"):
            r.ok("standalone.persistence_ok")
        else:
            r.fail("standalone.persistence_ok", "false")


def run_live_checks(r: Report) -> None:
    with httpx.Client(base_url=BASE, timeout=30.0) as c:
        h = c.get("/health", headers=hdr(TECH)).json()
        if h.get("rag_mode") != "live":
            r.skip("live.rag_mode", str(h.get("rag_mode")))
            return
        rag = h.get("rag") or {}
        if rag.get("ok"):
            r.ok("live.rag.ok")
        else:
            r.fail("live.rag.ok", "false")
        if h.get("submit_destination") == "rag_mock_inbox":
            r.ok("live.rag_mock_inbox")
        else:
            r.fail("live.inbox", str(h.get("submit_destination")))
        p1 = c.post("/playbooks/p1_xingsha_h103/run?view=public", headers=hdr(TECH)).json()
        if p1.get("rag_linkage"):
            r.ok(f"live.rag_linkage={p1.get('rag_linkage')}")
        else:
            r.fail("live.rag_linkage", "missing")


def run_standalone_tests(r: Report) -> None:
    run_standalone_checks(r)
    run_common_tests(r)


def run_live_tests(r: Report) -> None:
    run_live_checks(r)
    run_common_tests(r)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("auto", "standalone", "live"), default="auto")
    args = parser.parse_args()

    print("UI page function test")
    print(f"Target: {BASE}\n")

    with httpx.Client(base_url=BASE, timeout=10.0) as c:
        try:
            h = c.get("/health", headers=hdr(TECH)).json()
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] API unreachable: {exc}")
            return 1

    detected = str(h.get("runtime_mode") or "")
    mode = detected if args.mode == "auto" else args.mode
    r = Report(mode=mode)
    print(f"runtime_mode={detected}  test_as={mode}\n")

    if mode == "standalone":
        if detected != "standalone":
            print("[WARN] API not in standalone; results may fail standalone checks")
        print("-- Standalone --")
        run_standalone_tests(r)
    else:
        print("-- Live --")
        run_live_tests(r)

    out = ROOT / "data" / "eval" / "ui_page_function_test.json"
    out.write_text(
        json.dumps(
            {"mode": r.mode, "passed": r.passed, "failed": r.failed, "skipped": r.skipped},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nReport: {out}")
    return r.summary()


if __name__ == "__main__":
    sys.exit(main())
