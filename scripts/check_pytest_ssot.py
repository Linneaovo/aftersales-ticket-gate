"""校验 pytest collect 与 app.eval.ssot 常量一致。

若仓内 joint_evidence_pack.json 且 live_verified=true，则 acceptance_layers
中的 collect 必须与 ssot 一致（防 Phase 增测后忘再生包）。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "data" / "eval" / "joint_evidence_pack.json"


def check_pack_ssot(offline: int, full: int) -> list[str]:
    """返回错误信息列表；无 pack 或未 live 验证则跳过。"""
    if not PACK.exists():
        return []
    try:
        data = json.loads(PACK.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"pack unreadable: {exc}"]
    if not data.get("live_verified"):
        return []
    layers = data.get("acceptance_layers") or {}
    errs: list[str] = []
    po = layers.get("pytest_offline_collect")
    pf = layers.get("pytest_full_collect")
    if po != offline:
        errs.append(
            f"pack.pytest_offline_collect={po} ≠ ssot={offline}；请 --live 再生 joint_evidence_pack"
        )
    if pf != full:
        errs.append(
            f"pack.pytest_full_collect={pf} ≠ ssot={full}；请 --live 再生 joint_evidence_pack"
        )
    return errs


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from app.eval.ssot import PYTEST_FULL_COLLECT, PYTEST_OFFLINE_COLLECT

    py = ROOT / ".venv" / "Scripts" / "python.exe"
    exe = str(py if py.exists() else sys.executable)
    off = subprocess.run(
        [exe, "-m", "pytest", "--collect-only", "-q", "-m", "not integration"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    full = subprocess.run(
        [exe, "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    text_off = (off.stdout or "") + (off.stderr or "")
    text_full = (full.stdout or "") + (full.stderr or "")
    m_off = re.search(r"(\d+)/(\d+) tests collected", text_off) or re.search(
        r"(\d+) tests collected", text_off
    )
    m_full = re.search(r"(\d+) tests collected", text_full)
    if not m_off or not m_full:
        print(text_off[-500:])
        print(text_full[-500:])
        print("[FAIL] could not parse pytest collect output")
        return 1
    offline_n = int(m_off.group(1))
    full_n = int(m_full.group(1))
    print(f"offline_collect={offline_n} ssot={PYTEST_OFFLINE_COLLECT}")
    print(f"full_collect={full_n} ssot={PYTEST_FULL_COLLECT}")
    ok = offline_n == PYTEST_OFFLINE_COLLECT and full_n == PYTEST_FULL_COLLECT
    if not ok:
        print("[FAIL] update app/eval/ssot.py after adding/removing tests")
        return 1
    pack_errs = check_pack_ssot(PYTEST_OFFLINE_COLLECT, PYTEST_FULL_COLLECT)
    if pack_errs:
        for e in pack_errs:
            print(f"[FAIL] {e}")
        return 1
    if PACK.exists():
        data = json.loads(PACK.read_text(encoding="utf-8"))
        if data.get("live_verified"):
            print("[OK] live pack acceptance_layers match ssot")
        else:
            print("[SKIP] pack present but live_verified=false")
    print("[OK] pytest SSOT matches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
