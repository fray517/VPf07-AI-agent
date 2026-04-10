"""Общая логика хода диалога: агент, память, резюме."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphRecursionError

from agent.agent import last_ai_text
from agent.tools import append_memory_turn, load_memory_turns

_logger = logging.getLogger(__name__)


def recursion_limit() -> int:
    """Лимит шагов LangGraph из AGENT_RECURSION_LIMIT."""
    raw = os.environ.get("AGENT_RECURSION_LIMIT", "12").strip()
    try:
        n = int(raw)
    except ValueError:
        return 12
    return max(4, min(n, 200))


def memory_preamble(chat_id: str, max_items: int = 4) -> str:
    """Текст преамбулы из памяти для этого чата."""
    turns = load_memory_turns(chat_id)
    _logger.debug("память: chat_id=%s записей=%s", chat_id, len(turns))
    if not turns:
        return ""
    chunk = turns[-max_items:]
    lines = []
    for t in chunk:
        s = (t.get("summary") or "").strip()
        if s:
            lines.append(f"- {s}")
    if not lines:
        return ""
    preamble = (
        "[Контекст из прошлых диалогов]\n"
        + "\n".join(lines)
        + "\n[Текущий запрос ниже]\n"
    )
    _logger.info(
        "преамбула памяти: chat_id=%s строк=%s длина=%s",
        chat_id,
        len(lines),
        len(preamble),
    )
    return preamble


def summarize_turn(
    llm: ChatOpenAI,
    user_text: str,
    assistant_text: str,
) -> str:
    """Краткое резюме хода для памяти."""
    _logger.info(
        "шаг: резюме (user_len=%s answer_len=%s)",
        len(user_text),
        len(assistant_text),
    )
    t0 = time.perf_counter()
    msg = (
        f"Пользователь: {user_text}\n\n"
        f"Ассистент: {assistant_text}\n\n"
        "Дай одно короткое резюме (1–2 предложения) на русском."
    )
    out = llm.invoke(
        [
            SystemMessage(
                content="Ты помогаешь вести долговременную память диалога."
            ),
            HumanMessage(content=msg),
        ]
    )
    dt = time.perf_counter() - t0
    _logger.info("шаг: резюме готово за %.3f с", dt)
    content = getattr(out, "content", "")
    if isinstance(content, str):
        return content.strip()[:1200]
    return str(content)[:1200]


def run_turn(
    graph: Any,
    llm: ChatOpenAI,
    messages: list,
    raw: str,
    *,
    chat_id: str,
    turn_no: int = 0,
) -> tuple[str, list[Any], str | None]:
    """
    Один ход: invoke графа, память.

    Возвращает (ответ, нов_messages, ошибка_текст).
    Ошибка None при успехе.
    """
    _logger.info(
        "ход chat_id=%s #%s длина_запроса=%s",
        chat_id,
        turn_no,
        len(raw),
    )
    user_for_model = memory_preamble(chat_id) + raw
    messages.append(HumanMessage(content=user_for_model))
    _logger.info("до invoke: сообщений=%s", len(messages))

    try:
        t_inv = time.perf_counter()
        result = graph.invoke(
            {"messages": messages},
            {"recursion_limit": recursion_limit()},
        )
        _logger.info(
            "graph.invoke за %.3f с",
            time.perf_counter() - t_inv,
        )
    except GraphRecursionError as exc:
        _logger.warning("лимит шагов графа: %s", exc)
        if messages:
            messages.pop()
        return (
            "",
            messages,
            "Слишком много шагов агента. Уточните запрос или "
            "увеличьте AGENT_RECURSION_LIMIT.",
        )
    except Exception:
        _logger.exception("ошибка graph.invoke")
        if messages:
            messages.pop()
        return "", messages, "Ошибка агента (см. лог)."

    msgs = result.get("messages", [])
    messages = list(msgs)
    answer = last_ai_text(msgs)
    if not answer:
        _logger.warning("пустой ответ last_ai_text")
        answer = "Не удалось сформировать ответ."
    else:
        _logger.info("длина ответа=%s", len(answer))

    try:
        summary = summarize_turn(llm, raw, answer)
        append_memory_turn(raw, answer, summary, chat_id=chat_id)
        _logger.info("память записана для chat_id=%s", chat_id)
    except OSError as exc:
        _logger.exception("запись memory.json")
        _logger.warning("память не сохранена: %s", exc)

    return answer, messages, None
