"""Напоминания: хранение, разбор даты/времени, фоновая отправка в Telegram."""

from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_logger = logging.getLogger(__name__)

_AGENT_DIR = Path(__file__).resolve().parent
_FILE = _AGENT_DIR / "reminders.json"
_LOCK = threading.Lock()

_reminder_chat_ctx: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "reminder_chat",
    default=None,
)


def set_reminder_chat(chat_id: int | None) -> None:
    """Перед вызовом агента в Telegram передать chat_id; после — None."""
    _reminder_chat_ctx.set(chat_id)


def get_reminder_chat() -> int | None:
    """Текущий Telegram chat_id при обработке сообщения."""
    return _reminder_chat_ctx.get()


def _timezone() -> tzinfo:
    """IANA из REMINDER_TIMEZONE; без tzdata на Windows ZoneInfo может не найти зону."""
    name = os.environ.get("REMINDER_TIMEZONE", "Europe/Moscow").strip()
    try:
        return ZoneInfo(name)
    except Exception:
        _logger.warning(
            "REMINDER_TIMEZONE=%s недоступен (pip install tzdata?), "
            "используется UTC",
            name,
        )
        return timezone.utc


def _load_raw() -> dict[str, Any]:
    if not _FILE.is_file():
        return {"items": []}
    try:
        raw = _FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        _logger.warning("reminders: не прочитан файл %s", exc)
        return {"items": []}
    if not isinstance(data, dict):
        return {"items": []}
    items = data.get("items")
    if not isinstance(items, list):
        return {"items": []}
    return {"items": [x for x in items if isinstance(x, dict)]}


def _save_raw(data: dict[str, Any]) -> None:
    _FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_day_month(day_month: str) -> tuple[int, int]:
    """День и месяц из строки «число-месяц» (15-04, 15.04, 15/04)."""
    s = day_month.strip().replace(" ", "")
    for sep in ("-", ".", "/"):
        if sep in s:
            parts = s.split(sep)
            if len(parts) == 2:
                d, m = int(parts[0]), int(parts[1])
                if 1 <= d <= 31 and 1 <= m <= 12:
                    return d, m
    raise ValueError(
        "Дата в формате число-месяц, например 15-04 или 15.04."
    )


def parse_time_hm(time_hm: str) -> tuple[int, int]:
    """Часы и минуты из «ЧЧ:ММ»."""
    s = time_hm.strip()
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if not m:
        raise ValueError("Время в формате ЧЧ:ММ, например 14:30.")
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        raise ValueError("Недопустимое время.")
    return h, mi


def build_fire_datetime(day_month: str, time_hm: str) -> datetime:
    """Дата и время напоминания; год — текущий в выбранном часовом поясе."""
    tz = _timezone()
    day, month = parse_day_month(day_month)
    h, mi = parse_time_hm(time_hm)
    year = datetime.now(tz).year
    try:
        return datetime(year, month, day, h, mi, tzinfo=tz)
    except ValueError as exc:
        raise ValueError(
            "Некорректная дата или день не существует в этом месяце."
        ) from exc


def add_reminder(task: str, fire_at: datetime, chat_id: int) -> str:
    """Добавляет напоминание, возвращает id."""
    rid = str(uuid.uuid4())
    item = {
        "id": rid,
        "chat_id": chat_id,
        "task": task.strip()[:2000],
        "fire_at": fire_at.isoformat(),
    }
    with _LOCK:
        data = _load_raw()
        items: list = data["items"]
        items.append(item)
        if len(items) > 500:
            items[:] = items[-500:]
        _save_raw(data)
    _logger.info("напоминание id=%s chat_id=%s", rid, chat_id)
    return rid


def pop_due_reminders(now: datetime) -> list[dict[str, Any]]:
    """Забирает и удаляет из файла все напоминания с fire_at <= now."""
    due: list[dict[str, Any]] = []
    with _LOCK:
        data = _load_raw()
        items: list = data["items"]
        keep: list = []
        for it in items:
            try:
                raw = it.get("fire_at", "")
                fire = datetime.fromisoformat(raw)
                if fire.tzinfo is None:
                    fire = fire.replace(tzinfo=now.tzinfo)
            except (TypeError, ValueError):
                _logger.warning("напоминание с битой датой: %s", it)
                continue
            if fire <= now:
                due.append(it)
            else:
                keep.append(it)
        data["items"] = keep
        _save_raw(data)
    return due


def now_in_reminder_tz() -> datetime:
    """Текущий момент в часовом поясе напоминаний."""
    return datetime.now(_timezone())


def format_reminder_confirmation(fire_at: datetime, task: str) -> str:
    """Текст подтверждения для пользователя."""
    return (
        f"Напоминание создано: «{task}» в "
        f"{fire_at.strftime('%d.%m.%Y %H:%M')} "
        f"({fire_at.tzinfo})."
    )
