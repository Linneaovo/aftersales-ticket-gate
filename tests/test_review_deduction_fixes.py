"""评审扣分修复验收：FakeRag 默认 offline、KnowledgePort、契约热路径。"""

from __future__ import annotations

from app.tools.demo_rag import DemoRagClient
from app.tools.knowledge_port import KnowledgePort
from app.tools.rag_factory import assert_knowledge_port, knowledge_port_of
from tests.test_core import FakeLiveRag, FakeRag


def test_fake_rag_defaults_offline_not_live():
    assert FakeRag().offline is True
    assert FakeLiveRag().offline is False
    assert knowledge_port_of(FakeRag()) == "fixture"
    assert knowledge_port_of(FakeLiveRag()) == "http"


def test_demo_rag_is_knowledge_port():
    client = DemoRagClient()
    assert assert_knowledge_port(client)
    assert isinstance(client, KnowledgePort) or assert_knowledge_port(client)


def test_rag_contract_ssot_in_tools():
    from app.tools import rag_contract
    from app.eval import rag_response_contract as eval_reexport

    # 热路径 SSOT 在 tools；eval 侧仅为兼容再导出
    assert rag_contract.CONTRACT_VERSION == eval_reexport.CONTRACT_VERSION
    assert callable(rag_contract.validate_ask_response)
    assert rag_contract.validate_ask_response is eval_reexport.validate_ask_response
