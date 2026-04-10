"""Telegram-бот: тот же агент, интерфейс через pyTelegramBotAPI (telebot)."""

from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import telebot

from agent.agent import build_agent_graph, build_chat_model, load_env
from agent.dialog import recursion_limit, run_turn
from agent.logging_setup import configure_logging

_logger = logging.getLogger(__name__)

_SESSIONS: dict[int, list] = {}
_LOCK = threading.Lock()
_MAX_MSG = 4096


def _chat_key(chat_id: int) -> str:
    return f"tg_{chat_id}"


def _send_long_reply(bot: telebot.TeleBot, message: telebot.types.Message, text: str) -> None:
    """Ответ с разбиением под лимит Telegram."""
    cid = message.chat.id
    if len(text) <= _MAX_MSG:
        bot.reply_to(message, text)
        return
    bot.reply_to(message, text[:_MAX_MSG])
    for i in range(_MAX_MSG, len(text), _MAX_MSG):
        bot.send_message(cid, text[i : i + _MAX_MSG])


def main() -> None:
    load_env()
    configure_logging()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        _logger.error("TELEGRAM_BOT_TOKEN не задан")
        print("Задайте TELEGRAM_BOT_TOKEN в agent/.env")
        sys.exit(1)

    _logger.info(
        "запуск Telegram-бота AGENT_RECURSION_LIMIT=%s",
        recursion_limit(),
    )
    graph = build_agent_graph()
    llm = build_chat_model()
    bot = telebot.TeleBot(token, parse_mode=None)

    @bot.message_handler(commands=["start", "help"])
    def cmd_help(message: telebot.types.Message) -> None:
        bot.reply_to(
            message,
            "Привет! Я локальный AI-агент. Пишите сообщениями — "
            "вопросы, задачи, погода, крипта и т.д.\n"
            "Команды: /start, /help",
        )

    @bot.message_handler(content_types=["text"])
    def on_text(message: telebot.types.Message) -> None:
        raw = (message.text or "").strip()
        if not raw:
            return
        chat_id = message.chat.id
        _logger.info(
            "входящее: chat_id=%s username=%s len=%s",
            chat_id,
            getattr(message.from_user, "username", None),
            len(raw),
        )
        try:
            bot.send_chat_action(chat_id, "typing")
        except Exception:
            _logger.debug("send_chat_action не удался", exc_info=True)

        with _LOCK:
            if chat_id not in _SESSIONS:
                _SESSIONS[chat_id] = []
            messages = _SESSIONS[chat_id]
            key = _chat_key(chat_id)
            try:
                answer, new_msgs, err = run_turn(
                    graph,
                    llm,
                    messages,
                    raw,
                    chat_id=key,
                    turn_no=0,
                )
            except Exception:
                _logger.exception("run_turn")
                bot.reply_to(
                    message,
                    "Внутренняя ошибка. Смотрите agent/agent.log.",
                )
                return
            _SESSIONS[chat_id] = new_msgs

        if err:
            bot.reply_to(message, err)
            return
        _send_long_reply(bot, message, answer)

    _logger.info("polling запущен")
    bot.infinity_polling(skip_pending=True, timeout=60)


if __name__ == "__main__":
    main()
