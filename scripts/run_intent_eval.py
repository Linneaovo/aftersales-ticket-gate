#!/usr/bin/env python3
"""意图规则评测：fit + held_out 双栏；改 data/intent_rules.json 后必须重跑。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIT_CASES = ROOT / "data" / "eval" / "intent_cases.jsonl"
HELD_OUT = ROOT / "data" / "eval" / "intent_cases_held_out.jsonl"
OUT = ROOT / "data" / "eval" / "intent_eval_report.json"


def load_cases(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _eval_split(cases: list[dict], classify_detailed) -> dict:
    from app.domain.intent_rules import fired_rule_id, resolve_intent_confidence_threshold

    thr = resolve_intent_confidence_threshold()
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    failures: list[dict] = []
    correct = 0
    low_conf = 0
    confidences: list[float] = []
    rule_miss: list[dict] = []
    for row in cases:
        q = str(row.get("question") or "")
        expect = str(row.get("expect_intent") or "")
        expect_rule = row.get("expect_rule_id")
        got, conf, signals = classify_detailed(q)
        rid = fired_rule_id(signals)
        confusion[expect][got] += 1
        confidences.append(float(conf))
        if got == "fault_dispatch" and float(conf) < thr:
            low_conf += 1
        if expect_rule and rid and str(expect_rule) != rid:
            rule_miss.append(
                {"id": row.get("id"), "expect_rule_id": expect_rule, "got_rule_id": rid, "question": q}
            )
        if got == expect:
            correct += 1
        else:
            failures.append(
                {
                    "id": row.get("id"),
                    "expect": expect,
                    "got": got,
                    "confidence": conf,
                    "signals": signals,
                    "rule_id": rid,
                    "question": q,
                }
            )
    n = len(cases)
    accuracy = correct / n if n else 0.0
    labels = sorted({str(c.get("expect_intent")) for c in cases} | {g for m in confusion.values() for g in m})
    per_label: dict[str, dict[str, float]] = {}
    for lab in labels:
        tp = confusion[lab].get(lab, 0)
        fp = sum(confusion[o].get(lab, 0) for o in labels if o != lab)
        fn = sum(v for k, v in confusion[lab].items() if k != lab)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        per_label[lab] = {"precision": round(prec, 4), "recall": round(rec, 4), "support": tp + fn}
    return {
        "n_cases": n,
        "correct": correct,
        "accuracy": round(accuracy, 4),
        "per_label": per_label,
        "failures": failures[:30],
        "rule_id_misses": rule_miss[:20],
        "low_confidence_threshold": thr,
        "low_confidence_count": low_conf,
        "low_confidence_rate": round(low_conf / n, 4) if n else 0.0,
        "mean_confidence": round(sum(confidences) / n, 4) if n else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run intent rule eval (fit + held_out)")
    parser.add_argument("--fit", default=str(FIT_CASES))
    parser.add_argument("--held-out", default=str(HELD_OUT))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--min-fit-accuracy", type=float, default=0.85)
    parser.add_argument("--min-held-out-accuracy", type=float, default=0.75)
    args = parser.parse_args()

    from app.graph.nodes import classify_intent_detailed

    fit_cases = load_cases(Path(args.fit))
    held_cases = load_cases(Path(args.held_out))
    if len(fit_cases) < 50:
        print(f"[FAIL] fit need >=50 cases, got {len(fit_cases)}")
        return 1
    if len(held_cases) < 30:
        print(f"[FAIL] held_out need >=30 cases, got {len(held_cases)}")
        return 1

    fit = _eval_split(fit_cases, classify_intent_detailed)
    held = _eval_split(held_cases, classify_intent_detailed)

    def _boundary_buckets(cases: list[dict]) -> dict[str, dict]:
        buckets: dict[str, list[bool]] = {}
        for row in cases:
            b = str(row.get("boundary") or "")
            if not b:
                continue
            got, _, _ = classify_intent_detailed(str(row.get("question") or ""))
            buckets.setdefault(b, []).append(got == row.get("expect_intent"))
        return {
            k: {"n": len(v), "accuracy": round(sum(v) / len(v), 4) if v else 0.0}
            for k, v in buckets.items()
        }

    held["boundary_accuracy"] = _boundary_buckets(held_cases)
    fit_ok = fit["accuracy"] >= args.min_fit_accuracy
    held_ok = held["accuracy"] >= args.min_held_out_accuracy
    rule_ok = not (fit.get("rule_id_misses") or held.get("rule_id_misses"))
    report = {
        "schema": "intent_eval_report/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fit": fit,
        "held_out": held,
        "min_fit_accuracy": args.min_fit_accuracy,
        "min_held_out_accuracy": args.min_held_out_accuracy,
        "ok": fit_ok and held_ok and rule_ok,
        "rule_id_ok": rule_ok,
        "note": (
            "rule baseline; held_out is primary professionalism signal. "
            "expect_rule_id 若钉了则须匹配 fired rule；confidence 为启发式非校准概率。"
            " Re-run after intent_rules.json changes."
        ),
        # 兼容旧字段：主展示 held_out，附 fit
        "n_cases": held["n_cases"],
        "correct": held["correct"],
        "accuracy": held["accuracy"],
    }
    out = Path(args.out)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"wrote {out} fit={fit['accuracy']} held_out={held['accuracy']} "
        f"ok={report['ok']} rule_id_ok={rule_ok} fit_n={fit['n_cases']} held_n={held['n_cases']}"
    )
    for split_name, split in (("fit", fit), ("held_out", held)):
        misses = split.get("rule_id_misses") or []
        if misses:
            print(f"{split_name} rule_id_misses={len(misses)} (up to 5)")
            for m in misses[:5]:
                print(
                    f"  {m.get('id')}: expect_rule={m.get('expect_rule_id')} "
                    f"got_rule={m.get('got_rule_id')}"
                )
    if held["failures"]:
        print(f"held_out failures={len(held['failures'])} (up to 10)")
        for f in held["failures"][:10]:
            print(
                f"  {f['id']}: expect={f['expect']} got={f['got']} "
                f"rule={f.get('rule_id')} signals={f.get('signals')}"
            )
    return 0 if report["ok"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
