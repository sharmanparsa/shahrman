import asyncio
import os

import asyncpg
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set!")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db_pool = None


async def create_tables():
    global db_pool

    db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=5
    )

    async with db_pool.acquire() as conn:

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS players (
                id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                level INTEGER DEFAULT 1,
                coins INTEGER DEFAULT 100,
                energy INTEGER DEFAULT 100,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cities (
                id SERIAL PRIMARY KEY,
                player_id BIGINT UNIQUE REFERENCES players(id) ON DELETE CASCADE,
                name TEXT DEFAULT 'شهر من',
                population INTEGER DEFAULT 1000,
                satisfaction INTEGER DEFAULT 70,
                economy INTEGER DEFAULT 50
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS resources (
                city_id INTEGER PRIMARY KEY REFERENCES cities(id) ON DELETE CASCADE,
                food INTEGER DEFAULT 500,
                materials INTEGER DEFAULT 300,
                water INTEGER DEFAULT 500
            );
        """)

    print("Database tables are ready!")


@dp.message(CommandStart())
async def start_handler(message: Message):

    user = message.from_user

    async with db_pool.acquire() as conn:

        player = await conn.fetchrow(
            "SELECT * FROM players WHERE id = $1",
            user.id
        )

        if player is None:

            await conn.execute("""
                INSERT INTO players
                (id, username, first_name)
                VALUES ($1, $2, $3)
            """,
                user.id,
                user.username,
                user.first_name
            )

            city_id = await conn.fetchval("""
                INSERT INTO cities (player_id)
                VALUES ($1)
                RETURNING id
            """, user.id)

            await conn.execute("""
                INSERT INTO resources (city_id)
                VALUES ($1)
            """, city_id)

            await message.answer(
                "🏙 شهر من\n\n"
                "🎉 به شهر خودت خوش اومدی!\n\n"
                "👑 از این لحظه تو شهردار این شهری.\n\n"
                "💰 سکه: 100\n"
                "⭐ سطح: 1\n"
                "⚡ انرژی: 100\n"
                "👥 جمعیت: 1000\n"
                "😊 رضایت مردم: 70٪\n\n"
                "🏗 حالا باید شهر خودت رو بسازی!"
            )

        else:

            await message.answer(
                "🏙 دوباره به شهرت خوش اومدی!\n\n"
                f"💰 سکه: {player['coins']}\n"
                f"⭐ سطح: {player['level']}\n"
                f"⚡ انرژی: {player['energy']}\n\n"
                "👑 شهردار، شهر منتظرته!"
            )


async def health_check(request):
    return web.Response(text="Shahr Man Bot is running!")


async def main():

    await create_tables()

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

        if db_pool:
            await db_pool.close()

        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
