
from __future__ import annotations
import asyncio
import aiosqlite
import hashlib
import io
import json
import os
import re
import textwrap
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from PIL import Image
from dotenv import load_dotenv
from telegram import Bot, ParseMode
from telegram.constants import ParseMode  # if needed
from telegram.bot import DefaultBotProperties

# =========================
# Конфіг
# =========================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
BLACKLIST_CHANNEL_ID = int(os.getenv("BLACKLIST_CHANNEL_ID", "0"))
DEFAULT_POST_INTERVAL_MIN = int(os.getenv("DEFAULT_POST_INTERVAL_MIN", "10"))
ANTIFLOOD_SECONDS = int(os.getenv("ANTIFLOOD_SECONDS", "3"))
TIMEZONE = os.getenv("TIMEZONE", "Europe/Kyiv")

POST_TARGET_IDS = [
    int(x.strip()) for x in os.getenv("POST_TARGET_IDS", "").split(",") if x.strip()
]
BACKUP_CHANNEL_IDS = [
    int(x.strip()) for x in os.getenv("BACKUP_CHANNEL_IDS", "").split(",") if x.strip()
]
CITY_DISTRICTS = [x.strip() for x in os.getenv(
    "CITY_DISTRICTS", "").split(",") if x.strip()]
BAD_WORDS = [x.strip().lower()
             for x in os.getenv("BAD_WORDS", "").split(",") if x.strip()]

if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN is not set in .env")

# =========================
# Утиліти
# =========================


def now_tz() -> datetime:
    # Без зовнішніх залежностей: використовуємо локальний UTC, зсув не критичний
    return datetime.now(timezone.utc)


async def anti_flood(user_id: int, db: aiosqlite.Connection) -> bool:
    """Повертає True, якщо треба загальмувати (занадто часто)."""
    async with db.execute(
        "SELECT last_action_at FROM antiflood WHERE user_id=?", (user_id,)
    ) as cur:
        row = await cur.fetchone()
    ts = int(now_tz().timestamp())
    if row:
        last_ts = row[0]
        if ts - last_ts < ANTIFLOOD_SECONDS:
            await db.execute(
                "UPDATE antiflood SET last_action_at=? WHERE user_id=?", (
                    ts, user_id)
            )
            await db.commit()
            return True
        await db.execute(
            "UPDATE antiflood SET last_action_at=? WHERE user_id=?", (
                ts, user_id)
        )
        await db.commit()
        return False
    else:
        await db.execute(
            "INSERT INTO antiflood(user_id, last_action_at) VALUES(?, ?)", (user_id, ts)
        )
        await db.commit()
        return False

# Перцептивний хеш (dHash) для виявлення дублів фото


def dhash_image_bytes(content: bytes, size: int = 8) -> str:
    with Image.open(io.BytesIO(content)) as img:
        img = img.convert("L").resize((size + 1, size), Image.LANCZOS)
        diff = []
        for y in range(size):
            for x in range(size):
                diff.append(img.getpixel((x, y)) > img.getpixel((x + 1, y)))
        # перетворюємо у hex
        val = 0
        for i, v in enumerate(diff):
            if v:
                val |= 1 << i
        return f"{val:0{size*size//4}x}"

# =========================
# БД (SQLite)
# =========================


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    agreed_rules INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS antiflood (
    user_id INTEGER PRIMARY KEY,
    last_action_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS bad_words (
    word TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS blacklist (
    user_id INTEGER PRIMARY KEY,
    reason TEXT,
    added_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    district TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    contacts TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    status TEXT NOT NULL, -- draft|queued|approved|rejected|published
    reject_reason TEXT,
    photos_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS post_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL,
    file_id TEXT NOT NULL,
    file_unique_id TEXT NOT NULL,
    phash TEXT,
    FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    interval_min INTEGER NOT NULL,
    next_run_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    post_id INTEGER,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS moderation_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL UNIQUE,
    queued_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_status_created ON posts(status, created_at);
"""


async def init_db(db: aiosqlite.Connection):
    await db.executescript(SCHEMA_SQL)
    # Ініціалізувати заборонені слова з .env
    for w in BAD_WORDS:
        try:
            await db.execute("INSERT OR IGNORE INTO bad_words(word) VALUES (?)", (w,))
        except Exception:
            pass
    await db.commit()

# =========================
# Стан машини / FSM для /add
# =========================


class AddPost(StatesGroup):
    waiting_category = State()
    waiting_district = State()
    waiting_title = State()
    waiting_description = State()
    waiting_photos = State()
    waiting_contacts = State()


CATEGORIES = [
    "Віддам тварину",
    "Продам тварину",
    "Знайдена тварина",
    "Загублена тварина",
    "Потрібна допомога",
]

# =========================
# Розмітки клавіатур
# =========================


def kb_agree_rules() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Погоджуюсь ✅", callback_data="rules:agree")
    kb.button(text="Не згоден ❌", callback_data="rules:decline")
    return kb.as_markup()


def kb_categories() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for c in CATEGORIES:
        kb.button(text=c, callback_data=f"cat:{c}")
    kb.adjust(1)
    return kb.as_markup()


def kb_districts() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for d in CITY_DISTRICTS or ["Інгулецький", "Саксаганський", "Центрально-Міський"]:
        kb.button(text=d, callback_data=f"dist:{d}")
    kb.adjust(2)
    return kb.as_markup()


def kb_moderation(post_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Схвалити", callback_data=f"mod:approve:{post_id}")
    kb.button(text="❌ Відхилити", callback_data=f"mod:reject:{post_id}")
    kb.button(text="⛔ Бан користувача", callback_data=f"mod:ban:{post_id}")
    kb.adjust(2)
    return kb.as_markup()


def kb_admin() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Черга", callback_data="admin:queue")
    kb.button(text="Статистика", callback_data="admin:stats")
    kb.button(text="Список каналів", callback_data="admin:targets")
    kb.button(text="Фільтри", callback_data="admin:filters")
    kb.adjust(2)
    return kb.as_markup()

# =========================
# Тексти/шаблони
# =========================


RULES_TEXT = (
    """<b>Правила подання оголошень</b>\n\n"
    "• Оголошення лише за тематикою домашніх улюбленців.\n"
    "• Заборонені слова й спам буде видалено.\n"
    "• До 20 фото. Обовʼязково додайте контакти.\n\n"
    "Натискаючи <i>Погоджуюсь</i>, ви підтверджуєте дотримання правил."""
)

FAQ_TEXT = (
    "<b>FAQ</b>\n\n1) Як подати оголошення? – Використайте команду /add.\n"
    "2) Коли воно зʼявиться? – Після модерації, зазвичай до 24 год.\n"
    "3) Скільки коштує? – Розміщення безкоштовне."
)

CONTACTS_TEXT = (
    "<b>Контакти</b>\n\nАдміністрація: звертайтесь у приват або пишіть у групі модерації."
)

RULES_SHORT = "Натисніть /add щоб створити оголошення."


def format_post_text(row: dict) -> str:
    tags = []
    if row.get("category"):
        tags.append(f"#{row['category'].split()[0]}")
    if row.get("district"):
        tags.append(f"#{row['district'].replace('-', '')}")
    tags_line = " ".join(tags)
    return textwrap.dedent(
        f"""
        <b>{row['title']}</b>

        {row['description']}

        <b>Район:</b> {row['district']}
        <b>Категорія:</b> {row['category']}
        <b>Контакти:</b> {row['contacts']}

        {tags_line}
        """
    ).strip()

# =========================
# Бот/Диспетчер
# =========================

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# Пул зʼєднання з БД (простий варіант: одне зʼєднання на процес)
DB_PATH = os.getenv("DATABASE_PATH", "bot.db")
_db_conn: Optional[aiosqlite.Connection] = None


async def get_db() -> aiosqlite.Connection:
    global _db_conn
    if _db_conn is None:
        _db_conn = await aiosqlite.connect(DB_PATH)
        await init_db(_db_conn)
    return _db_conn

# =========================
# Перевірки/фільтри
# =========================


async def contains_bad_words(text: str, db: aiosqlite.Connection) -> bool:
    t = text.lower()
    words = []
    async with db.execute("SELECT word FROM bad_words") as cur:
        async for (w,) in cur:
            words.append(w)
    for w in words:
        if w and w in t:
            return True
    return False


async def is_blacklisted(user_id: int, db: aiosqlite.Connection) -> bool:
    async with db.execute("SELECT 1 FROM blacklist WHERE user_id=?", (user_id,)) as cur:
        row = await cur.fetchone()
    return bool(row)

# =========================
# Команди користувача
# =========================


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    db = await get_db()
    if await anti_flood(message.from_user.id, db):
        return
    if await is_blacklisted(message.from_user.id, db):
        await message.answer("Ви у чорному списку. Зверніться до адміністрації.")
        return
    # Перевірити чи юзер вже погодився з правилами
    async with db.execute(
        "SELECT agreed_rules FROM users WHERE user_id=?", (
            message.from_user.id,)
    ) as cur:
        row = await cur.fetchone()
    if not row:
        await db.execute(
            "INSERT INTO users(user_id, agreed_rules, created_at) VALUES(?,?,?)",
            (message.from_user.id, 0, int(now_tz().timestamp())),
        )
        await db.commit()
        await message.answer(RULES_TEXT, reply_markup=kb_agree_rules())
        return
    agreed = row[0] == 1
    if not agreed:
        await message.answer(RULES_TEXT, reply_markup=kb_agree_rules())
        return
    await message.answer("Вітаю! " + RULES_SHORT)


@dp.callback_query(F.data.startswith("rules:"))
async def cb_rules(call: CallbackQuery):
    db = await get_db()
    cmd = call.data.split(":")[1]
    if cmd == "agree":
        await db.execute(
            "UPDATE users SET agreed_rules=1 WHERE user_id=?", (
                call.from_user.id,)
        )
        await db.commit()
        await call.message.edit_text("Дякую! Тепер можна створити оголошення: /add")
    else:
        await call.message.edit_text("Шкода. До зустрічі!")
        try:
            await bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
    await call.answer()


@dp.message(Command("faq"))
async def cmd_faq(message: Message):
    await message.answer(FAQ_TEXT)


@dp.message(Command("contacts"))
async def cmd_contacts(message: Message):
    await message.answer(CONTACTS_TEXT)


@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    await message.answer(RULES_TEXT)


@dp.message(Command("my_posts"))
async def cmd_my_posts(message: Message):
    db = await get_db()
    async with db.execute(
        "SELECT id, status, created_at, title FROM posts WHERE author_id=? ORDER BY id DESC LIMIT 10",
        (message.from_user.id,),
    ) as cur:
        rows = await cur.fetchall()
    if not rows:
        await message.answer("У вас ще немає оголошень. Натисніть /add")
        return
    lines = [
        f"#{r[0]} — {r[1]} — {datetime.fromtimestamp(r[2]).strftime('%Y-%m-%d %H:%M')} — {r[3][:30]}"
        for r in rows
    ]
    await message.answer("Ваші останні оголошення:\n" + "\n".join(lines))

# ==== /add


@dp.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    db = await get_db()
    if await anti_flood(message.from_user.id, db):
        return
    if await is_blacklisted(message.from_user.id, db):
        await message.answer("Ви у чорному списку. Зверніться до адміністрації.")
        return
    # перевірити згоду з правилами
    async with db.execute(
        "SELECT agreed_rules FROM users WHERE user_id=?", (
            message.from_user.id,)
    ) as cur:
        row = await cur.fetchone()
    if not row or row[0] != 1:
        await message.answer("Спершу потрібно погодитись із правилами: /start")
        return
    await state.set_state(AddPost.waiting_category)
    await state.update_data(
        post={
            "category": None,
            "district": None,
            "title": None,
            "description": None,
            "contacts": None,
            "photos": [],
        }
    )
    await message.answer("Оберіть категорію оголошення:", reply_markup=kb_categories())


@dp.callback_query(AddPost.waiting_category, F.data.startswith("cat:"))
async def choose_category(call: CallbackQuery, state: FSMContext):
    cat = call.data.split(":", 1)[1]
    data = await state.get_data()
    data["post"]["category"] = cat
    await state.update_data(**data)
    await state.set_state(AddPost.waiting_district)
    await call.message.edit_text("Оберіть район:", reply_markup=kb_districts())
    await call.answer()


@dp.callback_query(AddPost.waiting_district, F.data.startswith("dist:"))
async def choose_district(call: CallbackQuery, state: FSMContext):
    dist = call.data.split(":", 1)[1]
    data = await state.get_data()
    data["post"]["district"] = dist
    await state.update_data(**data)
    await state.set_state(AddPost.waiting_title)
    await call.message.edit_text("Введіть заголовок (до 200 символів):")
    await call.answer()


@dp.message(AddPost.waiting_title)
async def add_title(message: Message, state: FSMContext):
    title = message.text.strip() if message.text else ""
    if not title or len(title) > 200:
        await message.answer("Введіть текст до 200 символів.")
        return
    db = await get_db()
    if await contains_bad_words(title, db):
        await message.answer("У заголовку виявлено заборонені слова. Спробуйте інакше.")
        return
    data = await state.get_data()
    data["post"]["title"] = title
    await state.update_data(**data)
    await state.set_state(AddPost.waiting_description)
    await message.answer("Опишіть оголошення (до 2000 символів):")


@dp.message(AddPost.waiting_description)
async def add_description(message: Message, state: FSMContext):
    desc = message.text.strip() if message.text else ""
    if not desc or len(desc) > 2000:
        await message.answer("Введіть опис до 2000 символів.")
        return
    db = await get_db()
    if await contains_bad_words(desc, db):
        await message.answer("В описі виявлено заборонені слова. Спробуйте інакше.")
        return
    data = await state.get_data()
    data["post"]["description"] = desc
    await state.update_data(**data)
    await state.set_state(AddPost.waiting_photos)
    await message.answer("Надішліть 1–20 фото. Коли завершите — напишіть слово <b>ГОТОВО</b>.")


@dp.message(AddPost.waiting_photos, F.photo)
async def add_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    photos = data["post"]["photos"]
    if len(photos) >= 20:
        await message.answer("Додано максимум 20 фото. Напишіть \"ГОТОВО\" для продовження.")
        return
    # Вибираємо найякісніше фото з групи
    tg_photo = message.photo[-1]
    file = await bot.get_file(tg_photo.file_id)
    file_bytes = await bot.download_file(file.file_path)
    content = file_bytes.read()
    phash = dhash_image_bytes(content)
    # анти-дубль: перевірити вже додані
    if any(p["phash"] == phash for p in photos if p.get("phash")):
        await message.answer("Схоже, це дубль фото — пропускаю.")
        return
    photos.append({"file_id": tg_photo.file_id,
                   "unique_id": tg_photo.file_unique_id, "phash": phash})
    data["post"]["photos"] = photos
    await state.update_data(**data)
    await message.answer(f"Фото додано ({len(photos)}/20). Надсилайте ще або напишіть \"ГОТОВО\".")


@dp.message(AddPost.waiting_photos)
async def photos_done_or_text(message: Message, state: FSMContext):
    if (message.text or "").strip().upper() != "ГОТОВО":
        await message.answer("Надішліть фото або напишіть \"ГОТОВО\" для продовження.")
        return
    data = await state.get_data()
    if len(data["post"]["photos"]) == 0:
        await message.answer("Додайте хоча б одне фото.")
        return
    await state.set_state(AddPost.waiting_contacts)
    await message.answer("Додайте контакти (до 200 символів):")


@dp.message(AddPost.waiting_contacts)
async def add_contacts(message: Message, state: FSMContext):
    contacts = message.text.strip() if message.text else ""
    if not contacts or len(contacts) > 200:
        await message.answer("Введіть контакти до 200 символів.")
        return
    db = await get_db()
    if await contains_bad_words(contacts, db):
        await message.answer("У контактах виявлено заборонені слова. Спробуйте інакше.")
        return

    data = await state.get_data()
    post = data["post"]

    # Зберігаємо пост у БД як draft -> queued + у чергу модерації
    ts = int(now_tz().timestamp())
    async with db.execute(
        """
        INSERT INTO posts(author_id, category, district, title, description, contacts, created_at, status, photos_count)
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            message.from_user.id,
            post["category"],
            post["district"],
            post["title"],
            post["description"],
            contacts,
            ts,
            "queued",
            len(post["photos"]),
        ),
    ) as cur:
        await db.commit()
        post_id = cur.lastrowid

    for p in post["photos"]:
        await db.execute(
            "INSERT INTO post_photos(post_id, file_id, file_unique_id, phash) VALUES(?,?,?,?)",
            (post_id, p["file_id"], p["unique_id"], p.get("phash")),
        )
    await db.execute(
        "INSERT OR IGNORE INTO moderation_queue(post_id, queued_at) VALUES(?, ?)",
        (post_id, ts),
    )
    await db.commit()

    await state.clear()

    # Відправляємо у адмін-групу картку для модерації
    text = format_post_text({
        "title": post["title"],
        "description": post["description"],
        "district": post["district"],
        "category": post["category"],
        "contacts": contacts,
    }) + f"\n\n<b>Автор:</b> <a href=\"tg://user?id={message.from_user.id}\">{message.from_user.full_name}</a>\n<b>ID поста:</b> {post_id}"

    try:
        media = []
        # перше фото як окреме повідомлення з підписом
        photos = post["photos"]
        first = photos[0]
        await bot.send_photo(
            chat_id=ADMIN_GROUP_ID,
            photo=first["file_id"],
            caption=text,
            reply_markup=kb_moderation(post_id),
        )
        # решта — галереєю
        for p in photos[1:10]:  # Telegram обмеження на медіагрупи ~10
            media.append(InputMediaPhoto(media=p["file_id"]))
        if media:
            await bot.send_media_group(chat_id=ADMIN_GROUP_ID, media=media)
    except Exception as e:
        await message.answer("Оголошення збережено, але не вдалося відправити в адмін-групу. Повідомте адміна.")

    await message.answer("Оголошення надіслано на модерацію. Дякуємо!")

# =========================
# Адмін-панель / Модерація
# =========================


@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.chat.type != ChatType.PRIVATE:
        return
    await message.answer("Панель адміністратора", reply_markup=kb_admin())


@dp.callback_query(F.data == "admin:queue")
async def admin_queue(call: CallbackQuery):
    db = await get_db()
    async with db.execute(
        "SELECT post_id FROM moderation_queue ORDER BY queued_at LIMIT 10"
    ) as cur:
        rows = await cur.fetchall()
    if not rows:
        await call.message.edit_text("Черга порожня")
        await call.answer()
        return
    ids = [str(r[0]) for r in rows]
    await call.message.edit_text("Найближчі в черзі: " + ", ".join(ids))
    await call.answer()


@dp.callback_query(F.data == "admin:stats")
async def admin_stats(call: CallbackQuery):
    db = await get_db()
    now = int(now_tz().timestamp())
    day_ago = now - 86400
    week_ago = now - 86400 * 7
    month_ago = now - 86400 * 30

    async def count_since(ts: int) -> Tuple[int, int]:
        return (
            # created
            (
                await db.execute_fetchone(
                    "SELECT COUNT(*) FROM posts WHERE created_at>=?", (ts,)
                )
            )[0],
            # rejected
            (
                await db.execute_fetchone(
                    "SELECT COUNT(*) FROM posts WHERE created_at>=? AND status='rejected'",
                    (ts,),
                )
            )[0],
        )

    created_d, rejected_d = await db.execute_fetchone(
        "SELECT COUNT(*), SUM(status='rejected') FROM posts WHERE created_at>=?",
        (day_ago,),
    )
    created_w, rejected_w = await db.execute_fetchone(
        "SELECT COUNT(*), SUM(status='rejected') FROM posts WHERE created_at>=?",
        (week_ago,),
    )
    created_m, rejected_m = await db.execute_fetchone(
        "SELECT COUNT(*), SUM(status='rejected') FROM posts WHERE created_at>=?",
        (month_ago,),
    )

    text = (
        f"Статистика:\n\n"
        f"За день: всього {created_d or 0}, відхилено {rejected_d or 0}\n"
        f"За тиждень: всього {created_w or 0}, відхилено {rejected_w or 0}\n"
        f"За місяць: всього {created_m or 0}, відхилено {rejected_m or 0}"
    )
    await call.message.edit_text(text)
    await call.answer()


@dp.callback_query(F.data.startswith("mod:"))
async def cb_moderation(call: CallbackQuery):
    db = await get_db()
    parts = call.data.split(":")
    action = parts[1]
    post_id = int(parts[2])

    async with db.execute(
        "SELECT author_id, title, description, district, category, contacts, status FROM posts WHERE id=?",
        (post_id,),
    ) as cur:
        post = await cur.fetchone()
    if not post:
        await call.answer("Пост не знайдено", show_alert=True)
        return

    author_id, title, desc, district, category, contacts, status = post

    if action == "ban":
        await db.execute(
            "INSERT OR REPLACE INTO blacklist(user_id, reason, added_at) VALUES(?,?,?)",
            (author_id, f"Бан через пост {post_id}", int(now_tz().timestamp())),
        )
        await db.commit()
        await bot.send_message(author_id, "Вас заблоковано в сервісі оголошень.")
        await call.answer("Користувача заблоковано")
        return

    if action == "approve":
        # Змінюємо статус, виймаємо з черги
        await db.execute("UPDATE posts SET status='approved' WHERE id=?", (post_id,))
        await db.execute("DELETE FROM moderation_queue WHERE post_id=?", (post_id,))
        await db.commit()
        await bot.send_message(author_id, f"Ваше оголошення #{post_id} схвалено та буде опубліковане за розкладом.")
        await log_admin(call.from_user.id, f"approve post {post_id}")
        await call.answer("Схвалено")
        # миттєва проба публікації (якщо черга пуста або дозволено поза розкладом — тут без змін)
        return

    if action == "reject":
        # Запросимо причину відхилення через ForceReply? Спрощено: стандартна причина
        reason = "Порушення правил або некоректний формат."
        await db.execute(
            "UPDATE posts SET status='rejected', reject_reason=? WHERE id=?",
            (reason, post_id),
        )
        await db.execute("DELETE FROM moderation_queue WHERE post_id=?", (post_id,))
        await db.commit()
        await bot.send_message(author_id, f"Ваше оголошення #{post_id} відхилено. Причина: {reason}")
        await log_admin(call.from_user.id, f"reject post {post_id}")
        await call.answer("Відхилено")
        return


async def log_admin(admin_id: int, action: str):
    db = await get_db()
    await db.execute(
        "INSERT INTO admin_logs(admin_id, action, post_id, created_at) VALUES(?,?,NULL,?)",
        (admin_id, action, int(now_tz().timestamp())),
    )
    await db.commit()
    if LOG_CHANNEL_ID:
        try:
            await bot.send_message(LOG_CHANNEL_ID, f"Адмін {admin_id}: {action}")
        except Exception:
            pass

# =========================
# Автопостинг / Розклад
# =========================


async def ensure_default_schedules(db: aiosqlite.Connection):
    # для кожного пост-таргета має бути запис у schedules
    ts = int(now_tz().timestamp())
    for chat_id in POST_TARGET_IDS:
        await db.execute(
            "INSERT OR IGNORE INTO schedules(chat_id, interval_min, next_run_at) VALUES(?,?,?)",
            (chat_id, DEFAULT_POST_INTERVAL_MIN, ts),
        )
    await db.commit()


async def pick_next_post(db: aiosqlite.Connection) -> Optional[Tuple[int, dict, List[str]]]:
    # вибрати найстаріший approved пост, що ще не публікувався
    async with db.execute(
        "SELECT id, author_id, title, description, district, category, contacts FROM posts WHERE status='approved' ORDER BY created_at LIMIT 1"
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    post_id, author_id, title, desc, district, category, contacts = row
    async with db.execute(
        "SELECT file_id FROM post_photos WHERE post_id=? ORDER BY id",
        (post_id,),
    ) as cur:
        photos = [r[0] async for r in cur]
    payload = {
        "title": title,
        "description": desc,
        "district": district,
        "category": category,
        "contacts": contacts,
    }
    return post_id, payload, photos


async def publish_post_to(chat_id: int, text: str, photos: List[str]) -> Optional[int]:
    try:
        msg = await bot.send_photo(chat_id, photos[0], caption=text)
        if len(photos) > 1:
            media = [InputMediaPhoto(media=p) for p in photos[1:10]]
            if media:
                await bot.send_media_group(chat_id, media)
        return msg.message_id
    except Exception:
        return None


async def autoposter_loop():
    await asyncio.sleep(2)
    db = await get_db()
    await ensure_default_schedules(db)
    while True:
        now_ts = int(now_tz().timestamp())
        # знайти всі чати, де пора публікувати
        async with db.execute(
            "SELECT id, chat_id, interval_min, next_run_at FROM schedules WHERE next_run_at<=?",
            (now_ts,),
        ) as cur:
            due = await cur.fetchall()
        if due:
            # на кожний чат пробуємо взяти пост
            for _sid, chat_id, interval_min, _next in due:
                pick = await pick_next_post(db)
                if not pick:
                    # Нема постів — перенести next_run_at
                    await db.execute(
                        "UPDATE schedules SET next_run_at=? WHERE chat_id=?",
                        (now_ts + interval_min * 60, chat_id),
                    )
                    await db.commit()
                    continue
                post_id, payload, photos = pick
                text = format_post_text(payload)
                main_msg_id = await publish_post_to(chat_id, text, photos)
                if main_msg_id:
                    # дублювання у резервні канали
                    for bcid in BACKUP_CHANNEL_IDS:
                        await publish_post_to(bcid, text, photos)

                    # оновити статус поста
                    await db.execute(
                        "UPDATE posts SET status='published' WHERE id=?",
                        (post_id,),
                    )
                    await db.commit()
                # перенести розклад далі
                await db.execute(
                    "UPDATE schedules SET next_run_at=? WHERE chat_id=?",
                    (now_ts + interval_min * 60, chat_id),
                )
                await db.commit()
        await asyncio.sleep(30)  # цикл перевірки кожні 30 сек

# =========================
# Хендлери груп: простий анти-спам (лінки/нецензурщина)
# =========================

LINK_RE = re.compile(r"https?://|t\.me/|@\w+", re.I)


@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def group_guard(message: Message):
    # банально: якщо новий юзер шле лінки — видалити
    if message.text and LINK_RE.search(message.text):
        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass

# =========================
# Головний вхід
# =========================


async def main():
    db = await get_db()
    # прогріти таблиці та розклади
    await ensure_default_schedules(db)
    # фоновий цикл автопостингу
    asyncio.create_task(autoposter_loop())
    # старт полінгу
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
