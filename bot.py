import os
import sqlite3
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove

# -------------------------------
# 🔹 Конфіг з ENV
# -------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")  # https://mybot.onrender.com
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = int(os.getenv("PORT", 8000))

# -------------------------------
# 🔹 Ініціалізація
# -------------------------------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
app = FastAPI()

# -------------------------------
# 🔹 База даних
# -------------------------------
conn = sqlite3.connect("database.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    accepted_rules BOOLEAN DEFAULT 0
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS ads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    category TEXT,
    district TEXT,
    title TEXT,
    description TEXT,
    photos TEXT,
    contacts TEXT
)
""")
conn.commit()

# -------------------------------
# 🔹 Стан машини для оголошень
# -------------------------------
class AdForm(StatesGroup):
    category = State()
    district = State()
    title = State()
    description = State()
    photos = State()
    contacts = State()

# -------------------------------
# 🔹 Хендлер /start
# -------------------------------
@dp.message_handler(commands="start")
async def cmd_start(message: types.Message):
    cursor.execute("SELECT accepted_rules FROM users WHERE user_id = ?", (message.from_user.id,))
    user = cursor.fetchone()

    if not user:
        cursor.execute("INSERT INTO users (user_id, accepted_rules) VALUES (?, 0)", (message.from_user.id,))
        conn.commit()
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("✅ Погоджуюсь", "❌ Не погоджуюсь")
        await message.answer(
            "📜 Правила:\n\n1. Не порушуйте закон\n2. Не публікуйте спам\n\nВи погоджуєтесь?",
            reply_markup=kb
        )
    elif not user[0]:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("✅ Погоджуюсь", "❌ Не погоджуюсь")
        await message.answer("Ви ще не погодились із правилами. Погоджуєтесь?", reply_markup=kb)
    else:
        await message.answer("Ласкаво просимо! Використовуйте /create для створення оголошення.", reply_markup=ReplyKeyboardRemove())

# -------------------------------
# 🔹 Обробка погодження правил
# -------------------------------
@dp.message_handler(lambda m: m.text in ["✅ Погоджуюсь", "❌ Не погоджуюсь"])
async def process_rules(message: types.Message):
    if message.text == "✅ Погоджуюсь":
        cursor.execute("UPDATE users SET accepted_rules = 1 WHERE user_id = ?", (message.from_user.id,))
        conn.commit()
        await message.answer("✅ Дякую! Тепер ви можете створювати оголошення командою /create", reply_markup=ReplyKeyboardRemove())
    else:
        cursor.execute("DELETE FROM users WHERE user_id = ?", (message.from_user.id,))
        conn.commit()
        await message.answer("👋 Ви відмовились від правил. До побачення!", reply_markup=ReplyKeyboardRemove())

# -------------------------------
# 🔹 Створення оголошення /create
# -------------------------------
@dp.message_handler(commands="create")
async def cmd_create(message: types.Message, state: FSMContext):
    cursor.execute("SELECT accepted_rules FROM users WHERE user_id = ?", (message.from_user.id,))
    user = cursor.fetchone()

    if not user or not user[0]:
        await message.answer("⚠️ Спершу потрібно погодитись із правилами! Натисніть /start")
        return

    await AdForm.category.set()
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🏠 Нерухомість", "🚗 Авто", "📱 Електроніка", "👔 Робота")
    await message.answer("Оберіть тематику оголошення:", reply_markup=kb)

@dp.message_handler(state=AdForm.category)
async def process_category(message: types.Message, state: FSMContext):
    await state.update_data(category=message.text)
    await AdForm.next()
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Центр", "Лівий берег", "Правий берег")
    await message.answer("Оберіть район:", reply_markup=kb)

@dp.message_handler(state=AdForm.district)
async def process_district(message: types.Message, state: FSMContext):
    await state.update_data(district=message.text)
    await AdForm.next()
    await message.answer("Введіть заголовок (до 200 символів):", reply_markup=ReplyKeyboardRemove())

@dp.message_handler(state=AdForm.title)
async def process_title(message: types.Message, state: FSMContext):
    if len(message.text) > 200:
        await message.answer("❌ Заголовок занадто довгий (макс 200 символів)")
        return
    await state.update_data(title=message.text)
    await AdForm.next()
    await message.answer("Введіть опис (до 2000 символів):")

@dp.message_handler(state=AdForm.description)
async def process_description(message: types.Message, state: FSMContext):
    if len(message.text) > 2000:
        await message.answer("❌ Опис занадто довгий (макс 2000 символів)")
        return
    await state.update_data(description=message.text)
    await AdForm.next()
    await message.answer("Надішліть фото (до 20 шт). Якщо без фото — напишіть 'Пропустити'.")

@dp.message_handler(content_types=["photo", "text"], state=AdForm.photos)
async def process_photos(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get("photos", "")

    if message.content_type == "photo":
        file_id = message.photo[-1].file_id
        photos = (photos + "," + file_id).strip(",")
        await state.update_data(photos=photos)
        await message.answer("Фото додано ✅ Можете надіслати ще або напишіть 'Готово'.")
    elif message.text.lower() in ["готово", "пропустити"]:
        await AdForm.next()
        await message.answer("Введіть контактну інформацію (до 200 символів):")

@dp.message_handler(state=AdForm.contacts)
async def process_contacts(message: types.Message, state: FSMContext):
    if len(message.text) > 200:
        await message.answer("❌ Контакти занадто довгі (макс 200 символів)")
        return

    await state.update_data(contacts=message.text)
    data = await state.get_data()

    cursor.execute("""
        INSERT INTO ads (user_id, category, district, title, description, photos, contacts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        message.from_user.id,
        data["category"],
        data["district"],
        data["title"],
        data["description"],
        data.get("photos", ""),
        data["contacts"]
    ))
    conn.commit()

    await message.answer("✅ Ваше оголошення збережено!", reply_markup=ReplyKeyboardRemove())
    await state.finish()

# -------------------------------
# 🔹 FastAPI routes
# -------------------------------
@app.on_event("startup")
async def on_startup():
    await bot.set_webhook(WEBHOOK_URL)

@app.on_event("shutdown")
async def on_shutdown():
    await bot.delete_webhook()
    await dp.storage.close()
    await dp.storage.wait_closed()

@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    data = await request.json()
    update = types.Update.to_object(data)

    # 🔥 Фікс контексту
    from aiogram import Bot, Dispatcher
    Bot.set_current(bot)
    Dispatcher.set_current(dp)

    await dp.process_update(update)
    return {"ok": True}

@app.get("/users")
async def get_users():
    cursor.execute("SELECT * FROM users")
    return {"users": cursor.fetchall()}

@app.get("/ads")
async def get_ads():
    cursor.execute("SELECT * FROM ads")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]  # імена колонок
    ads = [dict(zip(columns, row)) for row in rows]     # робимо список словників
    return {"ads": ads}