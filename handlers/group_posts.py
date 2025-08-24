import aiosqlite
from aiogram import Router, F
from aiogram.types import Message

group_posts_router = Router()

DB_PATH = "database.db"


@group_posts_router.message(F.chat.type.in_({"group", "supergroup"}))
async def save_group_post(message: Message):
    text = message.text or ""
    photo_id = None

    # якщо є фото — беремо найбільше за розміром
    if message.photo:
        photo_id = message.photo[-1].file_id

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO posts (chat_id, chat_title, user_id, username, full_name, text, photo_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.chat.id,
                message.chat.title,
                message.from_user.id if message.from_user else None,
                message.from_user.username if message.from_user else None,
                message.from_user.full_name if message.from_user else None,
                text,
                photo_id,
            ),
        )
        await db.commit()

    print(f"✅ Saved post from {message.from_user.full_name}: {text[:30]}...")