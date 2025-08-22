from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from app.repository import Repo
from bot.texts import RULES
from bot.keyboards import agree_kb

router = Router()
repo = Repo()

@router.message(F.text == "/start")
async def cmd_start(m: Message):
    u = await repo.get_or_create_user(m.from_user.id, m.from_user.username if m.from_user else None)
    if u.is_agreed:
        return await m.answer("Вітаю знову! Спробуйте /add щоб створити оголошення.")
    await m.answer(RULES, parse_mode="Markdown", reply_markup=agree_kb())

@router.callback_query(F.data == "agree_rules")
async def agree(cb: CallbackQuery):
    await repo.set_user_agreed(cb.from_user.id)
    await cb.message.edit_text("Дякуємо! Тепер ви можете створити оголошення командою /add.")
    await cb.answer()
