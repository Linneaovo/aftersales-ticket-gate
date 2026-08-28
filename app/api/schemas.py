from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RunCreateRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    knowledge_base: str = "demo-kb"
    history: list[dict[str, Any]] = Field(default_factory=list)
    api_key: str | None = None
    auto_submit: bool = False
    max_iterations: int | None = Field(default=None, ge=1, le=20)
    station: str | None = None
    second_visit: bool | None = None
    parts_hints: list[str] = Field(default_factory=list)
    sla_class: str | None = None


class HitlDecisionRequest(BaseModel):
    decision: Literal["approve", "reject", "edit"]
    note: str = ""
