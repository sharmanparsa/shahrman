import asyncio
import os

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        "🏙 به شهر من خوش اومدی!\n\n"
        "تو تازه وارد این شهر شدی.\n\n"
        "💰 موجودی: 100 سکه\n"
        "⭐ سطح: 1\n"
        "⚡ انرژی: 100\n\n"
        "🎮 به‌زودی وارد شهرت می‌شیم!"
    )


async def main():
    print("Bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())