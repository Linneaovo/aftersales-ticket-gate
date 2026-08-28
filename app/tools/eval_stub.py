"""Eval/测试用 RAG stub — 薄封装，实现见 rag_stub_base。"""

from __future__ import annotations

from app.tools.rag_stub_base import RagStubClient, build_stub_ask_payload

EvalRagStub = RagStubClient

__all__ = ["EvalRagStub", "RagStubClient", "build_stub_ask_payload"]
