"""联调证据分层（L0 / L1 / L2）— 宣称口径 SSOT。

口径（对外必须一致）：
- L0：进程内 FakeRag / pytest — 证编排门禁，不证 HTTP 联调
- L1：Compose 契约 HTTP 桩 — 证契约与 submit 归属，不证检索/生成质量
- L2：真 enterprise-rag + 模型 — 可 `live_verified=true`；本机/self-hosted/夜间

`--from-artifacts` 永不可称 L2；快照不得冒充当场 Live。
"""

from __future__ import annotations

from typing import Any, Literal

EvidenceTier = Literal["L0", "L1", "L2", "artifacts"]

CLAIM_MATRIX: dict[str, dict[str, str]] = {
    "L0": {
        "name": "Offline FakeRag",
        "proves": "编排门禁回归（pytest / scorecard）",
        "does_not_prove": "HTTP 联调、检索质量、生成正确性",
        "who_runs": "默认 CI（ci.yml）",
        "may_claim": "离线门禁回归通过",
        "forbidden_claim": "Live 联调 / 真 RAG",
    },
    "L1": {
        "name": "HTTP Contract Linkage",
        "proves": "双仓 HTTP 契约、submit 归属、draft→HITL→inbox",
        "does_not_prove": "向量检索质量、生成正确性、真 Ollama",
        "who_runs": "默认 CI（linkage-l1.yml）+ docker compose -f docker-compose.joint.yml",
        "may_claim": "CI 可复现 HTTP 契约联调",
        "forbidden_claim": "live_verified / 真模型 Live",
    },
    "L2": {
        "name": "Live RAG+Ollama",
        "proves": "真知识仓 HTTP + 模型路径；可 live_verified=true",
        "does_not_prove": "生产 ERP/WMS",
        "who_runs": "self-hosted / workflow_dispatch / 本机",
        "may_claim": "本机 Live 联调（须 live_verified=true）",
        "forbidden_claim": "把 L0/L1/快照说成 L2",
    },
    "artifacts": {
        "name": "Merged historical JSON",
        "proves": "历史产物可回读 schema",
        "does_not_prove": "当场联调",
        "who_runs": "build_joint_evidence_pack --from-artifacts",
        "may_claim": "仅历史摘要",
        "forbidden_claim": "当场 Live / L2",
    },
}


def normalize_tier(raw: Any) -> EvidenceTier | None:
    if raw is None:
        return None
    s = str(raw).strip().upper()
    if s in {"L0", "L1", "L2"}:
        return s  # type: ignore[return-value]
    if s in {"ARTIFACTS", "FROM_ARTIFACTS", "ARTIFACT"}:
        return "artifacts"
    return None


def tier_from_rag_health(health: dict[str, Any] | None) -> EvidenceTier:
    """根据 RAG /health 判定当场联调层级。"""
    body = health or {}
    explicit = normalize_tier(body.get("evidence_tier"))
    if explicit in {"L1", "L2"}:
        return explicit
    mode = str(body.get("mode") or body.get("provider") or "").lower()
    if mode in {"contract_stub", "rag_contract_stub", "fixture_http", "l1_stub"}:
        return "L1"
    # 真 RAG 健康体通常带 ollama/embedder 或 mode=live
    if body.get("consumer_contract_version_supported"):
        return "L2"
    return "L1"


def enforce_pack_tier_rules(pack: dict[str, Any]) -> dict[str, Any]:
    """写入/纠正证据包分层字段；禁止快照自称 L2。"""
    mode = str(pack.get("mode") or "")
    tier = normalize_tier(pack.get("evidence_tier"))

    if mode == "from_artifacts" or tier == "artifacts":
        pack["evidence_tier"] = "artifacts"
        pack["live_verified"] = False
        pack["portfolio_claimable"] = False
        pack.setdefault(
            "portfolio_warning",
            "artifacts_only：不得宣称 L2 / 当场 Live；请 --live（L2）或 run_l1_linkage（L1）",
        )
        return pack

    if tier is None:
        # 兼容旧包：有 live_verified 则推 L2，否则 L0 叙事
        if pack.get("live_verified"):
            pack["evidence_tier"] = "L2"
        elif mode == "live":
            pack["evidence_tier"] = "L2"
        else:
            pack["evidence_tier"] = "L0"
        tier = normalize_tier(pack.get("evidence_tier"))

    if tier == "L1":
        # L1 永不可 live_verified（该字段专指 L2 真模型联调）
        if pack.get("live_verified"):
            pack["live_verified"] = False
            pack["portfolio_warning"] = (
                (pack.get("portfolio_warning") or "")
                + " | L1 契约联调不得 live_verified；请看 l1_verified"
            ).strip(" |")
        pack.setdefault("l1_verified", bool(pack.get("l1_verified")))
        pack["portfolio_claimable"] = bool(pack.get("l1_verified"))
    elif tier == "L2":
        pack.setdefault("l1_verified", False)
    elif tier == "L0":
        pack["live_verified"] = False
        pack["l1_verified"] = False
        pack["portfolio_claimable"] = False

    pack["claim_matrix_ref"] = "app/eval/evidence_tier.py::CLAIM_MATRIX"
    return pack
