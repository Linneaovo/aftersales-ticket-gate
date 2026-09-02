"""本地演示「伪 WMS」HTTP 台账（学生可自起，非主机厂/经销商生产库）。

用法：
  python scripts/mock_parts_wms.py
  # 另开终端：.env 设 PARTS_LEDGER_URL=http://127.0.0.1:8011

契约：POST /parts/check  {"hints":[...], "machine_model":"SY215C?"}
返回字段对齐 app.tools.parts_ledger.HttpPartsLedger 期望。
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "data" / "parts_ledger.json"

app = FastAPI(title="Demo Parts WMS (student mock)", version="0.1.0")


class CheckBody(BaseModel):
    hints: list[str] = Field(default_factory=list)
    machine_model: str | None = None


def _load() -> dict:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "mode": "demo_mock_wms",
        "authority": "local_json_via_http",
        "is_production_wms": False,
        "ledger": str(LEDGER_PATH),
    }


@app.post("/parts/check")
def parts_check(body: CheckBody) -> dict:
    """委托本仓 JsonPartsLedger，再标记为 HTTP 源（演示 HttpPartsLedger 路径）。"""
    import sys

    sys.path.insert(0, str(ROOT))
    from app.tools.parts_ledger import JsonPartsLedger

    result = JsonPartsLedger(str(LEDGER_PATH)).check_parts(
        body.hints, machine_model=body.machine_model
    )
    result["source"] = "demo_mock_wms_http"
    result["ledger_kind"] = "http_mock"
    result["is_production_wms"] = False
    result["master_data_authority"] = "mock_parts_wms:8011"
    return result


if __name__ == "__main__":
    print("Demo mock WMS on http://127.0.0.1:8011  (NOT production)")
    print("Set PARTS_LEDGER_URL=http://127.0.0.1:8011 in Copilot .env")
    uvicorn.run(app, host="127.0.0.1", port=8011, log_level="info")
