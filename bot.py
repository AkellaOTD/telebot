from fastapi import FastAPI, Request
import os
import re
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent
)
import uvicorn

# -------------------------------
# 🔹 Конфіг
# -------------------------------
TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

DISTRICTS = os.getenv("DISTRICTS", "Центр,Лівий берег,Правий берег").split(",")

FAQ_RAW = os.getenv("FAQ", "")
FAQ_ITEMS = []
for item in FAQ_RAW.split(";"):
    if "|" in item:
        q, a = item.split("|", 1)
        FAQ_ITEMS.append((q.strip(), a.strip()))

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
app = FastAPI()

# -------------------------------
# 🔹 База даних
# -------------------------------
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER UNIQUE,
    accepted_rules BOOLEAN
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS ads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    first_name TEXT,
    category TEXT,
    district TEXT,
    title TEXT,
    description TEXT,
    photos TEXT,
    contacts TEXT,
    is_published INTEGER DEFAULT 0,
    is_rejected INTEGER DEFAULT 0,
    rejection_reason TEXT,
    moder_message_id INTEGER,
    shares INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    thread_id INTEGER,
    title TEXT,
    UNIQUE(chat_id, thread_id)
)
""")
conn.commit()

# -------------------------------
# 🔹 FSM
# -------------------------------
class AdForm(StatesGroup):
    category = State()
    district = State()
    title = State()
    description = State()
    photos = State()
    contacts = State()

# -------------------------------
# 🔹 Фільтр тексту
# -------------------------------
BANNED_WORDS = os.getenv("BANNED_WORDS", "").split(",")
BANNED_WORDS = [w.strip().lower() for w in BANNED_WORDS if w.strip()]

def validate_input(text: str) -> tuple[bool, str]:
    if re.search(r"(http[s]?://|www\.|t\.me/)", text, re.IGNORECASE):
        return False, "❌ Текст не може містити посилання!"
    lowered = text.lower()
    for word in BANNED_WORDS:
        if word in lowered:
            return False, f"❌ Текст містить заборонене слово: {word}"
    return True, ""

# -------------------------------
# 🔹 Клавіатури
# -------------------------------
def main_menu_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("📢 Подати оголошення", "ℹ️ FAQ")
    return kb

def faq_text():
    if not FAQ_ITEMS:
        return "ℹ️ Наразі FAQ порожній."
    lines = []
    for q, a in FAQ_ITEMS:
        lines.append(f"❓ {q}\n💬 {a}")
    return "\n\n".join(lines)

def get_moder_keyboard(ad_id: int, user_id: int, username: str | None):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✅ Опублікувати", callback_data=f"publish_{ad_id}"),
        InlineKeyboardButton("❌ Відхилити", callback_data=f"reject_{ad_id}")
    )
    if username:
        kb.add(InlineKeyboardButton(f"👤 @{username}", url=f"https://t.me/{username}"))
    else:
        kb.add(InlineKeyboardButton("👤 Профіль", url=f"tg://user?id={user_id}"))
    return kb

def get_user_button(user_id: int, username: str | None):
    if username:
        return InlineKeyboardButton(f"👤 @{username}", url=f"https://t.me/{username}")
    else:
        return InlineKeyboardButton("👤 Профіль", url=f"tg://user?id={user_id}")

# -------------------------------
# 🔹 /start
# -------------------------------
@dp.message_handler(commands="start")
async def cmd_start(message: types.Message):
    cursor.execute("SELECT accepted_rules FROM users WHERE user_id = ?", (message.from_user.id,))
    user = cursor.fetchone()

    if user and user[0]:
        await message.answer("✅ Ви вже погодились з правилами!", reply_markup=main_menu_kb())
        return

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("✅ Погоджуюсь", "❌ Не погоджуюсь")
    await message.answer(
        "📜 Правила:\n1. Без посилань.\n2. Без спаму.\n3. Заборонені слова не допускаються.\n\nВи погоджуєтесь?",
        reply_markup=kb
    )

@dp.message_handler(lambda msg: msg.text in ["✅ Погоджуюсь", "❌ Не погоджуюсь"])
async def rules_answer(message: types.Message):
    if message.text == "✅ Погоджуюсь":
        cursor.execute(
            "INSERT OR REPLACE INTO users (user_id, accepted_rules) VALUES (?, ?)",
            (message.from_user.id, True)
        )
        conn.commit()
        await message.answer("✅ Дякуємо! Тепер можете подати оголошення:", reply_markup=main_menu_kb())
    else:
        await message.answer("👋 Добре, до зустрічі!", reply_markup=ReplyKeyboardRemove())

# -------------------------------
# 🔹 FAQ
# -------------------------------
@dp.message_handler(lambda msg: msg.text == "ℹ️ FAQ")
async def handle_faq(message: types.Message):
    await message.answer(faq_text(), reply_markup=main_menu_kb())

# -------------------------------
# 🔹 Обробник кнопки "Подати оголошення"
# -------------------------------
@dp.message_handler(lambda msg: msg.text == "📢 Подати оголошення")
async def handle_new_ad_button(message: types.Message, state: FSMContext):
    await cmd_create(message, state)

# -------------------------------
# 🔹 /create (FSM) — тепер викликається тільки через кнопку
# -------------------------------
async def cmd_create(message: types.Message, state: FSMContext):
    cursor.execute("SELECT accepted_rules FROM users WHERE user_id = ?", (message.from_user.id,))
    user = cursor.fetchone()
    if not user or not user[0]:
        await message.answer("⚠️ Спершу потрібно погодитись із правилами! Натисніть /start")
        return

    cursor.execute("SELECT title FROM threads WHERE chat_id=?", (int(os.getenv("MODERATORS_CHAT_ID")),))
    categories = [row[0] for row in cursor.fetchall()]
    if not categories:
        await message.answer("⚠️ Немає доступних категорій. Адміністратор має додати гілки командою /bindthread")
        return

    await AdForm.category.set()
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    for c in categories:
        kb.add(c)
    kb.add("ℹ️ FAQ")
    await message.answer("Оберіть категорію:", reply_markup=kb)

@dp.message_handler(state=AdForm.category)
async def process_category(message: types.Message, state: FSMContext):
    if message.text == "ℹ️ FAQ":
        await message.answer(faq_text(), reply_markup=main_menu_kb())
        return
    await state.update_data(category=message.text)
    await AdForm.next()
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    for d in DISTRICTS:
        kb.add(d)
    kb.add("ℹ️ FAQ")
    await message.answer("Оберіть район:", reply_markup=kb)

@dp.message_handler(state=AdForm.district)
async def process_district(message: types.Message, state: FSMContext):
    if message.text == "ℹ️ FAQ":
        await message.answer(faq_text(), reply_markup=main_menu_kb())
        return
    await state.update_data(district=message.text)
    await AdForm.next()
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("ℹ️ FAQ")
    await message.answer("Введіть заголовок (до 200 символів):", reply_markup=kb)

@dp.message_handler(state=AdForm.title)
async def process_title(message: types.Message, state: FSMContext):
    if message.text == "ℹ️ FAQ":
        await message.answer(faq_text(), reply_markup=main_menu_kb())
        return
    if len(message.text) > 200:
        await message.answer("❌ Заголовок занадто довгий (макс 200 символів)")
        return
    valid, error = validate_input(message.text)
    if not valid:
        await message.answer(error)
        return
    await state.update_data(title=message.text)
    await AdForm.next()
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("ℹ️ FAQ")
    await message.answer("Введіть опис (до 2000 символів):", reply_markup=kb)

@dp.message_handler(state=AdForm.description)
async def process_description(message: types.Message, state: FSMContext):
    if message.text == "ℹ️ FAQ":
        await message.answer(faq_text(), reply_markup=main_menu_kb())
        return
    if len(message.text) > 2000:
        await message.answer("❌ Опис занадто довгий (макс 2000 символів)")
        return
    valid, error = validate_input(message.text)
    if not valid:
        await message.answer(error)
        return
    await state.update_data(description=message.text)
    await AdForm.next()
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Пропустити", "ℹ️ FAQ")
    await message.answer("Надішліть фото (до 20 шт). Якщо без фото — натисніть «Пропустити».", reply_markup=kb)

@dp.message_handler(content_types=["photo", "text"], state=AdForm.photos)
async def process_photos(message: types.Message, state: FSMContext):
    if message.text == "ℹ️ FAQ":
        await message.answer(faq_text(), reply_markup=main_menu_kb())
        return

    data = await state.get_data()
    photos = data.get("photos", "")

    if message.content_type == "photo":
        file_id = message.photo[-1].file_id
        photos = (photos + "," + file_id).strip(",")
        await state.update_data(photos=photos)
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("Готово", "ℹ️ FAQ")
        await message.answer("Фото додано ✅ Якщо все — натисніть «Готово».", reply_markup=kb)
    elif message.text.lower() == "пропустити":
        await AdForm.next()
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("ℹ️ FAQ")
        await message.answer("Введіть контактну інформацію (до 200 символів):", reply_markup=kb)
    elif message.text.lower() == "готово":
        await AdForm.next()
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("ℹ️ FAQ")
        await message.answer("Введіть контактну інформацію (до 200 символів):", reply_markup=kb)

@dp.message_handler(state=AdForm.contacts)
async def process_contacts(message: types.Message, state: FSMContext):
    if len(message.text) > 200:
        await message.answer("❌ Контакти занадто довгі (макс 200 символів)")
        return
    valid, error = validate_input(message.text)
    if not valid:
        await message.answer(error)
        return

    await state.update_data(contacts=message.text)
    data = await state.get_data()

    cursor.execute("""
        INSERT INTO ads (
            user_id, username, first_name, category, district, title, description, photos, contacts,
            is_published, is_rejected, rejection_reason, shares
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, 0)
    """, (
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        data["category"],
        data["district"],
        data["title"],
        data["description"],
        data.get("photos", ""),
        data["contacts"]
    ))
    conn.commit()

    cursor.execute("SELECT last_insert_rowid()")
    ad_id = cursor.fetchone()[0]

    moder_text = (
        f"📢 НОВЕ ОГОЛОШЕННЯ #{ad_id}\n\n"
        f"👤 Користувач: {message.from_user.first_name or ''} "
        f"(@{message.from_user.username}) [ID: {message.from_user.id}]\n\n"
        f"🔹 Категорія: {data['category']}\n"
        f"📍 Район: {data['district']}\n"
        f"🏷 Заголовок: {data['title']}\n"
        f"📝 Опис: {data['description']}\n"
        f"📞 Контакти: {data['contacts']}\n"
    )

    kb = get_moder_keyboard(ad_id, message.from_user.id, message.from_user.username)

    # Шукаємо гілку для модерації
    cursor.execute("""
        SELECT chat_id, thread_id FROM threads
        WHERE title=? AND chat_id=?
    """, (data["category"], int(os.getenv("MODERATORS_CHAT_ID"))))
    row = cursor.fetchone()

    if not row:
        await message.answer("❌ Для цієї категорії не знайдено гілки у групі модераторів")
        return

    moder_chat_id, moder_thread_id = row

    # Відправляємо у відповідну гілку
    msg = await bot.send_message(
        chat_id=moder_chat_id,
        message_thread_id=moder_thread_id,
        text=moder_text,
        reply_markup=kb
    )

    cursor.execute("UPDATE ads SET moder_message_id=? WHERE id=?", (msg.message_id, ad_id))
    conn.commit()

    await message.answer("✅ Ваше оголошення збережено та передано на модерацію!", reply_markup=ReplyKeyboardRemove())
    await state.finish()

# -------------------------------
# 🔹 Модерація
# -------------------------------
@dp.callback_query_handler(lambda c: c.data.startswith("reject_"))
async def process_reject(callback_query: types.CallbackQuery):
    ad_id = int(callback_query.data.split("_")[1])
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("❌ Заборонені слова", callback_data=f"reason_banned_{ad_id}"),
        InlineKeyboardButton("❌ Є посилання", callback_data=f"reason_link_{ad_id}"),
        InlineKeyboardButton("❌ Недостатньо інформації", callback_data=f"reason_info_{ad_id}")
    )
    await callback_query.message.answer(
        f"Виберіть причину відхилення для оголошення #{ad_id}:",
        reply_markup=kb
    )
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("reason_"))
async def process_reject_reason(callback_query: types.CallbackQuery):
    parts = callback_query.data.split("_")
    reason_type, ad_id = parts[1], int(parts[2])
    reasons = {
        "banned": "Містить заборонені слова",
        "link": "Є посилання",
        "info": "Недостатньо інформації"
    }
    reason = reasons.get(reason_type, "Відхилено")

    cursor.execute("UPDATE ads SET is_rejected=1, rejection_reason=? WHERE id=?", (reason, ad_id))
    conn.commit()

    cursor.execute("SELECT user_id FROM ads WHERE id=?", (ad_id,))
    user_id = cursor.fetchone()[0]

    kb = ReplyKeyboardMarkup(resize_keyboard=True).add("📢 Подати оголошення")

    await bot.send_message(
        user_id,
        f"❌ Ваше оголошення #{ad_id} було відхилено.\nПричина: {reason}",
        reply_markup=kb
    )
    await callback_query.message.answer(f"✅ Оголошення #{ad_id} відхилено. Причина: {reason}")
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("publish_"))
async def process_publish(callback_query: types.CallbackQuery):
    ad_id = int(callback_query.data.split("_")[1])
    cursor.execute("SELECT user_id, username, first_name, category, district, title, description, photos, contacts FROM ads WHERE id=?", (ad_id,))
    ad = cursor.fetchone()

    if not ad:
        await callback_query.answer("Оголошення не знайдено ❌", show_alert=True)
        return

    user_id, username, first_name, category, district, title, description, photos, contacts = ad
    cursor.execute("UPDATE ads SET is_published=1 WHERE id=?", (ad_id,))
    conn.commit()

    pub_text = (
        f"📢 ОГОЛОШЕННЯ #{ad_id}\n\n"
        f"👤 Користувач: {first_name or ''} (@{username})\n\n"
        f"🔹 Категорія: {category}\n"
        f"📍 Район: {district}\n"
        f"🏷 Заголовок: {title}\n"
        f"📝 Опис: {description}\n"
        f"📞 Контакти: {contacts}\n"
    )
    pub_kb = InlineKeyboardMarkup()
    pub_kb.add(get_user_button(user_id, username))
    pub_kb.add(InlineKeyboardButton("🔗 Поділитися", switch_inline_query=str(ad_id)))

    # шукаємо thread_id і chat_id
    cursor.execute("SELECT thread_id FROM threads WHERE chat_id=? AND title=?", (int(os.getenv("PUBLISH_CHAT_ID")), category))
    row = cursor.fetchone()
    if not row:
        await callback_query.answer("❌ Категорія не привʼязана до гілки у групі публікацій", show_alert=True)
        return

    chat_id = int(os.getenv("PUBLISH_CHAT_ID"))
    thread_id = row[0]

    if photos:
        photos = photos.split(",")
        if len(photos) == 1:
            await bot.send_photo(
                chat_id=chat_id,
                message_thread_id=thread_id,
                photo=photos[0],
                caption=pub_text,
                reply_markup=pub_kb
            )
        else:
            media = [types.InputMediaPhoto(p) for p in photos[:10]]
            await bot.send_media_group(chat_id=chat_id, message_thread_id=thread_id, media=media)
            await bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=pub_text,
                reply_markup=pub_kb
            )
    else:
        await bot.send_message(
            chat_id=chat_id,
            message_thread_id=thread_id,
            text=pub_text,
            reply_markup=pub_kb
        )

    kb = ReplyKeyboardMarkup(resize_keyboard=True).add("📢 Подати оголошення")
    await bot.send_message(user_id, "✅ Ваше оголошення успішно опубліковане!", reply_markup=kb)
    await callback_query.answer("Оголошення опубліковане ✅")

# -------------------------------
# 🔹 Inline handler для пересилань
# -------------------------------
@dp.inline_handler()
async def inline_query_handler(inline_query: InlineQuery):
    query = inline_query.query.strip()
    if not query.isdigit():
        return

    ad_id = int(query)
    cursor.execute("SELECT title, description, contacts FROM ads WHERE id=?", (ad_id,))
    ad = cursor.fetchone()
    if not ad:
        return

    title, description, contacts = ad

    text = (
        f"📢 ОГОЛОШЕННЯ #{ad_id}\n\n"
        f"🏷 {title}\n"
        f"📝 {description}\n"
        f"📞 {contacts}\n"
    )

    result = InlineQueryResultArticle(
        id=str(ad_id),
        title=f"Поділитися оголошенням #{ad_id}",
        description=title,
        input_message_content=InputTextMessageContent(text)
    )

    await bot.answer_inline_query(inline_query.id, results=[result], cache_time=0)

    # Рахуємо поширення
    cursor.execute("UPDATE ads SET shares = shares + 1 WHERE id=?", (ad_id,))
    conn.commit()

# -------------------------------
# 🔹 Команда /bindthread
# -------------------------------
@dp.message_handler(commands=["bindthread"], chat_type=[types.ChatType.SUPERGROUP])
async def bind_thread(message: types.Message):
    if not message.is_topic_message:
        await message.reply("⚠️ Використовуйте цю команду тільки в гілці (форум-темі).")
        return
    args = message.get_args()
    if not args:
        await message.reply("❌ Ви не вказали назву.\nПриклад: `/bindthread Продаж тварин`", parse_mode="Markdown")
        return

    chat_id = message.chat.id
    thread_id = message.message_thread_id
    title = args.strip()

    cursor.execute("""
        INSERT INTO threads (chat_id, thread_id, title)
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id, thread_id) DO UPDATE SET title=excluded.title
    """, (chat_id, thread_id, title))
    conn.commit()

    await message.reply(f"✅ Гілку збережено як: *{title}*", parse_mode="Markdown")

# -------------------------------
# 🔹 Статистика
# -------------------------------
@dp.message_handler(commands="stats")
async def cmd_stats(message: types.Message):
    # Перевіряємо, що команда викликана у групі модераторів
    if str(message.chat.id) != os.getenv("MODERATORS_CHAT_ID"):
        await message.reply("⛔ Ця команда доступна лише у групі модераторів.")
        return

    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    cursor.execute("SELECT COUNT(*) FROM ads WHERE created_at >= ?", (today,))
    today_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM ads WHERE created_at >= ?", (week_ago,))
    week_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM ads WHERE created_at >= ?", (month_ago,))
    month_count = cursor.fetchone()[0]

    cursor.execute("SELECT SUM(shares) FROM ads")
    total_shares = cursor.fetchone()[0] or 0

    await message.answer(
        f"📊 Статистика:\n"
        f"📅 За сьогодні: {today_count}\n"
        f"🗓 За тиждень: {week_count}\n"
        f"📆 За місяць: {month_count}\n"
        f"🔗 Всього пересилань: {total_shares}"
    )

# -------------------------------
# 🔹 API
# -------------------------------
@app.get("/threads")
async def get_threads():
    cursor.execute("SELECT chat_id, thread_id, title FROM threads")
    rows = cursor.fetchall()
    return {"threads": [{"chat_id": r[0], "thread_id": r[1], "title": r[2]} for r in rows]}

# -------------------------------
# 🔹 FastAPI endpoints
# -------------------------------
@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(WEBHOOK_URL)

@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    data = await request.json()
    update = types.Update.to_object(data)
    from aiogram import Bot
    Bot.set_current(bot)
    Dispatcher.set_current(dp)
    await dp.process_update(update)
    return {"ok": True}

# -------------------------------
# 🔹 Локальний запуск
# -------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))