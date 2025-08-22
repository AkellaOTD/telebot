# Pets Ads Admin Bot

Telegram бот для адміністрування груп/каналів з оголошеннями (домашні улюбленці).  
Стек: **Flask** (webhook/health), **aiogram 3.x**, **SQLite/PostgreSQL** (SQLAlchemy asyncio з `aiosqlite`/`asyncpg`).

## Швидкий старт (локально, polling)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # відредагуйте значення
python run_polling.py
```

## Запуск з webhook (за бажанням)
Налаштуйте домен/HTTPS, відредагуйте `.env` (`USE_WEBHOOK=true`), потім:
```bash
python run_webhook.py
```

## Структура
```
pets_ads_bot/
  app/
    __init__.py
    config.py
    database.py
    models.py
    repository.py
    services/
      __init__.py
      moderation.py
      posting.py
      spam.py
    utils/
      __init__.py
      phash.py
      text.py
      stats.py
  bot/
    __init__.py
    middlewares.py
    keyboards.py
    texts.py
    filters.py
    routers/
      __init__.py
      start.py
      add.py
      admin.py
      misc.py
  web/
    __init__.py
    flask_app.py
  run_polling.py
  run_webhook.py
  README.md
  requirements.txt
  .env.example
```

## База даних
- За замовчуванням `sqlite+aiosqlite:///./data/bot.db`
- Для PostgreSQL — `postgresql+asyncpg://...` (перемикається через `DATABASE_URL`)

## Ключові можливості
- `/start` з показом правил і згодою (одноразово)
- `/add` покрокове створення оголошення: категорія → район → заголовок (≤200) → опис (≤2000) → фото (≤20) → контакти (≤200)
- Перевірки: обовʼязкові поля, заборонені слова, дубль фото (`pHash`)
- Модерація в адмін-групі (approve/reject з причиною), сповіщення автору
- Автопостинг за розкладом (на канал/групу — свій інтервал/cron)
- Підтримка кількох груп/каналів + резервні канали
- FAQ, Contacts, Rules, Anti-flood, Blacklist, Spam-фільтр, Логи дій адмінів
- Статистика за день/тиждень/місяць

## Примітки
- Міграції через Alembic (за бажанням); стартова схема створюється автоматично.
- Файли зображень **не** зберігаються локально — зберігаються `file_id`, `pHash`.
- Більшість налаштувань — через `.env`.
