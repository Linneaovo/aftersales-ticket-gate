from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.policy.hitl_layers import (
    LAYER_CONFLICT,
    LAYER_DEGRADE,
    LAYER_INTENT,
    LAYER_LEDGER,
    LAYER_SHORTAGE,
    LAYER_SLA,
    LAYER_STATION,
    LAYER_WEATHER,
)

_VALID_CONFIRMATION_KEYS = frozenset(
    {
        LAYER_CONFLICT,
        LAYER_SHORTAGE,
        LAYER_SLA,
        LAYER_DEGRADE,
        LAYER_STATION,
        LAYER_LEDGER,
        LAYER_WEATHER,
        LAYER_INTENT,
    }
)


class RunCreateRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    knowledge_base: str = "demo-kb"
    history: list[dict[str, Any]] = Field(default_factory=list)
    api_key: str | None = None
    auto_submit: bool = False
    max_iterations: int | None = Field(default=None, ge=1, le=20)
    station: str | None = None
    second_visit: bool | None = None
    parts_hints: list[str] = Field(
        default_factory=list,
        description=(
            "可选强制配件 hint；默认忽略（ALLOW_DEMO_PARTS_HINTS=0）。"
            "主路径由 RAG draft.recommended_parts 驱动；playbook 回归可直调 state。"
        ),
    )
    sla_class: str | None = None
    parent_run_id: str | None = Field(
        default=None,
        description="退回补件后再开跑：传入原 run_id，将带入 return_note 与原问题上下文（不改原 draft）",
    )

class HitlDecisionRequest(BaseModel):
    # return = 退回补件终止（不改草稿字段）；edit 为历史别名，语义相同
    decision: Literal["approve", "reject", "return", "edit"]
    note: str = ""
    confirmations: dict[str, bool] = Field(
        default_factory=dict,
        description=(
            "分层人确勾选：conflict/shortage/sla/degrade/station/ledger/weather/intent。"
            "approve 时须覆盖 hitl.pending_layers，禁止一键放行业务门禁。"
        ),
    )

    @field_validator("confirmations")
    @classmethod
    def validate_confirmation_keys(cls, v: dict[str, bool]) -> dict[str, bool]:
        unknown = sorted(k for k in v if k not in _VALID_CONFIRMATION_KEYS)
        if unknown:
            raise ValueError(
                f"confirmations 含未知层: {unknown}; "
                f"合法 key: {sorted(_VALID_CONFIRMATION_KEYS)}"
            )
        return v

    @model_validator(mode="after")
    def validate_decision_note(self) -> HitlDecisionRequest:
        decision = self.normalized_decision()
        if decision in {"return", "reject"} and not (self.note or "").strip():
            raise ValueError(f"{decision} 必须填写非空 note")
        return self

    def normalized_decision(self) -> Literal["approve", "reject", "return"]:
        if self.decision == "edit":
            return "return"
        return self.decision  # type: ignore[return-value]
