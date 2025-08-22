from aiogram import Router, F
from aiogram.types import Message
from bot.texts import FAQ, CONTACTS

router = Router()

@router.message(F.text == "/faq")
async def faq(m: Message):
    await m.answer(FAQ)

@router.message(F.text == "/contacts")
async def contacts(m: Message):
    await m.answer(CONTACTS)
