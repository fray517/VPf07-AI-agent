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

from agent.agent import build_agent_graph, build_chat_model, load_env
from agent.dialog import recursion_limit, run_turn
from agent.logging_setup import configure_logging

_logger = logging.getLogger(__name__)

_CHAT_CLI = "cli"


def main() -> None:
    load_env()
    configure_logging()
    _logger.info("=== запуск CLI-агента ===")
    _logger.info(
        "LOG_LEVEL=%s LOG_FILE=%s AGENT_RECURSION_LIMIT=%s",
        os.environ.get("LOG_LEVEL", "INFO"),
        os.environ.get("LOG_FILE", "(по умолчанию agent/agent.log)"),
        recursion_limit(),
    )
    print("Локальный AI-агент (LangChain + OpenAI). Выход: exit или quit.\n")
    _logger.info("шаг: сборка графа агента")
    t_build = time.perf_counter()
    graph = build_agent_graph()
    _logger.info("шаг: граф собран за %.3f с", time.perf_counter() - t_build)
    llm = build_chat_model()
    messages: list = []
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
        try:
            answer, messages, err = run_turn(
                graph,
                llm,
                messages,
                raw,
                chat_id=_CHAT_CLI,
                turn_no=turn,
            )
        except KeyboardInterrupt:
            _logger.warning("прерывание во время graph.invoke (Ctrl+C)")
            print("\nПрервано (Ctrl+C). Запрос отменён.\n")
            if messages:
                messages.pop()
            continue

        if err:
            print(f"{err}\n")
            continue

        print(f"\nАгент> {answer}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("KeyboardInterrupt на верхнем уровне")
        print("\nВыход.")
        sys.exit(130)
