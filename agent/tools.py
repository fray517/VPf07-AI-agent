"""Инструменты агента: поиск, HTTP, файлы, терминал, погода, крипта."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from duckduckgo_search import DDGS
from langchain_core.tools import tool

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_AGENT_DIR = Path(__file__).resolve().parent
_logger = logging.getLogger(__name__)
_MAX_HTTP_BYTES = 2_000_000
_MAX_FILE_BYTES = 2_000_000
_CMD_TIMEOUT_SEC = 45
_CMD_MAX_LEN = 800

_DANGEROUS_CMD_PATTERNS = re.compile(
    r"(?i)(\|\s*&|&&|\|\||`|\$\(|;\s*(rm|del|format|shutdown)|"
    r"invoke-expression|iex\b|wget\b.*\||curl\b.*\||"
    r">\s*[\\/](dev|proc)|mkfs|dd\s+if=|:\(\)\{)"
)

def _preview(text: str, max_len: int = 160) -> str:
    """Короткая строка для лога без перегрузки."""
    one = text.replace("\n", " ").strip()
    if len(one) <= max_len:
        return one
    return one[:max_len] + "…"


_COIN_ALIASES: dict[str, str] = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "bitcoin": "bitcoin",
    "ethereum": "ethereum",
    "doge": "dogecoin",
    "dogecoin": "dogecoin",
    "sol": "solana",
    "solana": "solana",
}


def _resolve_safe_path(relative_path: str) -> Path:
    """Путь только внутри корня проекта, без выхода через .."""
    cleaned = relative_path.strip().replace("\\", "/").lstrip("/")
    target = (_PROJECT_ROOT / cleaned).resolve()
    try:
        target.relative_to(_PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(
            "Путь вне каталога проекта запрещён."
        ) from exc
    return target


def _http_allowed(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


@tool
def web_search(query: str) -> str:
    """Ищет в интернете через DuckDuckGo. Аргумент: поисковая фраза."""
    q = query.strip()
    if not q:
        _logger.warning("web_search: пустой запрос")
        return "Пустой запрос."
    _logger.info("инструмент web_search: query=%r", _preview(q, 200))
    t0 = time.perf_counter()
    try:
        ddgs = DDGS()
        results = list(ddgs.text(q, max_results=8))
    except Exception as exc:
        _logger.exception("web_search: сбой DuckDuckGo")
        return f"Ошибка поиска: {exc}"
    dt = time.perf_counter() - t0
    if not results:
        _logger.info("web_search: пусто за %.3f с", dt)
        return "Ничего не найдено."
    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        href = r.get("href", "")
        body = r.get("body", "")
        lines.append(f"{i}. {title}\n   {href}\n   {body[:280]}")
    out = "\n\n".join(lines)
    _logger.info(
        "web_search: результатов=%s, длина_текста=%s, время=%.3f с",
        len(results),
        len(out),
        dt,
    )
    return out


@tool
def http_get(url: str) -> str:
    """GET-запрос по HTTP(S). Аргумент: полный URL."""
    u = url.strip()
    if not _http_allowed(u):
        _logger.warning("http_get: URL не разрешён: %r", _preview(u, 120))
        return "Разрешены только http/https с хостом."
    _logger.info("инструмент http_get: %r", _preview(u, 300))
    t0 = time.perf_counter()
    try:
        resp = requests.get(
            u,
            timeout=30,
            headers={"User-Agent": "VPf07-local-agent/1.0"},
        )
    except requests.RequestException as exc:
        _logger.exception("http_get: сбой сети")
        return f"Ошибка запроса: {exc}"
    dt = time.perf_counter() - t0
    _logger.info(
        "http_get: status=%s за %.3f с", resp.status_code, dt
    )
    body = resp.content[:_MAX_HTTP_BYTES]
    text = body.decode(resp.encoding or "utf-8", errors="replace")
    return (
        f"status={resp.status_code}\n"
        f"content-type={resp.headers.get('Content-Type', '')}\n\n"
        f"{text[:_MAX_HTTP_BYTES]}"
    )


@tool
def read_project_file(relative_path: str) -> str:
    """Читает текстовый файл внутри корня проекта. Путь относительный."""
    _logger.info("инструмент read_project_file: %r", relative_path)
    t0 = time.perf_counter()
    path = _resolve_safe_path(relative_path)
    if not path.is_file():
        _logger.warning("read_project_file: нет файла %s", path)
        return f"Файл не найден: {relative_path}"
    if path.stat().st_size > _MAX_FILE_BYTES:
        _logger.warning("read_project_file: слишком большой %s", path)
        return "Файл слишком большой."
    text = path.read_text(encoding="utf-8", errors="replace")
    _logger.info(
        "read_project_file: байт=%s за %.3f с",
        len(text.encode("utf-8")),
        time.perf_counter() - t0,
    )
    return text


@tool
def write_project_file(relative_path: str, content: str) -> str:
    """Записывает текст в файл внутри корня проекта (создаёт каталоги)."""
    data = content.encode("utf-8")
    _logger.info(
        "инструмент write_project_file: %r байт=%s",
        relative_path,
        len(data),
    )
    t0 = time.perf_counter()
    path = _resolve_safe_path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(data) > _MAX_FILE_BYTES:
        _logger.warning("write_project_file: превышен лимит размера")
        return "Слишком большой объём данных для записи."
    path.write_bytes(data)
    _logger.info(
        "write_project_file: записано за %.3f с",
        time.perf_counter() - t0,
    )
    return f"Записано: {path.relative_to(_PROJECT_ROOT)}"


@tool
def safe_terminal_exec(command: str) -> str:
    """Выполняет одну команду в cmd (Windows) в корне проекта. Осторожно."""
    cmd = command.strip()
    if not cmd or len(cmd) > _CMD_MAX_LEN:
        _logger.warning("safe_terminal_exec: отклонена длина/пусто")
        return "Команда пуста или слишком длинная."
    if _DANGEROUS_CMD_PATTERNS.search(cmd):
        _logger.warning(
            "safe_terminal_exec: отклонена по шаблону: %r",
            _preview(cmd, 80),
        )
        return "Команда отклонена по правилам безопасности."
    _logger.info(
        "инструмент safe_terminal_exec: %r",
        _preview(cmd, 400),
    )
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            ["cmd.exe", "/c", cmd],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_CMD_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        _logger.error("safe_terminal_exec: таймаут %s с", _CMD_TIMEOUT_SEC)
        return "Таймаут выполнения команды."
    except subprocess.SubprocessError as exc:
        _logger.exception("safe_terminal_exec: subprocess")
        return f"Ошибка subprocess: {exc}"
    _logger.info(
        "safe_terminal_exec: exit=%s за %.3f с",
        proc.returncode,
        time.perf_counter() - t0,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    parts = [f"exit={proc.returncode}"]
    if out:
        parts.append(out[:8000])
    if err:
        parts.append(f"stderr:\n{err[:4000]}")
    return "\n\n".join(parts) if len(parts) > 1 else parts[0]


_WEATHER_CODES: dict[int, str] = {
    0: "ясно",
    1: "преимущественно ясно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "изморозь",
    51: "морось слабая",
    61: "дождь слабый",
    80: "ливень",
    95: "гроза",
}


def _weather_label(code: Any) -> str:
    try:
        code_int = int(code) if code is not None else -1
    except (TypeError, ValueError):
        code_int = -1
    return _WEATHER_CODES.get(code_int, f"код погоды {code}")


def _normalize_weather_period(period: str) -> str:
    """current | tomorrow | day_after."""
    p = (period or "").strip().lower()
    if p in ("завтра", "tomorrow", "на завтра"):
        return "tomorrow"
    if p in ("послезавтра", "через день"):
        return "day_after"
    if p in (
        "",
        "сейчас",
        "сегодня",
        "today",
        "now",
        "current",
        "текущая",
    ):
        return "current"
    return "current"


def _geocode_city(city: str) -> tuple[float, float, str]:
    """Возвращает lat, lon, name через Open-Meteo Geocoding."""
    _logger.debug("geocode: запрос name=%r", city)
    t0 = time.perf_counter()
    r = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "ru"},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    _logger.debug("geocode: ответ за %.3f с", time.perf_counter() - t0)
    results = data.get("results") or []
    if not results:
        raise ValueError(f"Город не найден: {city}")
    first = results[0]
    lat = float(first["latitude"])
    lon = float(first["longitude"])
    name = first.get("name", city)
    return lat, lon, name


@tool
def get_weather(city: str, period: str = "сейчас") -> str:
    """Погода по городу (Open-Meteo). city — название.
    period: «сейчас»/«сегодня» — текущая погода; «завтра» — прогноз на завтра
    (макс/мин °C); «послезавтра» — на послезавтра."""
    city = city.strip()
    if not city:
        _logger.warning("get_weather: пустой город")
        return "Укажите город."
    kind = _normalize_weather_period(period)
    _logger.info(
        "инструмент get_weather: city=%r period=%r -> %s",
        city,
        period,
        kind,
    )
    t0 = time.perf_counter()
    try:
        lat, lon, label = _geocode_city(city)
    except (ValueError, requests.RequestException) as exc:
        _logger.warning("get_weather: геокодинг не удался: %s", exc)
        return f"Не удалось определить координаты: {exc}"

    if kind == "current":
        try:
            r = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current_weather": "true",
                },
                timeout=20,
            )
            r.raise_for_status()
            payload = r.json()
        except requests.RequestException:
            _logger.exception("get_weather: forecast API (current)")
            return "Ошибка API погоды."
        cw = payload.get("current_weather") or {}
        temp = cw.get("temperature")
        wind = cw.get("windspeed")
        code = cw.get("weathercode")
        cond = _weather_label(code)
        out = (
            f"Город: {label} ({lat:.4f}, {lon:.4f})\n"
            f"Сейчас: температура {temp} °C, ветер {wind} км/ч\n"
            f"Условия: {cond}"
        )
        _logger.info(
            "get_weather: текущая за %.3f с temp=%s",
            time.perf_counter() - t0,
            temp,
        )
        return out

    day_index = 1 if kind == "tomorrow" else 2
    day_word = "завтра" if kind == "tomorrow" else "послезавтра"
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "timezone": "auto",
                "forecast_days": 7,
                "daily": (
                    "weathercode,temperature_2m_max,"
                    "temperature_2m_min,windspeed_10m_max"
                ),
            },
            timeout=20,
        )
        r.raise_for_status()
        payload = r.json()
    except requests.RequestException:
        _logger.exception("get_weather: forecast API (daily)")
        return "Ошибка API прогноза."

    daily = payload.get("daily") or {}
    times: list = daily.get("time") or []
    if len(times) <= day_index:
        _logger.warning(
            "get_weather: мало дней в прогнозе len=%s",
            len(times),
        )
        return "Нет данных прогноза на выбранный день."

    wcodes = daily.get("weathercode") or []
    tmaxs = daily.get("temperature_2m_max") or []
    tmins = daily.get("temperature_2m_min") or []
    winds = daily.get("windspeed_10m_max") or []
    date_str = times[day_index]
    code = wcodes[day_index] if day_index < len(wcodes) else None
    tmax = tmaxs[day_index] if day_index < len(tmaxs) else None
    tmin = tmins[day_index] if day_index < len(tmins) else None
    wmax = winds[day_index] if day_index < len(winds) else None
    cond = _weather_label(code)
    out = (
        f"Город: {label} ({lat:.4f}, {lon:.4f})\n"
        f"Прогноз на {day_word} ({date_str}):\n"
        f"Температура: min {tmin} °C, max {tmax} °C\n"
        f"Ветер (макс. за день): {wmax} км/ч\n"
        f"Условия: {cond}"
    )
    _logger.info(
        "get_weather: daily %s за %.3f с",
        day_word,
        time.perf_counter() - t0,
    )
    return out


def get_crypto_price(coin: str, currency: str) -> float:
    """Цена криптовалюты через CoinGecko (ids + vs_currencies)."""
    key = coin.strip().lower()
    cur = currency.strip().lower()
    cid = _COIN_ALIASES.get(key, key.replace(" ", "-"))
    _logger.debug("get_crypto_price: ids=%s vs=%s", cid, cur)
    t0 = time.perf_counter()
    url = "https://api.coingecko.com/api/v3/simple/price"
    r = requests.get(
        url,
        params={"ids": cid, "vs_currencies": cur},
        timeout=20,
    )
    r.raise_for_status()
    data: dict[str, Any] = r.json()
    if cid not in data or cur not in data[cid]:
        raise ValueError(f"Нет данных для {coin} в {currency}.")
    price = float(data[cid][cur])
    _logger.debug(
        "get_crypto_price: цена=%s за %.3f с",
        price,
        time.perf_counter() - t0,
    )
    return price


@tool
def crypto_price_tool(coin: str, currency: str) -> str:
    """Курс криптовалюты. coin: bitcoin, ethereum; currency: usd, eur, rub."""
    _logger.info(
        "инструмент crypto_price_tool: coin=%r currency=%r",
        coin,
        currency,
    )
    try:
        price = get_crypto_price(coin, currency)
        out = f"{coin.strip()} / {currency.strip().upper()}: {price}"
        _logger.info("crypto_price_tool: ok")
        return out
    except ValueError as exc:
        _logger.warning("crypto_price_tool: %s", exc)
        return f"Ошибка курса: {exc}"
    except Exception:
        _logger.exception("crypto_price_tool: неожиданная ошибка")
        return "Ошибка курса: внутренняя ошибка (см. лог)."


def build_tools() -> list:
    """Список инструментов для агента."""
    _logger.debug("build_tools: сборка списка инструментов")
    return [
        web_search,
        http_get,
        read_project_file,
        write_project_file,
        safe_terminal_exec,
        get_weather,
        crypto_price_tool,
    ]


def memory_file_path() -> Path:
    """Путь к JSON-файлу долговременной памяти."""
    return _AGENT_DIR / "memory.json"


def load_memory_turns() -> list[dict[str, Any]]:
    """Загружает сохранённые реплики из memory.json."""
    path = memory_file_path()
    if not path.is_file():
        _logger.debug("load_memory_turns: файла нет %s", path)
        return []
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        _logger.warning("load_memory_turns: не прочитан %s", exc)
        return []
    turns = data.get("turns")
    if isinstance(turns, list):
        ok = [t for t in turns if isinstance(t, dict)]
        _logger.debug("load_memory_turns: записей=%s", len(ok))
        return ok
    return []


def append_memory_turn(
    user_text: str,
    assistant_text: str,
    summary: str,
) -> None:
    """Добавляет реплику и резюме в memory.json."""
    path = memory_file_path()
    _logger.info(
        "append_memory_turn: user_len=%s answer_len=%s summary_len=%s",
        len(user_text),
        len(assistant_text),
        len(summary),
    )
    turns = load_memory_turns()
    turns.append(
        {
            "user": user_text,
            "assistant": assistant_text,
            "summary": summary,
        }
    )
    payload = {"turns": turns[-200:]}
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _logger.debug("append_memory_turn: записано в %s", path)
