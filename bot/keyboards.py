from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

def agree_kb():
    b = InlineKeyboardBuilder()
    b.button(text="✅ Погоджуюсь", callback_data="agree_rules")
    return b.as_markup()

def moderation_kb(post_id: int):
    b = InlineKeyboardBuilder()
    b.button(text="✅ Approve", callback_data=f"mod:approve:{post_id}")
    b.button(text="❌ Reject", callback_data=f"mod:reject:{post_id}")
    return b.as_markup()

def reject_reason_kb(post_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Відхилити без причини", callback_data=f"mod:reject_confirm:{post_id}:")]])
