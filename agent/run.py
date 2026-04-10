"""CLI: интерактивный запуск локального агента."""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agent.agent import (
    build_agent_graph,
    build_chat_model,
    last_ai_text,
    load_env,
)
from langgraph.errors import GraphRecursionError

from agent.logging_setup import configure_logging
from agent.tools import append_memory_turn, load_memory_turns

_logger = logging.getLogger(__name__)


def _recursion_limit() -> int:
    raw = os.environ.get("AGENT_RECURSION_LIMIT", "12").strip()
    try:
        n = int(raw)
    except ValueError:
        return 12
    return max(4, min(n, 200))


def _memory_preamble(max_items: int = 4) -> str:
    turns = load_memory_turns()
    _logger.debug("память: загружено записей turns=%s", len(turns))
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
        "преамбула памяти: строк=%s, длина=%s",
        len(lines),
        len(preamble),
    )
    return preamble


def _summarize_turn(
    llm: ChatOpenAI,
    user_text: str,
    assistant_text: str,
) -> str:
    _logger.info(
        "шаг: резюме диалога (user_len=%s, answer_len=%s)",
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


def main() -> None:
    load_env()
    configure_logging()
    _logger.info("=== запуск CLI-агента ===")
    _logger.info(
        "LOG_LEVEL=%s LOG_FILE=%s AGENT_RECURSION_LIMIT=%s",
        os.environ.get("LOG_LEVEL", "INFO"),
        os.environ.get("LOG_FILE", "(по умолчанию agent/agent.log)"),
        _recursion_limit(),
    )
    print("Локальный AI-агент (LangChain + OpenAI). Выход: exit или quit.\n")
    _logger.info("шаг: сборка графа агента")
    t_build = time.perf_counter()
    graph = build_agent_graph()
    _logger.info("шаг: граф собран за %.3f с", time.perf_counter() - t_build)
    llm = build_chat_model()
    messages = []
    turn = 0

    while True:
        try:
            raw = input("Вы> ").strip()
        except (EOFError, KeyboardInterrupt):
            _logger.info("ввод прерван (EOF/Ctrl+C), выход")
            print("\nВыход.")
            break
        low = raw.lower()
        if low in ("exit", "quit", "выход"):
            _logger.info("команда выхода от пользователя")
            print("Выход.")
            break
        if not raw:
            continue

        turn += 1
        _logger.info(
            "=== ход %s: длина запроса=%s символов ===",
            turn,
            len(raw),
        )
        user_for_model = _memory_preamble() + raw
        _logger.debug(
            "сообщение в модель: длина=%s (с преамбулой)",
            len(user_for_model),
        )
        messages.append(HumanMessage(content=user_for_model))
        _logger.info(
            "до invoke: сообщений в состоянии=%s",
            len(messages),
        )

        try:
            t_inv = time.perf_counter()
            result = graph.invoke(
                {"messages": messages},
                {"recursion_limit": _recursion_limit()},
            )
            _logger.info(
                "шаг: graph.invoke завершён за %.3f с",
                time.perf_counter() - t_inv,
            )
        except GraphRecursionError as exc:
            _logger.warning("лимит шагов графа: %s", exc)
            print(
                "Слишком много шагов агента (цикл по инструментам). "
                "Увеличьте AGENT_RECURSION_LIMIT в .env или уточните запрос.\n"
            )
            if messages:
                messages.pop()
            continue
        except KeyboardInterrupt:
            _logger.warning(
                "прерывание во время graph.invoke (Ctrl+C)"
            )
            # Ctrl+C во время ответа или инструмента (часто в пуле потоков).
            print("\nПрервано (Ctrl+C). Запрос отменён.\n")
            if messages:
                messages.pop()
            continue
        except Exception:
            _logger.exception("ошибка graph.invoke")
            print("Ошибка агента (подробности в логе).\n")
            if messages:
                messages.pop()
            continue

        msgs = result.get("messages", [])
        messages = list(msgs)
        _logger.info(
            "после invoke: сообщений=%s",
            len(messages),
        )
        answer = last_ai_text(msgs)
        if not answer:
            _logger.warning("пустой ответ last_ai_text, сообщений=%s", len(msgs))
            answer = "Не удалось сформировать ответ."
        else:
            _logger.info("длина ответа агента=%s символов", len(answer))
        print(f"\nАгент> {answer}\n")

        try:
            summary = _summarize_turn(llm, raw, answer)
            append_memory_turn(raw, answer, summary)
            _logger.info(
                "память: запись хода %s в memory.json выполнена",
                turn,
            )
        except KeyboardInterrupt:
            _logger.warning("прерывание при сохранении памяти")
            print("\nПрервано при сохранении памяти. Ответ уже показан.\n")
        except OSError as exc:
            _logger.exception("ошибка записи memory.json")
            print(f"(Память не сохранена: {exc})\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("KeyboardInterrupt на верхнем уровне")
        print("\nВыход.")
        sys.exit(130)
