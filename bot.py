import os
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.utils.executor import start_webhook
import sqlite3
from fastapi.responses import JSONResponse

# -------------------------------
# 🔹 Налаштування
# -------------------------------
API_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")

WEBHOOK_HOST = os.getenv('WEBHOOK_HOST')  # заміни на свій домен
WEBHOOK_PATH = os.getenv('WEBHOOK_PATH')
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

WEBAPP_HOST = os.getenv('WEBAPP_HOST')
WEBAPP_PORT = os.getenv('PORT')

# -------------------------------
# 🔹 База даних (SQLite)
# -------------------------------
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    accepted_rules BOOLEAN
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
# 🔹 FSM стани для створення оголошення
# -------------------------------
class AdForm(StatesGroup):
    category = State()
    district = State()
    title = State()
    description = State()
    photos = State()
    contacts = State()

# -------------------------------
# 🔹 Ініціалізація бота
# -------------------------------
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
app = FastAPI()

# -------------------------------
# 🔹 /start команда
# -------------------------------
@dp.message_handler(commands="start")
async def cmd_start(message: types.Message):
    cursor.execute("SELECT accepted_rules FROM users WHERE user_id = ?", (message.from_user.id,))
    user = cursor.fetchone()

    if user and user[0]:  # Якщо вже погодився
        await message.answer("✅ Ви вже погодились із правилами!\nГотові створити оголошення?")
        await message.answer("Натисніть /create щоб почати створення оголошення")
    else:
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add(KeyboardButton("✅ Погоджуюсь"), KeyboardButton("❌ Не погоджуюсь"))
        await message.answer("📜 Правила використання:\n\n1. ...\n2. ...\n3. ...\n\nВи погоджуєтесь?", reply_markup=kb)

# -------------------------------
# 🔹 Обробка згоди / відмови
# -------------------------------
@dp.message_handler(lambda m: m.text in ["✅ Погоджуюсь", "❌ Не погоджуюсь"])
async def process_rules(message: types.Message):
    if message.text == "✅ Погоджуюсь":
        cursor.execute("INSERT OR REPLACE INTO users (user_id, accepted_rules) VALUES (?, ?)", (message.from_user.id, True))
        conn.commit()
        await message.answer("Дякуємо! ✅ Тепер ви можете створити оголошення.\nНатисніть /create", reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer("👋 Добре, до побачення!", reply_markup=ReplyKeyboardRemove())
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)

# -------------------------------
# 🔹 Створення оголошення (FSM)
# -------------------------------
@dp.message_handler(commands="create")
async def cmd_create(message: types.Message):
    cursor.execute("SELECT accepted_rules FROM users WHERE user_id = ?", (message.from_user.id,))
    user = cursor.fetchone()
    if not user or not user[0]:
        await message.answer("⚠️ Спочатку потрібно погодитися з правилами! Напишіть /start")
        return

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Продам", "Куплю", "Послуги", "Інше")
    await message.answer("🔎 Оберіть тематику оголошення:", reply_markup=kb)
    await AdForm.category.set()

@dp.message_handler(state=AdForm.category)
async def process_category(message: types.Message, state: FSMContext):
    await state.update_data(category=message.text)
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Центр", "Північ", "Південь", "Схід", "Захід")
    await message.answer("📍 Оберіть район:", reply_markup=kb)
    await AdForm.next()

@dp.message_handler(state=AdForm.district)
async def process_district(message: types.Message, state: FSMContext):
    await state.update_data(district=message.text)
    await message.answer("✏️ Введіть заголовок (до 200 символів):", reply_markup=ReplyKeyboardRemove())
    await AdForm.next()

@dp.message_handler(state=AdForm.title)
async def process_title(message: types.Message, state: FSMContext):
    if len(message.text) > 200:
        await message.answer("❌ Заголовок занадто довгий. Спробуйте ще раз (макс 200 символів).")
        return
    await state.update_data(title=message.text)
    await message.answer("📝 Введіть опис (до 2000 символів):")
    await AdForm.next()

@dp.message_handler(state=AdForm.description)
async def process_description(message: types.Message, state: FSMContext):
    if len(message.text) > 2000:
        await message.answer("❌ Опис занадто довгий. Спробуйте ще раз (макс 2000 символів).")
        return
    await state.update_data(description=message.text)
    await message.answer("📸 Надішліть фото (до 20 шт). Якщо фото не потрібно — напишіть 'Пропустити'.")
    await AdForm.next()

@dp.message_handler(content_types=["photo", "text"], state=AdForm.photos)
async def process_photos(message: types.Message, state: FSMContext):
    if message.content_type == "text" and message.text.lower() == "пропустити":
        await state.update_data(photos=None)
    else:
        photos = []
        if message.photo:
            photos.append(message.photo[-1].file_id)
        await state.update_data(photos=",".join(photos))

    await message.answer("📞 Введіть контактну інформацію (до 200 символів):")
    await AdForm.next()

@dp.message_handler(state=AdForm.contacts)
async def process_contacts(message: types.Message, state: FSMContext):
    if len(message.text) > 200:
        await message.answer("❌ Контакти занадто довгі. Макс 200 символів.")
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
        data["photos"],
        data["contacts"]
    ))
    conn.commit()

    await message.answer("✅ Оголошення створено!", reply_markup=ReplyKeyboardRemove())
    await state.finish()

# -------------------------------
# 🔹 Webhook для FastAPI
# -------------------------------
@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    update = types.Update(**await request.json())
    await dp.process_update(update)

# -------------------------------
# 🔹 Запуск сервера
# -------------------------------
async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_URL)

async def on_shutdown(dp):
    await bot.delete_webhook()


# -------------------------------
# 🔹 Виведення користувачів
# -------------------------------
@app.get("/users")
async def get_users():
    cursor.execute("SELECT user_id, accepted_rules FROM users")
    rows = cursor.fetchall()
    users = [{"user_id": r[0], "accepted_rules": bool(r[1])} for r in rows]
    return JSONResponse(content=users)

# -------------------------------
# 🔹 Виведення оголошень
# -------------------------------
@app.get("/ads")
async def get_ads():
    cursor.execute("SELECT id, user_id, category, district, title, description, photos, contacts FROM ads")
    rows = cursor.fetchall()
    ads = [
        {
            "id": r[0],
            "user_id": r[1],
            "category": r[2],
            "district": r[3],
            "title": r[4],
            "description": r[5],
            "photos": r[6].split(",") if r[6] else [],
            "contacts": r[7]
        }
        for r in rows
    ]
    return JSONResponse(content=ads)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=WEBAPP_HOST, port=WEBAPP_PORT)