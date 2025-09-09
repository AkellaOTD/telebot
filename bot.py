from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
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

MODERATORS_CHAT_ID = os.getenv("MODERATORS_CHAT_ID")
if not MODERATORS_CHAT_ID:
    raise ValueError("❌ MODERATORS_CHAT_ID не знайдено у .env")
MODERATORS_CHAT_ID = int(MODERATORS_CHAT_ID)

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
    is_queued INTEGER DEFAULT 0,
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

cursor.execute("""
CREATE TABLE IF NOT EXISTS admin_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER,
    admin_username TEXT,
    action TEXT,
    ad_id INTEGER,
    chat_id INTEGER,
    thread_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS blacklist (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        InlineKeyboardButton("✅ Опублікувати зараз", callback_data=f"publish_{ad_id}"),
        InlineKeyboardButton("⏳ Додати в чергу", callback_data=f"queue_{ad_id}"),
        InlineKeyboardButton("❌ Відхилити", callback_data=f"reject_{ad_id}"),
        InlineKeyboardButton("🚫 Чорний список", callback_data=f"blacklist_{ad_id}")
    )
    kb.add(
        InlineKeyboardButton("✏️ Редагувати", callback_data=f"edit_{ad_id}"),
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
    cursor.execute("SELECT 1 FROM blacklist WHERE user_id=?", (message.from_user.id,))
    if cursor.fetchone():
        await message.answer("🚫 Ви заблоковані та не можете подавати оголошення.")
        return
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
def log_admin_action(admin_id, username, action, ad_id=None, chat_id=None, thread_id=None):
    cursor.execute(
        "INSERT INTO admin_logs (admin_id, admin_username, action, ad_id, chat_id, thread_id) VALUES (?, ?, ?, ?, ?, ?)",
        (admin_id, username, action, ad_id, chat_id, thread_id)
    )
    conn.commit()

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
    log_admin_action(callback_query.from_user.id, callback_query.from_user.username, f"reject: {reason}", ad_id)

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
    log_admin_action(callback_query.from_user.id, callback_query.from_user.username, "publish", ad_id, chat_id, thread_id)

@dp.callback_query_handler(lambda c: c.data.startswith("queue_"))
async def process_queue(callback_query: types.CallbackQuery):
    ad_id = int(callback_query.data.split("_")[1])
    cursor.execute("UPDATE ads SET is_queued=1 WHERE id=?", (ad_id,))
    conn.commit()

    await callback_query.message.edit_reply_markup(reply_markup=None)
    await bot.send_message(
        callback_query.from_user.id,
        f"⏳ Оголошення #{ad_id} додано у чергу на публікацію"
    )
    cursor.execute("SELECT user_id FROM ads WHERE id=?", (ad_id,))
    row = cursor.fetchone()
    if row:
        user_id = row[0]
        kb = ReplyKeyboardMarkup(resize_keyboard=True).add("📢 Подати оголошення")
        await bot.send_message(user_id, "✅ Ваше оголошення додано до черги на публікацію!", reply_markup=kb)

    log_admin_action(callback_query.from_user.id, callback_query.from_user.username, "queue_ad", ad_id)

@dp.callback_query_handler(lambda c: c.data.startswith("blacklist_"))
async def process_blacklist(callback_query: types.CallbackQuery):
    ad_id = int(callback_query.data.split("_")[1])

    # Отримуємо користувача з БД
    cursor.execute("SELECT user_id, username, first_name FROM ads WHERE id=?", (ad_id,))
    row = cursor.fetchone()

    if not row:
        await callback_query.answer("Оголошення не знайдено ❌", show_alert=True)
        return

    user_id, username, first_name = row

    # Додаємо у blacklist
    cursor.execute("INSERT OR IGNORE INTO blacklist (user_id, username, first_name) VALUES (?, ?, ?)",
                   (user_id, username, first_name))
    conn.commit()

    await callback_query.answer("🚫 Користувач доданий у чорний список")
    await bot.send_message(callback_query.from_user.id,
                           f"Користувач {first_name} (@{username}) [{user_id}] доданий у чорний список")

    # Логування дії
    log_admin_action(callback_query.from_user.id,
                     callback_query.from_user.username,
                     "blacklist_user",
                     ad_id)

@dp.callback_query_handler(lambda c: c.data.startswith("unblacklist_"))
async def process_unblacklist(callback_query: types.CallbackQuery):
    user_id = int(callback_query.data.split("_")[1])

    cursor.execute("DELETE FROM blacklist WHERE user_id=?", (user_id,))
    conn.commit()

    await callback_query.answer("✅ Користувача розблоковано")
    await callback_query.message.edit_text(f"Користувача <code>{user_id}</code> розблоковано", parse_mode="HTML")

    # Логування
    log_admin_action(callback_query.from_user.id,
                     callback_query.from_user.username,
                     "unblacklist_user",
                     None)

@dp.callback_query_handler(lambda c: c.data.startswith("edit_"))
async def process_edit(callback_query: types.CallbackQuery, state: FSMContext):
    ad_id = int(callback_query.data.split("_")[1])
    await state.update_data(ad_id=ad_id)

    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🏷 Заголовок", callback_data="editfield_title"),
        InlineKeyboardButton("📝 Опис", callback_data="editfield_description"),
    )
    kb.add(
        InlineKeyboardButton("📞 Контакти", callback_data="editfield_contacts"),
        InlineKeyboardButton("📍 Район", callback_data="editfield_district"),
    )

    await callback_query.message.answer(f"✏️ Виберіть поле для редагування #{ad_id}:", reply_markup=kb)
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("editfield_"))
async def process_edit_field(callback_query: types.CallbackQuery, state: FSMContext):
    field = callback_query.data.split("_")[1]
    await state.update_data(field=field)
    await EditAdForm.value.set()

    await callback_query.message.answer(f"Введіть нове значення для {field}:")
    await callback_query.answer()

@dp.message_handler(state=EditAdForm.value)
async def process_edit_value(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ad_id = data["ad_id"]
    field = data["field"]
    value = message.text.strip()

    allowed_fields = {
        "title": "title",
        "description": "description",
        "contacts": "contacts",
        "district": "district"
    }

    if field not in allowed_fields:
        await message.answer("❌ Невідоме поле.")
        await state.finish()
        return

    column = allowed_fields[field]
    cursor.execute(f"UPDATE ads SET {column}=? WHERE id=?", (value, ad_id))
    conn.commit()

    await message.answer(f"✅ Поле '{column}' оновлено для оголошення #{ad_id}")
    log_admin_action(message.from_user.id, message.from_user.username, f"edit_{column}", ad_id)

    await state.finish()

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
    log_admin_action(message.from_user.id, message.from_user.username, "bind_thread", chat_id=chat_id, thread_id=thread_id)

@dp.message_handler(commands=["blacklist"])
async def cmd_blacklist(message: types.Message):
    # Доступ тільки для адмінів
    if message.chat.id != MODERATORS_CHAT_ID:
        await message.answer("⛔ Ця команда доступна лише в адмін-групі")
        return

    cursor.execute("SELECT user_id, username, first_name, added_at FROM blacklist ORDER BY added_at DESC")
    users = cursor.fetchall()

    if not users:
        await message.answer("✅ Чорний список порожній")
        return

    text = "<b>🚫 Чорний список користувачів:</b>\n\n"
    kb = InlineKeyboardMarkup(row_width=1)

    for user_id, username, first_name, added_at in users:
        uname = f"@{username}" if username else ""
        text += f"👤 <b>{first_name}</b> {uname} (<code>{user_id}</code>) — {added_at}\n"
        kb.add(InlineKeyboardButton(f"❌ Розблокувати {first_name}", callback_data=f"unblacklist_{user_id}"))

    await message.answer(text, parse_mode="HTML", reply_markup=kb)

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
    log_admin_action(message.from_user.id, message.from_user.username, "view_stats", chat_id=message.chat.id)

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


@app.get("/logs", response_class=HTMLResponse)
async def get_logs(
    admin_id: int | None = None,
    action: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    chat_id: int | None = None,
    thread_id: int | None = None,
    published: str | None = None   # "yes", "no" або None
):
    # Отримуємо доступні значення для select
    cursor.execute("SELECT DISTINCT admin_id, admin_username FROM admin_logs WHERE admin_id IS NOT NULL")
    admins = cursor.fetchall()

    cursor.execute("SELECT DISTINCT chat_id FROM admin_logs WHERE chat_id IS NOT NULL")
    chats = [row[0] for row in cursor.fetchall()]

    cursor.execute("SELECT DISTINCT thread_id FROM admin_logs WHERE thread_id IS NOT NULL")
    threads = [row[0] for row in cursor.fetchall()]

    # Базовий SQL
    query = """
        SELECT id, admin_id, admin_username, action, ad_id, chat_id, thread_id, created_at
        FROM admin_logs
        WHERE 1=1
    """
    params = []

    if admin_id:
        query += " AND admin_id=?"
        params.append(admin_id)
    if action:
        query += " AND action LIKE ?"
        params.append(f"%{action}%")
    if date_from:
        query += " AND date(created_at) >= date(?)"
        params.append(date_from)
    if date_to:
        query += " AND date(created_at) <= date(?)"
        params.append(date_to)
    if chat_id:
        query += " AND chat_id=?"
        params.append(chat_id)
    if thread_id:
        query += " AND thread_id=?"
        params.append(thread_id)
    if published == "yes":
        query += " AND action LIKE 'publish%'"
    elif published == "no":
        query += " AND action LIKE 'reject%'"

    query += " ORDER BY created_at DESC LIMIT 200"
    cursor.execute(query, params)
    rows = cursor.fetchall()

    # HTML-форма + таблиця
    html = """
    <html>
    <head>
        <title>Admin Logs</title>
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; }
            table { border-collapse: collapse; width: 100%; margin-top: 20px; }
            th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
            th { background-color: #f4f4f4; }
            tr:nth-child(even) { background-color: #fafafa; }
            .filters { margin-bottom: 20px; }
            .filters label { margin-right: 10px; }
            .filters select, .filters input { margin-right: 15px; }
        </style>
    </head>
    <body>
        <h1>Admin Logs</h1>
        <form method="get" class="filters">

            <label>Admin:
                <select name="admin_id">
                    <option value="">-- All --</option>
    """

    for a_id, a_user in admins:
        label = f"{a_id} (@{a_user})" if a_user else str(a_id)
        selected = "selected" if str(admin_id) == str(a_id) else ""
        html += f"<option value='{a_id}' {selected}>{label}</option>"

    html += """
                </select>
            </label>

            <label>Chat:
                <select name="chat_id">
                    <option value="">-- All --</option>
    """

    for chat in chats:
        selected = "selected" if str(chat_id) == str(chat) else ""
        html += f"<option value='{chat}' {selected}>{chat}</option>"

    html += """
                </select>
            </label>

            <label>Thread:
                <select name="thread_id">
                    <option value="">-- All --</option>
    """

    for t in threads:
        selected = "selected" if str(thread_id) == str(t) else ""
        html += f"<option value='{t}' {selected}>{t}</option>"

    html += """
                </select>
            </label>

            <label>Status:
                <select name="published">
                    <option value="">-- All --</option>
                    <option value="yes" {yes_sel}>Published</option>
                    <option value="no" {no_sel}>Rejected</option>
                </select>
            </label>

            <label>Date from:
                <input type="date" name="date_from" value="{date_from}">
            </label>

            <label>Date to:
                <input type="date" name="date_to" value="{date_to}">
            </label>

            <input type="submit" value="Filter">
        </form>
        <table>
            <tr>
                <th>ID</th>
                <th>Admin ID</th>
                <th>Username</th>
                <th>Action</th>
                <th>Ad ID</th>
                <th>Chat</th>
                <th>Thread</th>
                <th>Time</th>
            </tr>
    """.format(
        yes_sel="selected" if published == "yes" else "",
        no_sel="selected" if published == "no" else "",
        date_from=date_from or "",
        date_to=date_to or ""
    )

    for r in rows:
        html += f"""
        <tr>
            <td>{r[0]}</td>
            <td>{r[1]}</td>
            <td>@{r[2] if r[2] else ''}</td>
            <td>{r[3]}</td>
            <td>{r[4] if r[4] else ''}</td>
            <td>{r[5] if r[5] else ''}</td>
            <td>{r[6] if r[6] else ''}</td>
            <td>{r[7]}</td>
        </tr>
        """

    html += "</table></body></html>"
    return HTMLResponse(content=html)
# -------------------------------
# 🔹 Локальний запуск
# -------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))