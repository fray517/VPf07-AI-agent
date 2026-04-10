"""Сборка LLM-агента LangChain (create_agent + инструменты)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .tools import build_tools

_DEFAULT_MODEL = "gpt-4o-mini"

_logger = logging.getLogger(__name__)


def load_env() -> None:
    """Загружает переменные из agent/.env (рядом с этим пакетом)."""
    env_path = Path(__file__).resolve().parent / ".env"
    existed = env_path.is_file()
    load_dotenv(env_path)
    _logger.info(
        "шаг: load_env путь=%s файл_есть=%s",
        env_path,
        existed,
    )


def _system_prompt() -> str:
    return (
        "Ты локальный AI-ассистент в терминале. Отвечай по-русски, "
        "структурировано и по делу.\n"
        "Инструменты:\n"
        "- web_search — факты, новости, общая информация из сети.\n"
        "- http_get — прямой GET к API по URL.\n"
        "- read_project_file / write_project_file — файлы только внутри "
        "корня проекта (относительный путь).\n"
        "- safe_terminal_exec — простые команды Windows cmd в корне проекта; "
        "без опасных конструкций.\n"
        "- get_weather — погода: city и period. "
        "period «сейчас» или «сегодня» — текущая; «завтра» — прогноз на завтра; "
        "«послезавтра» — на послезавтра. Один вызов достаточен — не повторяй "
        "тот же запрос.\n"
        "- crypto_price_tool — цена криптовалюты (coin: bitcoin, ethereum; "
        "currency: usd, eur, rub).\n"
        "- fiat_exchange_rate_tool — курс фиата: base_currency и "
        "quote_currency (EUR, USD, RUB): сколько quote за 1 base.\n"
        "Если задача неясна (нет города, валюты, пути), задай короткий "
        "уточняющий вопрос. Выбирай минимально достаточный инструмент."
    )


def build_chat_model() -> ChatOpenAI:
    """Создаёт ChatOpenAI из OPENAI_API_KEY."""
    load_env()
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        _logger.error("OPENAI_API_KEY не задан после load_env")
        raise RuntimeError(
            "Не задан OPENAI_API_KEY. Укажите ключ в agent/.env."
        )
    model = os.environ.get("OPENAI_MODEL", _DEFAULT_MODEL).strip()
    name = model or _DEFAULT_MODEL
    _logger.info(
        "шаг: ChatOpenAI model=%s (ключ задан, длина=%s)",
        name,
        len(key),
    )
    return ChatOpenAI(
        model=name,
        api_key=key,
        temperature=0.2,
    )


def build_agent_graph():
    """Возвращает скомпилированный граф агента (LangGraph)."""
    _logger.info("шаг: build_agent_graph начало")
    llm = build_chat_model()
    tools = build_tools()
    names = [getattr(t, "name", str(t)) for t in tools]
    _logger.info("шаг: инструменты подключены: %s", names)
    graph = create_agent(
        llm,
        tools,
        system_prompt=_system_prompt(),
        debug=False,
    )
    _logger.info("шаг: create_agent вернул граф типа %s", type(graph).__name__)
    return graph


def last_ai_text(messages: list) -> str:
    """Текст последнего ответа модели."""
    _logger.debug("last_ai_text: всего сообщений=%s", len(messages))
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            content = m.content
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                text = "".join(parts).strip()
                if text:
                    return text
    _logger.warning("last_ai_text: подходящий AIMessage не найден")
    return ""
