"""启动前预检：live 联调、持久化卫生、低危 smoke。

用法：
  python scripts\\demo_preflight.py
  python scripts\\demo_preflight.py --require-rag
  python scripts\\demo_preflight.py --require-rag --smoke-run
  python scripts\\demo_preflight.py --require-rag --smoke-run --contract
  python scripts\\demo_preflight.py --reset
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8002"
RAG_BASE = "http://127.0.0.1:8001"
TECH_HEADERS = {"X-API-Key": "demo-technician", "Content-Type": "application/json"}


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"[OK] {msg}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Demo preflight for live RAG linkage or standalone")
    parser.add_argument("--reset", action="store_true", help="run reset_demo_state before checks")
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--require-rag", action="store_true", help="also check enterprise-rag :8001")
    parser.add_argument("--rag-base", default=RAG_BASE)
    parser.add_argument(
        "--standalone",
        action="store_true",
        help="单仓自立预检（无 :8001）；检查 runtime_mode/file_outbox/standalone_scorecard",
    )
    parser.add_argument(
        "--smoke-run",
        action="store_true",
        help="POST playbook 冒烟（live 期望 rag_client_mode=live；standalone 期望 fixture）",
    )
    parser.add_argument(
        "--contract",
        action="store_true",
        help="对 :8001 跑 live_rag_contract_check（消费方契约）",
    )
    parser.add_argument(
        "--skip-align",
        action="store_true",
        help="跳过 parts live allowlist 对齐（默认跑）",
    )
    parser.add_argument(
        "--scorecard",
        action="store_true",
        help="检查 governance/standalone scorecard 存在且未相对源产物过期；可先自动生成",
    )
    parser.add_argument(
        "--refresh-scorecard",
        action="store_true",
        help="先跑 failure drill + scorecard 再检查（常与 --scorecard 同用）",
    )
    parser.add_argument(
        "--matrix",
        action="store_true",
        help="跑 V1–V3 联合验证矩阵（scripts/run_joint_verify.py）；可与 --pack-matrix 联用",
    )
    parser.add_argument(
        "--pack-matrix",
        action="store_true",
        help="矩阵通过后尝试 live 证据包（转交 run_joint_verify --pack）",
    )
    args = parser.parse_args()

    if args.standalone and args.require_rag:
        fail("--standalone 与 --require-rag 互斥")
    if args.standalone and (args.matrix or args.pack_matrix):
        fail("--standalone 与 --matrix/--pack-matrix 互斥（矩阵面向 Live）")

    if args.reset:
        sys.path.insert(0, str(ROOT))
        from app.tracing.store import repair_persistence, reset_all_persistence

        report = reset_all_persistence()
        repair = repair_persistence(dry_run=False)
        print(json.dumps({"reset": report, "repair": repair}, ensure_ascii=False, indent=2))
        ok("reset_demo_state complete")

    print("== demo preflight ==" + (" [standalone]" if args.standalone else ""))

    # E2：allowlist ↔ ledger（离线即可）
    if not args.skip_align:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "check_parts_live_align",
            ROOT / "scripts" / "check_parts_live_align.py",
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        align = mod.check()
        if not align.get("ok"):
            fail(f"parts live align: {align.get('errors')}")
        ok(f"parts live align ({len(align.get('part_nos') or [])} part_nos)")

    if args.require_rag:
        try:
            with httpx.Client(timeout=10.0) as rc:
                rh = rc.get(f"{args.rag_base.rstrip('/')}/health")
            if rh.status_code != 200:
                fail(f"RAG 不可达 ({args.rag_base}) HTTP {rh.status_code}")
            ok("RAG :8001 health 200")
            try:
                rag_health = rh.json()
            except Exception:
                rag_health = {}
            sys.path.insert(0, str(ROOT))
            from app.tools.rag_contract import CONTRACT_VERSION

            supported = rag_health.get("consumer_contract_version_supported")
            if supported != CONTRACT_VERSION:
                fail(
                    f"contract version mismatch: RAG consumer_contract_version_supported={supported!r} "
                    f"Copilot CONTRACT_VERSION={CONTRACT_VERSION!r}（须同日对齐两仓常量）"
                )
            ok(f"contract version mutual match ({CONTRACT_VERSION})")
            if not rag_health.get("submit_require_copilot_token"):
                fail(
                    "RAG submit_require_copilot_token=false — A档联调须经 demo_env/"
                    "start_demo 开启 SUBMIT_REQUIRE_COPILOT_TOKEN=1 并重启 :8001"
                )
            if not rag_health.get("copilot_submit_token_configured"):
                fail("RAG COPILOT_SUBMIT_TOKEN 未配置（与 Copilot .env.demo 同值）")
            ok("RAG submit gate on (token required for business inbox)")
            from app.config import get_settings

            if not (get_settings().copilot_submit_token or "").strip():
                fail("Copilot COPILOT_SUBMIT_TOKEN 为空（.env.demo 应含 demo-copilot-submit-shared）")
            ok("Copilot submit token configured")
        except SystemExit:
            raise
        except Exception as exc:
            fail(f"RAG 不可达 ({args.rag_base}): {exc}")

        joint_path = ROOT / "data" / "eval" / "joint_evidence_pack.json"
        if joint_path.is_file():
            try:
                joint = json.loads(joint_path.read_text(encoding="utf-8"))
                if not joint.get("live_verified"):
                    print(
                        "[WARN] joint_evidence_pack live_verified=false — "
                        "不得宣称当场联调；请 python scripts/build_joint_evidence_pack.py --live"
                    )
                else:
                    ok("joint_evidence_pack live_verified=true")
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] cannot read joint_evidence_pack: {exc}")

    if args.contract and not args.standalone:
        import importlib.util

        # 仅 --contract 未带 --require-rag 时，仍做版本互证
        if not args.require_rag:
            try:
                with httpx.Client(timeout=10.0) as rc:
                    rh = rc.get(f"{args.rag_base.rstrip('/')}/health")
                if rh.status_code != 200:
                    fail(f"RAG 不可达 ({args.rag_base}) HTTP {rh.status_code}")
                rag_health = rh.json()
                sys.path.insert(0, str(ROOT))
                from app.tools.rag_contract import CONTRACT_VERSION

                supported = rag_health.get("consumer_contract_version_supported")
                if supported != CONTRACT_VERSION:
                    fail(
                        f"contract version mismatch: RAG consumer_contract_version_supported={supported!r} "
                        f"Copilot CONTRACT_VERSION={CONTRACT_VERSION!r}"
                    )
                ok(f"contract version mutual match ({CONTRACT_VERSION})")
            except SystemExit:
                raise
            except Exception as exc:
                fail(f"RAG health/version check failed: {exc}")

        spec = importlib.util.spec_from_file_location(
            "live_rag_contract_check",
            ROOT / "scripts" / "live_rag_contract_check.py",
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        crep = mod.check(args.rag_base)
        ver = crep.get("contract_version")
        if not crep.get("all_ok"):
            fail(f"RAG consumer contract failed (v={ver}): {crep.get('errors')}")
        ok(f"RAG consumer contract v={ver} (ask/draft/submit/inbox)")

    try:
        with httpx.Client(timeout=30.0) as c:
            h = c.get(f"{args.base.rstrip('/')}/health")
    except Exception as exc:
        fail(f"Copilot 不可达 ({args.base}): {exc}")

    if h.status_code != 200:
        fail(f"/health HTTP {h.status_code}: {h.text[:200]}")

    body = h.json()
    sys.path.insert(0, str(ROOT))
    from app import __version__

    health_version = str(body.get("version") or "")
    if health_version != __version__:
        fail(
            f"/health.version={health_version!r} != 源码 {__version__!r} "
            "（改代码后须重启 Copilot :8002）"
        )
    ok(f"version match ({__version__})")

    rag_mode = body.get("rag_mode")
    demo_warn = body.get("demo_mode_warning")
    live_req = body.get("live_linkage_required")
    runtime_mode = body.get("runtime_mode")
    submit_dest = body.get("submit_destination")
    knowledge_port = body.get("knowledge_port")

    print(f"runtime_mode={runtime_mode} · knowledge_port={knowledge_port} · submit={submit_dest}")
    print(f"rag_mode={rag_mode} · demo_mode_warning={demo_warn} · live_linkage_required={live_req}")
    print(f"rag_auto_fallback={body.get('rag_auto_fallback')} · persistence_ok={body.get('persistence_ok')}")
    print(
        f"ledger sha256={body.get('parts_ledger_sha256')} · items={body.get('parts_item_count')} · "
        f"contract={body.get('rag_contract_version')}"
    )

    # E1：进程 health 指纹 vs 磁盘台账
    sys.path.insert(0, str(ROOT))
    from app.domain.parts_catalog import parts_ledger_fingerprint

    disk_fp = parts_ledger_fingerprint()
    health_sha = str(body.get("parts_ledger_sha256") or "")
    disk_sha = str(disk_fp.get("parts_ledger_sha256") or "")
    if disk_sha and health_sha and health_sha != disk_sha:
        fail(
            f"parts ledger fingerprint mismatch: health={health_sha} disk={disk_sha} "
            "（进程读到旧台账？POST /admin/reload-ledger 或重启 :8002）"
        )
    if disk_sha:
        ok(f"ledger fingerprint match ({disk_sha})")

    mode_warnings = body.get("mode_warnings") or []
    if mode_warnings:
        fail("mode_warnings: " + " · ".join(str(w) for w in mode_warnings))

    if args.standalone:
        if runtime_mode != "standalone":
            fail(f"runtime_mode={runtime_mode}，期望 standalone（copy .env.standalone .env 并重启 :8002）")
        if submit_dest != "file_outbox":
            fail(f"submit_destination={submit_dest}，期望 file_outbox")
        if knowledge_port != "fixture":
            fail(f"knowledge_port={knowledge_port}，期望 fixture")
        if live_req:
            fail("standalone 下 live_linkage_required 须为 false")
        ok("standalone mode gates (runtime/file_outbox/fixture · no mode_warnings)")
    else:
        if live_req and rag_mode != "live":
            fail("live 模式要求 rag_mode=live。请 copy .env.demo .env 并启动 enterprise-rag :8001")
        if demo_warn:
            fail("demo_mode_warning=true — Standalone 请用 --standalone；联调请设 RAG_AUTO_FALLBACK=0")

    persistence = body.get("persistence") or {}
    if not persistence.get("healthy"):
        hint = body.get("persistence_hint") or "POST /persistence/repair"
        fail(f"persistence unhealthy: {hint}")

    if args.smoke_run:
        try:
            pb = "p1b_no_shortage_ready" if not args.standalone else "p1_xingsha_h103"
            with httpx.Client(timeout=120.0) as c:
                resp = c.post(
                    f"{args.base.rstrip('/')}/playbooks/{pb}/run",
                    headers=TECH_HEADERS,
                )
            if resp.status_code != 200:
                fail(f"smoke playbook {pb} HTTP {resp.status_code}: {resp.text[:300]}")
            run = resp.json()
            if args.standalone:
                if run.get("knowledge_port") != "fixture" and run.get("rag_client_mode") != "demo_offline":
                    fail(
                        f"standalone smoke knowledge_port={run.get('knowledge_port')} "
                        f"rag_client_mode={run.get('rag_client_mode')}"
                    )
                if run.get("status") != "waiting_hitl":
                    fail(f"standalone smoke P1 status={run.get('status')}，期望 waiting_hitl")
                ok(f"smoke {pb} status={run.get('status')} knowledge_port=fixture")
            else:
                if run.get("rag_client_mode") != "live":
                    fail(f"smoke run rag_client_mode={run.get('rag_client_mode')}，期望 live")
                linkage = run.get("rag_linkage") or []
                if "ask" not in linkage:
                    fail(f"smoke run rag_linkage 缺少 ask: {linkage}")
                if run.get("status") != "succeeded":
                    fail(f"smoke p1b status={run.get('status')}，期望 succeeded（有库存不阻塞）")
                ok(f"smoke p1b status={run.get('status')} rag_linkage={' → '.join(linkage)}")
        except Exception as exc:
            fail(f"smoke playbook 失败: {exc}")

    if args.standalone and (args.refresh_scorecard or args.scorecard or True):
        # standalone 默认刷新/检查 standalone_scorecard
        sys.path.insert(0, str(ROOT))
        from app.eval.governance_scorecard import STANDALONE_SCORECARD_PATH, write_scorecard

        if args.refresh_scorecard or not STANDALONE_SCORECARD_PATH.exists():
            card = write_scorecard(profile="standalone")
            if not card.get("all_ok"):
                fail(
                    "standalone_scorecard all_ok=false: "
                    + str([m.get("name") for m in (card.get("metrics") or []) if m.get("required", True) and not m.get("ok")])
                )
            ok("standalone_scorecard generated all_ok=true")
        else:
            card = json.loads(STANDALONE_SCORECARD_PATH.read_text(encoding="utf-8"))
            if card.get("hand_filled"):
                fail("standalone_scorecard hand_filled=true 禁止")
            if not card.get("all_ok"):
                fail("standalone_scorecard all_ok=false — 运行 --refresh-scorecard")
            ok("standalone_scorecard present all_ok=true")
        if body.get("standalone_scorecard_ok") is False:
            print("[WARN] /health standalone_scorecard_ok=false — 重启 :8002 后应读到新产物")

    if (args.refresh_scorecard or args.scorecard) and not args.standalone:
        sys.path.insert(0, str(ROOT))
        if args.refresh_scorecard:
            from app.eval.governance_scorecard import write_scorecard
            from app.eval.hitl_gate_eval import write_hitl_gate_report
            import importlib.util
            import os
            import tempfile

            from app.config import get_settings
            from app.graph.builder import reset_graph_cache

            td = tempfile.mkdtemp(prefix="preflight_hitl_")
            os.environ["CHECKPOINT_DB_PATH"] = str(Path(td) / "checkpoints.db")
            get_settings.cache_clear()
            reset_graph_cache()
            hitl_rep = write_hitl_gate_report()
            if not hitl_rep.get("all_ok"):
                fail(
                    "hitl_gate_report all_ok=false: "
                    + str([r.get("id") for r in (hitl_rep.get("results") or []) if not r.get("ok")])
                )
            ok("refreshed hitl_gate_report")

            spec = importlib.util.spec_from_file_location(
                "build_joint_failure_drill",
                ROOT / "scripts" / "build_joint_failure_drill.py",
            )
            drill_mod = importlib.util.module_from_spec(spec)
            assert spec.loader is not None
            spec.loader.exec_module(drill_mod)
            drill = drill_mod.build_drill(probe_live=False)
            drill_path = ROOT / "data" / "eval" / "joint_failure_drill.json"
            drill_path.write_text(
                json.dumps(drill, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if not drill.get("all_ok"):
                fail(f"joint_failure_drill all_ok=false: {[s.get('id') for s in drill.get('scenes') or [] if not s.get('ok')]}")
            card = write_scorecard()
            if not card.get("all_ok"):
                print("[WARN] governance_scorecard all_ok=false after refresh")
            ok("refreshed joint_failure_drill + governance_scorecard")

        from app.eval.governance_scorecard import SCORECARD_PATH, scorecard_is_stale

        if not SCORECARD_PATH.exists():
            fail("governance_scorecard missing — run with --refresh-scorecard")
        stale, reasons = scorecard_is_stale()
        if stale:
            fail(
                "governance_scorecard stale vs sources: "
                + ", ".join(reasons)
                + " — re-run with --refresh-scorecard"
            )
        card = json.loads(SCORECARD_PATH.read_text(encoding="utf-8"))
        if card.get("hand_filled"):
            fail("governance_scorecard hand_filled=true 禁止")
        if not card.get("all_ok"):
            print("[WARN] governance_scorecard all_ok=false — 查看 metrics")
        else:
            ok("governance_scorecard present, fresh, all_ok=true")

    if args.matrix or args.pack_matrix:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "run_joint_verify",
            ROOT / "scripts" / "run_joint_verify.py",
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        old_argv = sys.argv
        argv = ["run_joint_verify.py", "--rag-base", args.rag_base]
        if args.pack_matrix:
            argv.append("--pack")
        try:
            sys.argv = argv
            code = mod.main()
        finally:
            sys.argv = old_argv
        if code != 0:
            fail("joint verify matrix failed — 见 data/eval/joint_verify_matrix.json")
        ok("joint verify matrix passed")

    ok("preflight passed")
    print("提示: 改 parts_ledger.json 后无需重启；改 Copilot 代码后请重启 :8002")
    print(
        "口径: Standalone绿≠Live；仅 live_verified=true 可宣称本机联调；"
        "token 为演示归属非生产鉴权"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
