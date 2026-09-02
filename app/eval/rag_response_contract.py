"""兼容再导出：契约 SSOT 已迁至 app.tools.rag_contract（避免 tools→eval 热依赖）。"""

from app.tools.rag_contract import (  # noqa: F401
    CONTRACT_VERSION,
    assert_contract,
    read_last_contract_check_summary,
    validate_ask_response,
    validate_draft_response,
    validate_inbox_response,
    validate_submit_response,
    write_contract_check_summary,
)

__all__ = [
    "CONTRACT_VERSION",
    "assert_contract",
    "read_last_contract_check_summary",
    "validate_ask_response",
    "validate_draft_response",
    "validate_inbox_response",
    "validate_submit_response",
    "write_contract_check_summary",
]
