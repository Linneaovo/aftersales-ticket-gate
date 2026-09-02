"""静态门禁：work_order_submit 仅允许在 submit_node 赋值。"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"

# 允许写入 work_order_submit 的业务路径（Policy-as-Code 单写点）
ALLOWED_WRITE = {
    APP / "graph" / "nodes.py",
}

WRITE_PATTERNS = (
    re.compile(r"""state\s*\[\s*['"]work_order_submit['"]\s*\]\s*="""),
    re.compile(r"""['"]work_order_submit['"]\s*:\s*[^N]"""),  # dict literal in return - check separately
)


def test_work_order_submit_single_write_path():
    violations: list[str] = []
    for path in APP.rglob("*.py"):
        if path in ALLOWED_WRITE:
            continue
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if 'state["work_order_submit"]' in line or "state['work_order_submit']" in line:
                if "=" in line.split("#")[0]:
                    violations.append(f"{path.relative_to(ROOT)}:{i}: {line.strip()}")
    assert not violations, "work_order_submit 须仅经 submit_node 写入:\n" + "\n".join(violations)


def test_submit_node_calls_evaluate_submit_eligible():
    nodes = (APP / "graph" / "nodes.py").read_text(encoding="utf-8")
    assert "def submit_node" in nodes
    idx = nodes.index("def submit_node")
    chunk = nodes[idx : idx + 2500]
    assert "evaluate_submit_eligible(state)" in chunk
    assert 'state["work_order_submit"]' in chunk
    # 赋值必须出现在 evaluate 调用之后
    assert chunk.index("evaluate_submit_eligible(state)") < chunk.index('state["work_order_submit"]')


def test_submit_destination_call_sites_gated():
    """凡调用 dest.submit / get_submit_destination().submit 的业务路径须先过门禁。"""
    violations: list[str] = []
    for path in (APP / "graph").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "def submit_node" in text:
            # submit_node 已由上一测保证
            continue
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.split("#")[0]
            if ".submit(" in stripped and "evaluate_submit_eligible" not in stripped:
                if "submit_node" in stripped:
                    continue
                # fallback / helper 不应直接落箱
                if "dest.submit" in stripped or "get_submit_destination" in stripped:
                    violations.append(f"{path.relative_to(ROOT)}:{i}: {line.strip()}")
    assert not violations, "submit destination 调用须仅经 submit_node:\n" + "\n".join(violations)
