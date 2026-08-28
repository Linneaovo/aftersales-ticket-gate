from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings, get_settings


class RagToolError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RagClient:
    """enterprise-rag HTTP 客户端；只透传 X-API-Key，禁止本地提权。"""

    def __init__(self, settings: Settings | None = None, api_key: str | None = None) -> None:
        self.settings = settings or get_settings()
        self.api_key = api_key or self.settings.api_key
        self.base_url = self.settings.rag_base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        # 故意不传 X-Role，避免 UI 提权幻觉；角色由 RAG 按 Key 绑定
        return {"X-API-Key": self.api_key} if self.api_key else {}

    def _request(self, method: str, path: str, *, timeout: float, **kwargs: Any) -> Any:
        try:
            with httpx.Client(base_url=self.base_url, timeout=timeout) as client:
                resp = client.request(method, path, headers=self._headers(), **kwargs)
                if resp.status_code >= 400:
                    detail = resp.text
                    try:
                        payload = resp.json()
                        if isinstance(payload, dict) and payload.get("detail"):
                            detail = str(payload["detail"])
                    except Exception:
                        pass
                    raise RagToolError(detail, resp.status_code)
                if not resp.content:
                    return {}
                return resp.json()
        except httpx.ConnectError as exc:
            raise RagToolError(f"无法连接知识层 {self.base_url}，请先启动 enterprise-rag") from exc
        except httpx.TimeoutException as exc:
            raise RagToolError(f"知识层请求超时 ({timeout}s): {path}") from exc
        except httpx.HTTPError as exc:
            raise RagToolError(f"知识层 HTTP 错误: {exc}") from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health", timeout=10.0)

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
        return self._request(
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
        return self._request(
            "POST",
            "/work-orders/draft",
            timeout=self.settings.draft_timeout_s,
            json={
                "question": question,
                "knowledge_base": knowledge_base or self.settings.default_kb,
                "answer": answer,
                "role": role,
                "sources": sources or [],
            },
        )

    def submit_work_order(self, draft: dict[str, Any], note: str = "") -> dict[str, Any]:
        from app.tools.work_order_client import extract_draft_body

        body = extract_draft_body(draft)
        return self._request(
            "POST",
            "/work-orders/submit",
            timeout=self.settings.draft_timeout_s,
            json={"draft": body, "note": note},
        )

    def list_inbox(self, limit: int = 20) -> dict[str, Any]:
        return self._request(
            "GET",
            "/work-orders/inbox",
            timeout=15.0,
            params={"limit": limit},
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
    ) -> dict[str, Any]:
        kb = knowledge_base or self.settings.default_kb
        return self._request(
            "POST",
            f"/knowledge-bases/{kb}/feedback",
            timeout=30.0,
            json={
                "rating": rating,
                "query": query,
                "result": result,
                "comment": comment,
            },
        )

    def metrics(self, knowledge_base: str | None = None) -> dict[str, Any]:
        kb = knowledge_base or self.settings.default_kb
        return self._request("GET", f"/knowledge-bases/{kb}/metrics", timeout=15.0)


def summarize_rag_health(payload: dict[str, Any]) -> dict[str, Any]:
    """从 RAG /health 提取演示/联调可用摘要。"""
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
