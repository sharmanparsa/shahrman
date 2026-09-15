import asyncio
import os

import asyncpg
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
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


# =========================
# DATABASE
# =========================

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
                player_id BIGINT UNIQUE
                    REFERENCES players(id)
                    ON DELETE CASCADE,
                name TEXT DEFAULT 'شهر من',
                population INTEGER DEFAULT 1000,
                satisfaction INTEGER DEFAULT 70,
                economy INTEGER DEFAULT 50
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS resources (
                city_id INTEGER PRIMARY KEY
                    REFERENCES cities(id)
                    ON DELETE CASCADE,
                food INTEGER DEFAULT 500,
                materials INTEGER DEFAULT 300,
                water INTEGER DEFAULT 500
            );
        """)

    print("Database tables are ready!")


# =========================
# MAIN MENU
# =========================

def main_menu():

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏙 شهر من",
                    callback_data="city"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏗 ساختمان‌ها",
                    callback_data="buildings"
                ),
                InlineKeyboardButton(
                    text="📦 منابع",
                    callback_data="resources"
                )
            ],
            [
                InlineKeyboardButton(
                    text="👤 پروفایل",
                    callback_data="profile"
                )
            ]
        ]
    )

    return keyboard


# =========================
# START
# =========================

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

            player = await conn.fetchrow(
                "SELECT * FROM players WHERE id = $1",
                user.id
            )

    await message.answer(
        "👑 اتاق شهردار\n\n"
        "🏙 به شهرخودت خوش اومدی، شهردار!\n\n"
        f"💰 سکه: {player['coins']}\n"
        f"⭐ سطح: {player['level']}\n"
        f"⚡ انرژی: {player['energy']}\n\n"
        "از منوی پایین شهر رو مدیریت کن:",
        reply_markup=main_menu()
    )


# =========================
# CITY
# =========================

@dp.callback_query(lambda c: c.data == "city")
async def city_handler(callback):

    user_id = callback.from_user.id

    async with db_pool.acquire() as conn:

        city = await conn.fetchrow("""
            SELECT *
            FROM cities
            WHERE player_id = $1
        """, user_id)

    if city:

        await callback.message.edit_text(
            f"🏙 {city['name']}\n\n"
            f"👥 جمعیت: {city['population']:,}\n"
            f"😊 رضایت مردم: {city['satisfaction']}٪\n"
            f"📈 اقتصاد شهر: {city['economy']}٪\n\n"
            "👑 شهردار، این شهر الان تحت مدیریت توئه."
        )

    await callback.answer()


# =========================
# RESOURCES
# =========================

@dp.callback_query(lambda c: c.data == "resources")
async def resources_handler(callback):

    user_id = callback.from_user.id

    async with db_pool.acquire() as conn:

        resources = await conn.fetchrow("""
            SELECT r.*
            FROM resources r
            JOIN cities c
            ON r.city_id = c.id
            WHERE c.player_id = $1
        """, user_id)

    if resources:

        await callback.message.edit_text(
            "📦 منابع شهر\n\n"
            f"🍞 غذا: {resources['food']}\n"
            f"🧱 مصالح: {resources['materials']}\n"
            f"💧 آب: {resources['water']}\n\n"
            "منابع شهر در آینده با ساختمان‌ها، اقتصاد "
            "و اتفاقات مختلف تغییر می‌کنند."
        )

    await callback.answer()


# =========================
# PROFILE
# =========================

@dp.callback_query(lambda c: c.data == "profile")
async def profile_handler(callback):

    user_id = callback.from_user.id

    async with db_pool.acquire() as conn:

        player = await conn.fetchrow("""
            SELECT *
            FROM players
            WHERE id = $1
        """, user_id)

    if player:

        username = player["username"]

        if username:
            username_text = f"@{username}"
        else:
            username_text = "ندارد"

        await callback.message.edit_text(
            "👤 پروفایل شهردار\n\n"
            f"🆔 آیدی: {user_id}\n"
            f"👤 نام کاربری: {username_text}\n"
            f"⭐ سطح: {player['level']}\n"
            f"💰 سکه: {player['coins']}\n"
            f"⚡ انرژی: {player['energy']}"
        )

    await callback.answer()


# =========================
# BUILDINGS
# =========================

@dp.callback_query(lambda c: c.data == "buildings")
async def buildings_handler(callback):

    await callback.message.edit_text(
        "🏗 ساختمان‌های شهر\n\n"
        "🚧 هنوز هیچ ساختمانی ساخته نشده.\n\n"
        "به‌زودی می‌تونی ساختمان‌هایی مثل:\n"
        "👮 پلیس\n"
        "🚒 آتش‌نشانی\n"
        "🏥 بیمارستان\n"
        "⚡ نیروگاه\n"
        "💧 تصفیه‌خانه آب\n"
        "🏫 مدرسه\n"
        "🌳 پارک\n"
        "🏟 ورزشگاه\n"
        "و خیلی چیزهای دیگه بسازی."
    )

    await callback.answer()


# =========================
# HEALTH CHECK
# =========================

async def health_check(request):

    return web.Response(
        text="Shahr Man Bot is running!"
    )


# =========================
# MAIN
# =========================

async def main():

    await create_tables()

    app = web.Application()

    app.router.add_get(
        "/",
        health_check
    )

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
