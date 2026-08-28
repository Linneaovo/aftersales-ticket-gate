from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import get_settings


def _playbooks_dir() -> Path:
    return Path(get_settings().playbooks_dir)


def load_playbook(playbook_id: str) -> dict[str, Any]:
    path = _playbooks_dir() / f"{playbook_id}.json"
    if not path.exists():
        raise FileNotFoundError(playbook_id)
    return json.loads(path.read_text(encoding="utf-8"))


def validate_playbook_by_id(
    playbook_id: str,
    out: dict[str, Any],
    *,
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = spec or load_playbook(playbook_id)
    from app.playbooks.runner import validate_playbook_result

    report = validate_playbook_result(data, out)
    report["playbook_id"] = playbook_id
    return report
