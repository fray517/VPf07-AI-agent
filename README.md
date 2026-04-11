# VPf07-AI-agent

Локальный AI-агент на **Python 3.10+**: понимает запросы на естественном языке, сам выбирает инструменты и может работать из **терминала** или через **Telegram-бота**. Модель — **OpenAI** (Chat Completions через `langchain-openai`), оркестрация — **LangChain** (`create_agent`, граф **LangGraph**).

## Возможности

- **Диалог** на русском с сохранением краткого контекста в `agent/memory.json` (отдельно для консоли и для каждого чата Telegram).
- **Инструменты агента:**
  - поиск в интернете (**DuckDuckGo**);
  - HTTP GET (**requests**);
  - чтение и запись файлов **только внутри корня репозитория**;
  - безопасное выполнение команд **cmd** в корне проекта (фильтр опасных шаблонов);
  - **погода** по городу (геокодинг Open-Meteo + прогноз; текущая погода и **завтра** / послезавтра);
  - **криптовалюты** (CoinGecko, без ключа);
  - **фиатные курсы** EUR / USD / RUB и др. ([open.er-api.com](https://open.er-api.com), без ключа);
  - **напоминания** в Telegram (дата `день-месяц`, время `ЧЧ:ММ`, год — текущий; фоновая отправка сообщения).
- **Логирование** в `agent/agent.log` и в stderr (уровень `LOG_LEVEL`).

## Стек

| Компонент | Назначение |
|-----------|------------|
| `openai`, `langchain`, `langchain-openai`, `langchain-core` | LLM и агент |
| `duckduckgo-search` | веб-поиск |
| `requests` | HTTP и внешние API |
| `python-dotenv` | переменные окружения |
| `pyTelegramBotAPI` (`telebot`) | Telegram |
| `tzdata` | часовые пояса для `zoneinfo` (рекомендуется на Windows) |

Полный список версий — в `requirements.txt`.

## Установка

```powershell
cd c:\Users\feden\My_Project\zerocoder\Vibe_Coder\VPf07-AI-agent
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Скопируйте `env.example` в **`agent/.env`** и заполните переменные (файл `.env` не коммитится; шаблон — в корне `env.example`).

Обязательно для работы агента:

- `OPENAI_API_KEY` — ключ OpenAI.

Для бота:

- `TELEGRAM_BOT_TOKEN` — токен от [@BotFather](https://t.me/BotFather).

Опционально:

- `OPENAI_MODEL` — например `gpt-4o-mini` (по умолчанию задано в примере);
- `LOG_LEVEL`, `LOG_FILE`;
- `AGENT_RECURSION_LIMIT` — лимит шагов графа (по умолчанию 12), защита от зацикливания по инструментам;
- `REMINDER_TIMEZONE` — IANA-имя пояса для напоминаний (например `Europe/Moscow`).

## Запуск

**Консоль:**

```powershell
python .\run.py
```

**Telegram-бот:**

```powershell
python .\run_bot.py
```

Бот должен быть запущен постоянно, пока нужны опрос и **напоминания** (фоновый поток раз в ~15 секунд проверяет `agent/reminders.json`).

## Структура проекта

```
VPf07-AI-agent/
  run.py                 # точка входа CLI
  run_bot.py             # точка входа Telegram
  requirements.txt
  env.example            # шаблон переменных (копия в agent/.env)
  agent/
    agent.py             # сборка LLM и графа агента
    tools.py             # инструменты LangChain
    dialog.py            # общий ход диалога (invoke, память)
    run.py               # интерактивный цикл CLI
    bot.py               # telebot: хендлеры и цикл напоминаний
    reminders.py         # напоминания и разбор даты/времени
    logging_setup.py     # настройка логов
    memory.json          # долговременные резюме диалогов
    reminders.json       # очередь напоминаний
    agent.log            # логи (ротация при настройке)
```

## Напоминания (Telegram)

Пользователь формулирует задачу свободно; агент вызывает инструмент с полями:

- текст задачи;
- время **`ЧЧ:ММ`**;
- дата **`день-месяц`** (разделитель `-`, `.` или `/`), **год — текущий** в выбранном `REMINDER_TIMEZONE`.

В консоли (`run.py`) создание напоминаний недоступно — инструмент сообщит, что нужен бот.

## Замечания по Windows

- Для имён зон вроде `Europe/Moscow` установите **`tzdata`** (`pip install tzdata` уже в `requirements.txt`). Без него возможен откат на UTC в логике напоминаний.
- Команды терминала в инструменте выполняются через **`cmd.exe /c`**.

## Лицензия

См. файл `LICENSE` в корне репозитория.
