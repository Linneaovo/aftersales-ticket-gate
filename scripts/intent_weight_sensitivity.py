#!/usr/bin/env python3
"""意图打分权重敏感度：各权重 ±20% 重跑 held-out，证明 confidence 为启发式门禁触发器而非校准概率。"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

HELD = ROOT / "data" / "eval" / "intent_cases_held_out.jsonl"
RULES = ROOT / "data" / "intent_rules.json"
OUT = ROOT / "data" / "eval" / "intent_weight_sensitivity.json"

WEIGHT_KEYS = (
    "fault_code",
    "model",
    "action",
    "symptom",
    "dispatch_token",
    "weak_action",
    "intake_phrase",
    "station_or_jobsite",
)


def _load_cases(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _accuracy(cases: list[dict]) -> float:
    from app.domain.intent_rules import classify_intent_detailed, reload_intent_rules

    reload_intent_rules()
    ok = 0
    for row in cases:
        got, _, _ = classify_intent_detailed(str(row.get("question") or ""))
        if got == row.get("expect_intent"):
            ok += 1
    return ok / len(cases) if cases else 0.0


def _boundary_accuracy(cases: list[dict]) -> dict[str, dict[str, float | int]]:
    from app.domain.intent_rules import classify_intent_detailed, reload_intent_rules

    reload_intent_rules()
    buckets: dict[str, list[bool]] = {}
    for row in cases:
        b = str(row.get("boundary") or "unlabeled")
        got, _, _ = classify_intent_detailed(str(row.get("question") or ""))
        buckets.setdefault(b, []).append(got == row.get("expect_intent"))
    out: dict[str, dict[str, float | int]] = {}
    for k, flags in buckets.items():
        n = len(flags)
        out[k] = {"n": n, "accuracy": round(sum(flags) / n, 4) if n else 0.0}
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--held-out", default=str(HELD))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--delta", type=float, default=0.2)
    args = parser.parse_args()

    from app.domain import intent_rules as ir

    cases = _load_cases(Path(args.held_out))
    if len(cases) < 30:
        print(f"[FAIL] held_out need >=30, got {len(cases)}")
        return 1

    base_rules = json.loads(RULES.read_text(encoding="utf-8"))
    baseline = _accuracy(cases)
    boundary = _boundary_accuracy(cases)

    variants: list[dict] = []
    for key in WEIGHT_KEYS:
        for sign, label in ((1.0, "plus"), (-1.0, "minus")):
            data = deepcopy(base_rules)
            w = dict(data.get("fault_dispatch_score_weights") or {})
            cur = float(w.get(key, 0.0) or 0.0)
            w[key] = max(0.0, round(cur * (1.0 + sign * args.delta), 4))
            data["fault_dispatch_score_weights"] = w
            tmp = Path(args.out).parent / f"_tmp_intent_weights_{key}_{label}.json"
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            # monkeypatch path via reload after swapping _RULES_PATH
            old = ir._RULES_PATH
            ir._RULES_PATH = tmp
            try:
                ir.reload_intent_rules()
                acc = _accuracy(cases)
            finally:
                ir._RULES_PATH = old
                ir.reload_intent_rules()
                tmp.unlink(missing_ok=True)
            variants.append(
                {
                    "weight": key,
                    "variant": label,
                    "value": w[key],
                    "held_out_accuracy": round(acc, 4),
                    "delta_vs_baseline": round(acc - baseline, 4),
                }
            )

    report = {
        "schema": "intent_weight_sensitivity/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "confidence 为启发式信号和（capped 1.0），非校准概率；"
            "本报告仅量化权重扰动对 held-out 的影响，供 POL-INTENT-01 门禁叙事。"
        ),
        "held_out_n": len(cases),
        "baseline_accuracy": round(baseline, 4),
        "boundary_accuracy": boundary,
        "delta": args.delta,
        "variants": variants,
    }
    out = Path(args.out)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out} baseline={baseline:.4f} variants={len(variants)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
