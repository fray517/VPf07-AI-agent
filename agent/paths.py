"""Каталог данных агента (память, напоминания, логи по умолчанию)."""

from __future__ import annotations

import os
from pathlib import Path

_PKG = Path(__file__).resolve().parent


def agent_data_dir() -> Path:
    """Путь к данным: по умолчанию каталог пакета agent/.

    В Docker задайте AGENT_DATA_DIR (например /app/agent/data) и смонтируйте
    том на этот путь, чтобы не терять память и напоминания.
    """
    custom = os.environ.get("AGENT_DATA_DIR", "").strip()
    if custom:
        p = Path(custom)
        p.mkdir(parents=True, exist_ok=True)
        return p
    return _PKG
