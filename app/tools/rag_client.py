from __future__ import annotations

import time
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.tools.circuit_breaker import circuit_allow, circuit_record_failure, circuit_record_success
from app.tools.http_pool import close_http_clients, get_http_client


class RagToolError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def close_rag_http_clients() -> None:
    """测试/进程退出时释放连接池。"""
    close_http_clients()


class RagClient:
    """enterprise-rag HTTP 客户端；只透传 X-API-Key，禁止本地提权。

    进程内复用 httpx 连接池；GET 瞬时错误重试；连续失败触发轻量熔断。
    """

    _RETRYABLE_STATUS = frozenset({502, 503, 504})
    _MAX_RETRIES = 2
    _CIRCUIT_THRESHOLD = 3
    _CIRCUIT_COOLDOWN_S = 15.0

    def __init__(self, settings: Settings | None = None, api_key: str | None = None) -> None:
        self.settings = settings or get_settings()
        self.api_key = api_key or self.settings.api_key
        self.base_url = self.settings.rag_base_url.rstrip("/")

    def _circuit_name(self) -> str:
        return f"rag:{self.base_url}"

    def _headers(self) -> dict[str, str]:
        # 故意不传 X-Role，避免 UI 提权幻觉；角色由 RAG 按 Key 绑定
        return {"X-API-Key": self.api_key} if self.api_key else {}

    def _request(self, method: str, path: str, *, timeout: float, **kwargs: Any) -> Any:
        cname = self._circuit_name()
        if not circuit_allow(cname, failure_threshold=self._CIRCUIT_THRESHOLD, cooldown_s=self._CIRCUIT_COOLDOWN_S):
            raise RagToolError(f"知识层熔断开路（连续失败），稍后重试: {self.base_url}", 503)

        client = get_http_client(self.base_url, self.api_key)
        extra_headers = kwargs.pop("headers", None) or {}
        headers = {**self._headers(), **extra_headers}
        last_exc: Exception | None = None
        attempts = self._MAX_RETRIES + 1 if method.upper() == "GET" else 1
        for attempt in range(attempts):
            try:
                resp = client.request(method, path, headers=headers, timeout=timeout, **kwargs)
                if resp.status_code >= 400:
                    if resp.status_code in self._RETRYABLE_STATUS and attempt < attempts - 1:
                        time.sleep(0.25 * (attempt + 1))
                        continue
                    detail = resp.text
                    try:
                        payload = resp.json()
                        if isinstance(payload, dict) and payload.get("detail"):
                            detail = str(payload["detail"])
                    except Exception:
                        pass
                    if resp.status_code in self._RETRYABLE_STATUS or resp.status_code >= 500:
                        circuit_record_failure(cname, failure_threshold=self._CIRCUIT_THRESHOLD)
                    raise RagToolError(detail, resp.status_code)
                if not resp.content:
                    circuit_record_success(cname)
                    return {}
                circuit_record_success(cname)
                return resp.json()
            except RagToolError:
                raise
            except httpx.ConnectError as exc:
                last_exc = exc
                if attempt < attempts - 1:
                    time.sleep(0.25 * (attempt + 1))
                    continue
                circuit_record_failure(cname, failure_threshold=self._CIRCUIT_THRESHOLD)
                raise RagToolError(f"无法连接知识层 {self.base_url}，请先启动 enterprise-rag") from exc
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt < attempts - 1:
                    time.sleep(0.25 * (attempt + 1))
                    continue
                circuit_record_failure(cname, failure_threshold=self._CIRCUIT_THRESHOLD)
                raise RagToolError(f"知识层请求超时 ({timeout}s): {path}") from exc
            except httpx.HTTPError as exc:
                circuit_record_failure(cname, failure_threshold=self._CIRCUIT_THRESHOLD)
                raise RagToolError(f"知识层 HTTP 错误: {exc}") from exc
        if last_exc:
            circuit_record_failure(cname, failure_threshold=self._CIRCUIT_THRESHOLD)
            raise RagToolError(f"知识层请求失败: {last_exc}") from last_exc
        raise RagToolError("知识层请求失败")

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health", timeout=10.0)

    def _contract_mode(self) -> str:
        mode = (self.settings.contract_validate or "strict").strip().lower()
        return mode if mode in {"strict", "warn", "off"} else "strict"

    def _apply_ask_contract(self, payload: Any) -> dict[str, Any]:
        from app.tools.rag_contract import validate_ask_response

        if not isinstance(payload, dict):
            return {
                "answer": "",
                "sources": [],
                "grounded": False,
                "contract_gate_incomplete": True,
                "_contract_errors": ["ask: payload must be object"],
            }
        if self._contract_mode() == "off":
            return payload
        errors = validate_ask_response(payload)
        if not errors:
            return payload
        out = dict(payload)
        out["_contract_errors"] = errors
        out["contract_gate_incomplete"] = True
        return out

    def _enforce_write_contract(self, kind: str, payload: Any) -> dict[str, Any]:
        from app.tools.rag_contract import (
            validate_draft_response,
            validate_submit_response,
        )

        mode = self._contract_mode()
        if mode == "off":
            return payload if isinstance(payload, dict) else {}
        if not isinstance(payload, dict):
            raise RagToolError(f"{kind} contract: payload must be object", 502)
        validators = {
            "draft": validate_draft_response,
            "submit": validate_submit_response,
        }
        errors = validators[kind](payload)
        if not errors:
            return payload
        msg = f"{kind} contract: " + "; ".join(errors)
        if mode == "warn":
            return payload
        raise RagToolError(msg, 502)

    def ask(
        self,
        question: str,
        *,
        knowledge_base: str | None = None,
        history: list[dict] | None = None,
        role: str | None = None,
    ) -> dict[str, Any]:
        kb = knowledge_base or self.settings.default_kb
        filters: dict[str, Any] = {}
        if role:
            filters["role"] = role
        payload = self._request(
            "POST",
            f"/knowledge-bases/{kb}/ask",
            timeout=self.settings.ask_timeout_s,
            json={
                "question": question,
                "history": history or [],
                "filters": filters,
                "parameters": {},
            },
        )
        return self._apply_ask_contract(payload)

    def retrieve(
        self,
        question: str,
        *,
        knowledge_base: str | None = None,
        history: list[dict] | None = None,
        role: str | None = None,
    ) -> dict[str, Any]:
        kb = knowledge_base or self.settings.default_kb
        filters: dict[str, Any] = {}
        if role:
            filters["role"] = role
        return self._request(
            "POST",
            f"/knowledge-bases/{kb}/retrieve",
            timeout=self.settings.retrieve_timeout_s,
            json={
                "question": question,
                "history": history or [],
                "filters": filters,
                "parameters": {},
            },
        )

    def draft_work_order(
        self,
        question: str,
        *,
        knowledge_base: str | None = None,
        answer: str = "",
        role: str = "technician",
        sources: list[dict] | None = None,
    ) -> dict[str, Any]:
        payload_json: dict[str, Any] = {
            "question": question,
            "knowledge_base": knowledge_base or self.settings.default_kb,
            "answer": answer,
            "role": role,
        }
        # RAG 默认禁止 inline sources；仅显式传入非空 sources 时才附带
        if sources:
            payload_json["sources"] = sources
        payload = self._request(
            "POST",
            "/work-orders/draft",
            timeout=self.settings.draft_timeout_s,
            json=payload_json,
        )
        return self._enforce_write_contract("draft", payload)

    def submit_work_order(
        self,
        draft: dict[str, Any],
        note: str = "",
        *,
        submitted_by: str = "copilot",
        run_id: str | None = None,
        decision_certificate_phase: str | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        from app.tools.work_order_client import extract_draft_body

        body = extract_draft_body(draft)
        payload: dict[str, Any] = {
            "draft": body,
            "note": note,
            "submitted_by": submitted_by,
        }
        if run_id:
            payload["run_id"] = run_id
        if decision_certificate_phase:
            payload["decision_certificate_phase"] = decision_certificate_phase
        if source:
            payload["source"] = source
        headers: dict[str, str] = {}
        token = (self.settings.copilot_submit_token or "").strip()
        # 业务路径带共享 token；探针不强制（RAG 开启硬门时仍放行 contract_probe）
        if token and (source or "copilot_hitl") != "contract_probe":
            headers["X-Copilot-Submit-Token"] = token
        resp = self._request(
            "POST",
            "/work-orders/submit",
            timeout=self.settings.draft_timeout_s,
            json=payload,
            headers=headers or None,
        )
        return self._enforce_write_contract("submit", resp)

    def list_inbox(
        self,
        limit: int = 20,
        *,
        lane: str = "all",
        source: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "lane": lane or "all"}
        if source:
            params["source"] = source
        return self._request(
            "GET",
            "/work-orders/inbox",
            timeout=15.0,
            params=params,
        )

    def get_ticket(self, ticket_id: str) -> dict[str, Any]:
        return self._request("GET", f"/work-orders/inbox/{ticket_id}", timeout=15.0)

    def submit_feedback(
        self,
        *,
        knowledge_base: str | None = None,
        rating: str,
        query: str,
        result: dict[str, Any],
        comment: str = "",
        run_id: str | None = None,
    ) -> dict[str, Any]:
        kb = knowledge_base or self.settings.default_kb
        body: dict[str, Any] = {
            "rating": rating,
            "query": query,
            "result": result,
            "comment": comment,
        }
        if run_id:
            body["run_id"] = run_id
        return self._request(
            "POST",
            f"/knowledge-bases/{kb}/feedback",
            timeout=30.0,
            json=body,
        )

    def list_feedback_by_run_id(
        self,
        run_id: str,
        *,
        knowledge_base: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """B6：按 run_id 回读 RAG feedback。"""
        kb = knowledge_base or self.settings.default_kb
        return self._request(
            "GET",
            f"/knowledge-bases/{kb}/feedback",
            timeout=15.0,
            params={"run_id": run_id, "limit": limit},
        )

    def metrics(self, knowledge_base: str | None = None) -> dict[str, Any]:
        kb = knowledge_base or self.settings.default_kb
        return self._request("GET", f"/knowledge-bases/{kb}/metrics", timeout=15.0)


def summarize_rag_health(payload: dict[str, Any]) -> dict[str, Any]:
    """从 RAG /health 提取联调可用摘要。"""
    status = payload.get("status") or "unknown"
    ollama = payload.get("ollama") or payload.get("checks", {}).get("ollama")
    embedder = payload.get("embedder") or payload.get("checks", {}).get("embedder")
    degraded = status not in {"ok", "healthy", "UP"}
    detail = {
        "status": status,
        "degraded": degraded,
        "ollama": ollama,
        "embedder": embedder,
        "demo_kb": payload.get("demo_kb") or payload.get("knowledge_base"),
    }
    return detail
