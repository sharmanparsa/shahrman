import asyncio
import os

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set!")

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


async def health_check(request):
    return web.Response(text="Shahr Man Bot is running!")


async def main():
    # Web server for Render
    app = web.Application()
    app.router.add_get("/", health_check)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=PORT
    )

    await site.start()

    print(f"Web server running on port {PORT}")
    print("Bot is running...")

    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
