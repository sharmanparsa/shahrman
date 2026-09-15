import asyncio
import os

import asyncpg
from aiohttp import web

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

from dotenv import load_dotenv


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set!")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set!")


# =========================================================
# BOT
# =========================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

db_pool = None


# =========================================================
# BUILDINGS
# =========================================================

BUILDINGS = {

    "police": {
        "name": "👮 کلانتری",
        "cost": 100,
        "description": "افزایش امنیت شهر"
    },

    "fire": {
        "name": "🚒 آتش‌نشانی",
        "cost": 150,
        "description": "کاهش خطر آتش‌سوزی"
    },

    "hospital": {
        "name": "🏥 درمانگاه",
        "cost": 200,
        "description": "افزایش سلامت شهروندان"
    },

    "power": {
        "name": "⚡ نیروگاه",
        "cost": 250,
        "description": "تأمین برق شهر"
    },

    "water": {
        "name": "💧 تصفیه‌خانه آب",
        "cost": 200,
        "description": "تأمین آب شهر"
    },

    "school": {
        "name": "🏫 مدرسه",
        "cost": 180,
        "description": "افزایش آموزش و رضایت"
    },
}


# =========================================================
# DATABASE
# =========================================================

async def create_tables():

    global db_pool

    db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=5
    )

    async with db_pool.acquire() as conn:

        # -------------------------
        # PLAYERS
        # -------------------------

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS players (
                id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                level INTEGER NOT NULL DEFAULT 1,
                coins INTEGER NOT NULL DEFAULT 100,
                energy INTEGER NOT NULL DEFAULT 100,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)

        # -------------------------
        # CITIES
        # -------------------------

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cities (
                id SERIAL PRIMARY KEY,

                player_id BIGINT UNIQUE
                    REFERENCES players(id)
                    ON DELETE CASCADE,

                name TEXT NOT NULL DEFAULT 'شهر من',

                population INTEGER NOT NULL DEFAULT 1000,

                satisfaction INTEGER NOT NULL DEFAULT 70,

                economy INTEGER NOT NULL DEFAULT 50
            );
        """)

        # -------------------------
        # RESOURCES
        # -------------------------

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS resources (
                city_id INTEGER PRIMARY KEY
                    REFERENCES cities(id)
                    ON DELETE CASCADE,

                food INTEGER NOT NULL DEFAULT 500,

                materials INTEGER NOT NULL DEFAULT 300,

                water INTEGER NOT NULL DEFAULT 500
            );
        """)

        # -------------------------
        # BUILDINGS
        # -------------------------

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS buildings (

                city_id INTEGER
                    REFERENCES cities(id)
                    ON DELETE CASCADE,

                building_type TEXT NOT NULL,

                level INTEGER NOT NULL DEFAULT 0,

                PRIMARY KEY (city_id, building_type));
        """)

    print("Database tables are ready!")


# =========================================================
# MAIN MENU
# =========================================================

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


# =========================================================
# BACK BUTTON
# =========================================================

def back_button():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت",
                    callback_data="main_menu"
                )
            ]
        ]
    )


# =========================================================
# MAIN MENU HANDLER
# =========================================================

async def show_main_menu(callback: CallbackQuery):

    user_id = callback.from_user.id

    async with db_pool.acquire() as conn:

        player = await conn.fetchrow(
            """
            SELECT *
            FROM players
            WHERE id = $1
            """,
            user_id
        )

        city = await conn.fetchrow(
            """
            SELECT *
            FROM cities
            WHERE player_id = $1
            """,
            user_id
        )

    if not player or not city:

        await callback.answer(
            "❌ اطلاعات شهر پیدا نشد.",
            show_alert=True
        )

        return

    await callback.message.edit_text(

        "👑 اتاق شهردار\n\n"

        f"🏙 {city['name']}\n\n"

        f"👥 جمعیت: {city['population']:,}\n"
        f"😊 رضایت مردم: {city['satisfaction']}٪\n"
        f"📈 اقتصاد شهر: {city['economy']}٪\n\n"

        f"💰 سکه: {player['coins']}\n"
        f"⭐ سطح: {player['level']}\n"
        f"⚡ انرژی: {player['energy']}\n\n"

        "شهردار، شهر منتظر تصمیم توئه! 👑",

        reply_markup=main_menu()
    )


# =========================================================
# /START
# =========================================================

@dp.message(CommandStart())
async def start_handler(message: Message):

    user = message.from_user

    async with db_pool.acquire() as conn:

        player = await conn.fetchrow(
            """
            SELECT *
            FROM players
            WHERE id = $1
            """,
            user.id
        )

        # =================================================
        # NEW PLAYER
        # =================================================

        if player is None:

            async with conn.transaction():

                await conn.execute(
                    """
                    INSERT INTO players
                    (
                        id,
                        username,
                        first_name,
                        level,
                        coins,
                        energy
                    )
                    VALUES
                    (
                        $1,
                        $2,
                        $3,
                        1,
                        100,
                        100
                    )
                    """,

                    user.id,
                    user.username,
                    user.first_name
                )

                city_id = await conn.fetchval(
                    """
                    INSERT INTO cities
                    (
                        player_id,
                        name,
                        population,
                        satisfaction,
                        economy
                    )
                    VALUES
                    (
                        $1,
                        'شهر من',
                        1000,
                        70,
                        50
                    )
                    RETURNING id
                    """,

                    user.id
                )

                await conn.execute(
                    """
                    INSERT INTO resources
                    (
                        city_id,
                        food,
                        materials,
                        water
                    )
                    VALUES
                    (
                        $1,
                        500,
                        300,
                        500
                    )
                    """,

                    city_id
                )

            # دوباره اطلاعات بازیکن را می‌گیریم

            player = await conn.fetchrow(
                """
                SELECT *
                FROM players
                WHERE id = $1
                """,
                user.id
            )

            city = await conn.fetchrow(
                """
                SELECT *
                FROM cities
                WHERE player_id = $1
                """,
                user.id
            )

            await message.answer(

                "🎉 به شهر من خوش اومدی!\n\n"

                "👑 از این لحظه تو شهردار این شهری.\n\n"

                f"🏙 شهر: {city['name']}\n"
                f"👥 جمعیت: {city['population']:,}\n"
                f"😊 رضایت مردم: {city['satisfaction']}٪\n"
                f"📈 اقتصاد: {city['economy']}٪\n\n"

                f"💰 سکه: {player['coins']}\n"
                f"⭐ سطح: {player['level']}\n"
                f"⚡ انرژی: {player['energy']}\n\n"

                "🏗 حالا وقت ساختن شهرته!",

                reply_markup=main_menu()
            )

        # =================================================
        # OLD PLAYER
        # =================================================

        else:

            # اطلاعات کاربر را در صورت تغییر Username/Name به‌روز می‌کنیم

            await conn.execute(
                """
                UPDATE players
                SET username = $1,
                    first_name = $2
                WHERE id = $3
                """,

                user.username,
                user.first_name,
                user.id
            )

            city = await conn.fetchrow(
                """
                SELECT *
                FROM cities
                WHERE player_id = $1
                """,
                user.id
            )

            await message.answer(

                "👑 دوباره به شهرت خوش اومدی!\n\n"

                f"🏙 {city['name']}\n\n"

                f"👥 جمعیت: {city['population']:,}\n"
                f"😊 رضایت: {city['satisfaction']}٪\n"
                f"📈 اقتصاد: {city['economy']}٪\n\n"

                f"💰 سکه: {player['coins']}\n"
                f"⭐ سطح: {player['level']}\n"
                f"⚡ انرژی: {player['energy']}\n\n"

                "👑 شهردار، شهر منتظرته!",

                reply_markup=main_menu()
            )


# =========================================================
# MAIN MENU BUTTON
# =========================================================

@dp.callback_query(lambda c: c.data == "main_menu")
async def main_menu_handler(callback: CallbackQuery):

    await show_main_menu(callback)

    await callback.answer()


# =========================================================
# CITY
# =========================================================

@dp.callback_query(lambda c: c.data == "city")
async def city_handler(callback: CallbackQuery):

    user_id = callback.from_user.id

    async with db_pool.acquire() as conn:

        city = await conn.fetchrow(
            """
            SELECT *
            FROM cities
            WHERE player_id = $1
            """,
            user_id
        )

    if not city:

        await callback.answer(
            "❌ شهر پیدا نشد!",
            show_alert=True
        )

        return

    await callback.message.edit_text(

        f"🏙 {city['name']}\n\n"

        f"👥 جمعیت: {city['population']:,}\n\n"

        f"😊 رضایت مردم: {city['satisfaction']}٪\n\n"

        f"📈 اقتصاد شهر: {city['economy']}٪\n\n"

        "📊 وضعیت کلی شهر\n\n"

        "👑 تو شهردار این شهری.\n"
        "تصمیم‌های تو آینده شهر رو تعیین می‌کنن.",

        reply_markup=back_button()
    )

    await callback.answer()


# =========================================================
# RESOURCES
# =========================================================

@dp.callback_query(lambda c: c.data == "resources")
async def resources_handler(callback: CallbackQuery):

    user_id = callback.from_user.id

    async with db_pool.acquire() as conn:

        resources = await conn.fetchrow(
            """
            SELECT r.*
            FROM resources r

            JOIN cities c
            ON r.city_id = c.id

            WHERE c.player_id = $1
            """,

            user_id
        )

    if not resources:

        await callback.answer(
            "❌ منابع پیدا نشد!",
            show_alert=True
        )

        return

    await callback.message.edit_text(

        "📦 منابع شهر\n\n"

        f"🍞 غذا: {resources['food']:,}\n"
        f"🧱 مصالح: {resources['materials']:,}\n"
        f"💧 آب: {resources['water']:,}\n\n"

        "منابع در آینده با ساختمان‌ها، اقتصاد، "
        "جمعیت و بحران‌ها تغییر می‌کنن.",

        reply_markup=back_button()
    )

    await callback.answer()


# =========================================================
# PROFILE
# =========================================================

@dp.callback_query(lambda c: c.data == "profile")
async def profile_handler(callback: CallbackQuery):

    user_id = callback.from_user.id

    async with db_pool.acquire() as conn:

        player = await conn.fetchrow(
            """
            SELECT *
            FROM players
            WHERE id = $1
            """,
            user_id
        )

    if not player:

        await callback.answer(
            "❌ پروفایل پیدا نشد!",
            show_alert=True
        )

        return

    if player["username"]:

        username_text = f"@{player['username']}"

    else:

        username_text = "ندارد"

    await callback.message.edit_text(

        "👤 پروفایل شهردار\n\n"

        f"👤 نام: {player['first_name']}\n"
        f"🔹 نام کاربری: {username_text}\n\n"

        f"⭐ سطح: {player['level']}\n"
        f"💰 سکه: {player['coins']}\n"
        f"⚡ انرژی: {player['energy']}\n\n"

        "👑 شهردار شهر من",

        reply_markup=back_button()
    )

    await callback.answer()


# =========================================================
# BUILDINGS PAGE
# =========================================================

@dp.callback_query(lambda c: c.data == "buildings")
async def buildings_handler(callback: CallbackQuery):

    user_id = callback.from_user.id

    async with db_pool.acquire() as conn:

        city_id = await conn.fetchval(
            """
            SELECT id
            FROM cities
            WHERE player_id = $1
            """,

            user_id
        )

        if not city_id:

            await callback.answer(
                "❌ شهر پیدا نشد!",
                show_alert=True
            )

            return

        buildings = await conn.fetch(
            """
            SELECT building_type, level
            FROM buildings
            WHERE city_id = $1
            """,

            city_id
        )

    levels = {
        row["building_type"]: row["level"]
        for row in buildings
    }

    text = "🏗 ساختمان‌های شهر\n\n"

    buttons = []

    for key, building in BUILDINGS.items():

        level = levels.get(key, 0)

        # -----------------------------------------------
        # ساختمان ساخته نشده# -----------------------------------------------

        if level == 0:

            text += (
                f"{building['name']}\n"
                f"سطح: 0\n"
                f"💰 هزینه ساخت: {building['cost']} سکه\n"
                f"ℹ️ {building['description']}\n\n"
            )

            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"🏗 ساخت {building['name']}",
                        callback_data=f"build_{key}"
                    )
                ]
            )

        # -----------------------------------------------
        # ساختمان ساخته شده
        # -----------------------------------------------

        else:

            next_cost = building["cost"] * (level + 1)

            text += (
                f"{building['name']}\n"
                f"سطح: {level}\n"
                f"⬆️ هزینه ارتقا: {next_cost} سکه\n"
                f"ℹ️ {building['description']}\n\n"
            )

            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"⬆️ ارتقای {building['name']}",
                        callback_data=f"build_{key}"
                    )
                ]
            )

    buttons.append(
        [
            InlineKeyboardButton(
                text="🔙 بازگشت",
                callback_data="main_menu"
            )
        ]
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=buttons
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard
    )

    await callback.answer()


# =========================================================
# BUILD / UPGRADE BUILDING
# =========================================================

@dp.callback_query(lambda c: c.data.startswith("build_"))
async def build_handler(callback: CallbackQuery):

    user_id = callback.from_user.id

    building_key = callback.data.replace(
        "build_",
        "",
        1
    )

    # -----------------------------------------------
    # Check building
    # -----------------------------------------------

    if building_key not in BUILDINGS:

        await callback.answer(
            "❌ ساختمان پیدا نشد!",
            show_alert=True
        )

        return

    building = BUILDINGS[building_key]

    async with db_pool.acquire() as conn:

        async with conn.transaction():

            # -------------------------------------------
            # City
            # -------------------------------------------

            city_id = await conn.fetchval(
                """
                SELECT id
                FROM cities
                WHERE player_id = $1
                """,

                user_id
            )

            if not city_id:

                await callback.answer(
                    "❌ شهر پیدا نشد!",
                    show_alert=True
                )

                return

            # -------------------------------------------
            # Player
            # -------------------------------------------

            player = await conn.fetchrow(
                """
                SELECT coins
                FROM players
                WHERE id = $1
                FOR UPDATE
                """,

                user_id
            )

            if not player:

                await callback.answer(
                    "❌ بازیکن پیدا نشد!",
                    show_alert=True
                )

                return

            # -------------------------------------------
            # Current building level
            # -------------------------------------------

            current_level = await conn.fetchval(
                """
                SELECT level
                FROM buildings

                WHERE city_id = $1
                AND building_type = $2
                """,

                city_id,
                building_key
            )

            if current_level is None:

                current_level = 0

            # -------------------------------------------
            #New level
            # -------------------------------------------

            next_level = current_level + 1

            # -------------------------------------------
            # Cost
            # -------------------------------------------

            cost = building["cost"] * next_level

            # -------------------------------------------
            # Check money
            # -------------------------------------------

            if player["coins"] < cost:

                await callback.answer(
                    f"❌ سکه کافی نداری!\n\n"
                    f"💰 سکه فعلی: {player['coins']}\n"
                    f"💸 هزینه: {cost}",

                    show_alert=True
                )

                return

            # -------------------------------------------
            # Remove coins
            # -------------------------------------------

            await conn.execute(
                """
                UPDATE players

                SET coins = coins - $1

                WHERE id = $2
                """,

                cost,
                user_id
            )

            # -------------------------------------------
            # Save building
            # -------------------------------------------

            await conn.execute(
                """
                INSERT INTO buildings
                (
                    city_id,
                    building_type,
                    level
                )

                VALUES
                (
                    $1,
                    $2,
                    $3
                )

                ON CONFLICT
                (
                    city_id,
                    building_type
                )

                DO UPDATE SET
                    level = EXCLUDED.level
                """,

                city_id,
                building_key,
                next_level
            )

    # -----------------------------------------------
    # Success message
    # -----------------------------------------------

    action = "ساخته شد" if next_level == 1 else "ارتقا پیدا کرد"

    await callback.answer(
        f"✅ {building['name']}\n"
        f"سطح {next_level}\n"
        f"{action}!",
        show_alert=True
    )

    # نمایش دوباره ساختمان‌ها

    await buildings_handler(callback)


# =========================================================
# RENDER HEALTH CHECK
# =========================================================

async def health_check(request):

    return web.Response(
        text="Shahr Man Bot is running!"
    )


# =========================================================
# MAIN
# =========================================================

async def main():

    print("Starting Shahr Man...")

    # -----------------------------------------------
    # Database
    # -----------------------------------------------

    await create_tables()

    print("Database connected successfully!")

    # -----------------------------------------------
    # Web server for Render
    # -----------------------------------------------

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

    print(
        f"Web server running on port {PORT}"
    )

    print("Bot is running!")

    # -----------------------------------------------
    # Start bot
    # -----------------------------------------------

    try:

        await dp.start_polling(bot)

    finally:

        await runner.cleanup()

        if db_pool:

            await db_pool.close()

        await bot.session.close()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    asyncio.run(main())
