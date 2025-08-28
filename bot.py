import os
import re
import sqlite3
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import uvicorn


# -------------------------------
# 🔹 Конфіг
# -------------------------------
TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

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
    category TEXT,
    district TEXT,
    title TEXT,
    description TEXT,
    photos TEXT,
    contacts TEXT,
    is_published BOOLEAN DEFAULT 0,
    is_rejected BOOLEAN DEFAULT 0,
    rejection_reason TEXT
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
BANNED_WORDS = ["спам", "шахрайство", "лохотрон", "обман", "scam", "fraud"]


def validate_input(text: str) -> tuple[bool, str]:
    """Перевірка тексту на посилання і заборонені слова"""
    if re.search(r"(http[s]?://|www\.|t\.me/)", text, re.IGNORECASE):
        return False, "❌ Текст не може містити посилання!"
    lowered = text.lower()
    for word in BANNED_WORDS:
        if word in lowered:
            return False, f"❌ Текст містить заборонене слово: {word}"
    return True, ""

# -------------------------------
# 🔹 /start
# -------------------------------


@dp.message_handler(commands="start")
async def cmd_start(message: types.Message):
    cursor.execute(
        "SELECT accepted_rules FROM users WHERE user_id = ?", (message.from_user.id,))
    user = cursor.fetchone()

    if user and user[0]:
        await message.answer("✅ Ви вже погодились з правилами! Можете створювати оголошення командою /create")
        return

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("✅ Погоджуюсь", "❌ Не погоджуюсь")
    await message.answer("📜 Правила:\n1. Без посилань.\n2. Без спаму.\n3. Заборонені слова не допускаються.\n\nВи погоджуєтесь?",
                         reply_markup=kb)


@dp.message_handler(lambda msg: msg.text in ["✅ Погоджуюсь", "❌ Не погоджуюсь"])
async def rules_answer(message: types.Message):
    if message.text == "✅ Погоджуюсь":
        cursor.execute(
            "INSERT OR REPLACE INTO users (user_id, accepted_rules) VALUES (?, ?)", (message.from_user.id, True))
        conn.commit()
        await message.answer("✅ Дякуємо! Тепер можете створити оголошення командою /create", reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer("👋 Добре, до зустрічі!", reply_markup=ReplyKeyboardRemove())

# -------------------------------
# 🔹 /create (FSM)
# -------------------------------


@dp.message_handler(commands="create")
async def cmd_create(message: types.Message, state: FSMContext):
    cursor.execute(
        "SELECT accepted_rules FROM users WHERE user_id = ?", (message.from_user.id,))
    user = cursor.fetchone()
    if not user or not user[0]:
        await message.answer("⚠️ Спершу потрібно погодитись із правилами! Натисніть /start")
        return

    await AdForm.category.set()
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Віддам тварину", "Продам тварину", "Знайдена тварина",
           "Загублена тварина", "Потрібна допомога ")
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
    valid, error = validate_input(message.text)
    if not valid:
        await message.answer(error)
        return
    await state.update_data(title=message.text)
    await AdForm.next()
    await message.answer("Введіть опис (до 2000 символів):")


@dp.message_handler(state=AdForm.description)
async def process_description(message: types.Message, state: FSMContext):
    if len(message.text) > 2000:
        await message.answer("❌ Опис занадто довгий (макс 2000 символів)")
        return
    valid, error = validate_input(message.text)
    if not valid:
        await message.answer(error)
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
    valid, error = validate_input(message.text)
    if not valid:
        await message.answer(error)
        return

    await state.update_data(contacts=message.text)
    data = await state.get_data()
    cursor.execute("""
    INSERT INTO ads (
        user_id, category, district, title, description, photos, contacts,
        is_published, is_rejected, rejection_reason
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, NULL)
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
    await message.answer("✅ Ваше оголошення збережено!")
    await state.finish()

# sending new ads to moderators group
cursor.execute("SELECT last_insert_rowid()")
ad_id = cursor.fetchone()[0]

# Формуємо текст оголошення
ad_text = (
    f"📢 НОВЕ ОГОЛОШЕННЯ #{ad_id}\n\n"
    f"🔹 Категорія: {data['category']}\n"
    f"📍 Район: {data['district']}\n"
    f"🏷 Заголовок: {data['title']}\n"
    f"📝 Опис: {data['description']}\n"
    f"📞 Контакти: {data['contacts']}\n"
)

# Кнопки модерації
moder_kb = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="✅ Опублікувати", callback_data=f"publish_{ad_id}"),
        InlineKeyboardButton(text="❌ Відхилити", callback_data=f"reject_{ad_id}")
    ]
])

# Надсилаємо в групу модераторів
await bot.send_message(
    chat_id=int(os.getenv("MODERATORS_CHAT_ID")),
    text=ad_text,
    reply_markup=moder_kb
)


@dp.callback_query_handler(lambda c: c.data.startswith("publish_"))
async def process_publish(callback_query: types.CallbackQuery):
    ad_id = int(callback_query.data.split("_")[1])

    cursor.execute("UPDATE ads SET is_published=1 WHERE id=?", (ad_id,))
    conn.commit()

    # Дістаємо оголошення
    cursor.execute("SELECT * FROM ads WHERE id=?", (ad_id,))
    ad = cursor.fetchone()
    columns = [desc[0] for desc in cursor.description]
    ad_dict = dict(zip(columns, ad))

    ad_text = (
        f"📢 ОГОЛОШЕННЯ\n\n"
        f"🔹 Категорія: {ad_dict['category']}\n"
        f"📍 Район: {ad_dict['district']}\n"
        f"🏷 Заголовок: {ad_dict['title']}\n"
        f"📝 Опис: {ad_dict['description']}\n"
        f"📞 Контакти: {ad_dict['contacts']}\n"
    )

    # Публікуємо у канал/групу
    await bot.send_message(int(os.getenv("PUBLISH_CHAT_ID")), ad_text)

    await callback_query.answer("Оголошення опубліковано ✅")


@dp.callback_query_handler(lambda c: c.data.startswith("reject_"))
async def process_reject(callback_query: types.CallbackQuery):
    ad_id = int(callback_query.data.split("_")[1])

    # Тут можна додати свій механізм запиту причини відхилення у адміна,
    # а для прикладу поставимо дефолт
    reason = "Не відповідає правилам"

    cursor.execute("UPDATE ads SET is_rejected=1, rejection_reason=? WHERE id=?", (reason, ad_id))
    conn.commit()

    # Отримуємо user_id власника
    cursor.execute("SELECT user_id FROM ads WHERE id=?", (ad_id,))
    user_id = cursor.fetchone()[0]

    # Повідомляємо користувача
    await bot.send_message(user_id, f"❌ Ваше оголошення #{ad_id} відхилено.\nПричина: {reason}")

    await callback_query.answer("Оголошення відхилено ❌")
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


@app.get("/ads")
async def get_ads():
    cursor.execute("SELECT * FROM ads")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    ads = [dict(zip(columns, row)) for row in rows]
    return {"ads": ads}
from fastapi import HTTPException

@app.get("/ads/{ad_id}")
async def get_ad(ad_id: int):
    cursor.execute("SELECT * FROM ads WHERE id = ?", (ad_id,))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Ad not found")

    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))


@app.post("/ads/{ad_id}/publish")
async def publish_ad(ad_id: int):
    cursor.execute("SELECT * FROM ads WHERE id = ?", (ad_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Ad not found")

    cursor.execute("UPDATE ads SET is_published = 1 WHERE id = ?", (ad_id,))
    conn.commit()
    return {"status": "success", "message": f"Ad {ad_id} published"}


@app.post("/ads/{ad_id}/reject")
async def reject_ad(ad_id: int, reason: str):
    cursor.execute("SELECT * FROM ads WHERE id = ?", (ad_id,))
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Ad not found")

    cursor.execute(
        "UPDATE ads SET is_rejected = 1, rejection_reason = ? WHERE id = ?",
        (reason, ad_id)
    )
    conn.commit()
    return {"status": "success", "message": f"Ad {ad_id} rejected", "reason": reason}


@app.get("/users")
async def get_users():
    cursor.execute("SELECT * FROM users")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    users = [dict(zip(columns, row)) for row in rows]
    return {"users": users}

# -------------------------------
# 🔹 Локальний запуск (dev)
# -------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
