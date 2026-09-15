import asyncio
import logging
import os
import random
from datetime import datetime, timedelta, timezone

import asyncpg
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv


# =========================================================
# SETTINGS
# =========================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing")

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

db_pool = None


# =========================================================
# GAME CONSTANTS
# =========================================================

START_COINS = 1000
START_FOOD = 500
START_MATERIALS = 300
START_ENERGY = 500
START_WATER = 500
START_EQUIPMENT = 20

START_POPULATION = 100
START_JOBS = 50
START_SATISFACTION = 70
START_ECONOMY = 50

MAX_SATISFACTION = 100
MAX_LEVEL = 30


# =========================================================
# BUILDINGS
# =========================================================

BUILDINGS = {
    "police": {
        "name": "🚓 کلانتری",
        "cost": 350,
        "material": 100,
        "base_effect": {"security": 8},
        "maintenance": 8,
        "description": "امنیت شهر را افزایش می‌دهد.",
    },
    "fire": {
        "name": "🚒 ایستگاه آتش‌نشانی",
        "cost": 400,
        "material": 120,
        "base_effect": {"fire_safety": 10},
        "maintenance": 9,
        "description": "احتمال و شدت آتش‌سوزی را کاهش می‌دهد.",
    },
    "hospital": {
        "name": "🏥 بیمارستان",
        "cost": 500,
        "material": 150,
        "base_effect": {"health": 12},
        "maintenance": 12,
        "description": "سلامت شهروندان را افزایش می‌دهد.",
    },
    "power": {
        "name": "⚡ نیروگاه",
        "cost": 550,
        "material": 180,
        "base_effect": {"power": 15},
        "maintenance": 14,
        "description": "ظرفیت برق شهر را افزایش می‌دهد.",
    },
    "water": {
        "name": "💧 تصفیه‌خانه آب",
        "cost": 500,
        "material": 160,
        "base_effect": {"water": 15},
        "maintenance": 12,
        "description": "آب سالم و پایدار برای شهر.",
    },
    "school": {
        "name": "🏫 مدرسه",
        "cost": 450,
        "material": 130,
        "base_effect": {"education": 10},
        "maintenance": 9,
        "description": "آموزش و کیفیت نیروی انسانی.",
    },
    "university": {
        "name": "🎓 دانشگاه",
        "cost": 800,
        "material": 250,
        "base_effect": {"education": 18, "economy": 5},
        "maintenance": 18,
        "description": "اقتصاد و آموزش پیشرفته.",
    },
    "park": {
        "name": "🌳 پارک",
        "cost": 300,
        "material": 80,
        "base_effect": {"recreation": 12, "pollution_control": 5},
        "maintenance": 5,
        "description": "تفریح و کاهش آلودگی.",
    },
    "shopping": {
        "name": "🛍️ مرکز خرید",
        "cost": 700,
        "material": 220,
        "base_effect": {"economy": 12, "jobs": 15},
        "maintenance": 12,
        "description": "افزایش اشتغال و اقتصاد.",
    },
    "stadium": {
        "name": "🏟️ ورزشگاه",
        "cost": 1000,
        "material": 300,
        "base_effect": {"recreation": 20, "economy": 5, "jobs": 20},
        "maintenance": 20,
        "description": "تفریح، اشتغال و اقتصاد.",
    },
    "recycling": {
        "name": "♻️ مرکز بازیافت",
        "cost": 600,
        "material": 200,
        "base_effect": {"pollution_control": 18},
        "maintenance": 12,
        "description": "کنترل آلودگی و زباله.",
    },
    "emergency": {
        "name": "🚑 مرکز اورژانس",
        "cost": 750,
        "material": 220,
        "base_effect": {"crisis": 15, "health": 8},
        "maintenance":15,
        "description": "سرعت واکنش به بحران‌ها.",
    },
    "roads": {
        "name": "🛣️ اداره راه",
        "cost": 650,
        "material": 250,
        "base_effect": {"infrastructure": 15, "jobs": 10},
        "maintenance": 15,
        "description": "زیرساخت و حمل‌ونقل.",
    },
    "waste": {
        "name": "🗑️ مدیریت پسماند",
        "cost": 450,
        "material": 150,
        "base_effect": {"pollution_control": 12},
        "maintenance": 9,
        "description": "مدیریت زباله و پاکیزگی.",
    },
    "industry": {
        "name": "🏭 منطقه صنعتی",
        "cost": 900,
        "material": 300,
        "base_effect": {"economy": 20, "jobs": 35, "pollution": 8},
        "maintenance": 20,
        "description": "اقتصاد و اشتغال زیاد، اما آلودگی بیشتر.",
    },
}


# =========================================================
# CRISES
# =========================================================

CRISES = {
    "theft": {
        "name": "🚨 موج سرقت",
        "stat": "security",
        "base_severity": 55,
        "reward": 120,
        "satisfaction_loss": 8,
        "resource": "coins",
    },
    "fire": {
        "name": "🔥 آتش‌سوزی",
        "stat": "fire_safety",
        "base_severity": 60,
        "reward": 150,
        "satisfaction_loss": 10,
        "resource": "water",
    },
    "disease": {
        "name": "🦠 شیوع بیماری",
        "stat": "health",
        "base_severity": 65,
        "reward": 180,
        "satisfaction_loss": 12,
        "resource": "coins",
    },
    "power": {
        "name": "⚡ قطعی برق",
        "stat": "power",
        "base_severity": 60,
        "reward": 150,
        "satisfaction_loss": 9,
        "resource": "energy",
    },
    "water": {
        "name": "💧 بحران آب",
        "stat": "water",
        "base_severity": 60,
        "reward": 150,
        "satisfaction_loss": 9,
        "resource": "water",
    },
    "pollution": {
        "name": "🌫️ آلودگی شدید",
        "stat": "pollution_control",
        "base_severity": 50,
        "reward": 130,
        "satisfaction_loss": 7,
        "resource": "coins",
    },
    "storm": {
        "name": "🌪️ طوفان شدید",
        "stat": "infrastructure",
        "base_severity": 70,
        "reward": 220,
        "satisfaction_loss": 12,
        "resource": "materials",
    },
    "snow": {
        "name": "❄️ برف سنگین",
        "stat": "infrastructure",
        "base_severity": 55,
        "reward": 150,
        "satisfaction_loss": 8,
        "resource": "materials",
    },
    "heat": {
        "name": "☀️ موج گرما",
        "stat": "power",
        "base_severity": 55,
        "reward": 150,
        "satisfaction_loss": 8,
        "resource": "energy",
    },
    "garbage": {
        "name": "🗑️ بحران زباله",
        "stat": "pollution_control",
        "base_severity": 50,
        "reward": 120,
        "satisfaction_loss": 7,
        "resource": "materials",
    },
    "accident": {
        "name": "🚑 حادثه بزرگ",
        "stat": "crisis",
        "base_severity": 65,
        "reward": 190,
        "satisfaction_loss": 10,
        "resource": "coins",
    },
    "economic": {
        "name": "📉 بحران اقتصادی",
        "stat": "economy",
        "base_severity": 65,
        "reward": 250,
        "satisfaction_loss": 12,
        "resource": "coins",
    },
    "flood": {
        "name": "🌊 سیل",
        "stat": "infrastructure",
        "base_severity": 72,
        "reward": 230,
        "satisfaction_loss": 13,
        "resource": "materials",
    },
    "infrastructure": {
        "name": "🏚️ خرابی زیرساخت",
        "stat": "infrastructure",
        "base_severity": 62,
        "reward": 200,
        "satisfaction_loss": 10,
        "resource": "materials",
    },
    "cold": {
        "name": "🥶 سرمای شدید",
        "stat": "power",
        "base_severity": 60,
        "reward": 170,
        "satisfaction_loss": 9,
        "resource": "energy",
    },
}


# =========================================================
# HELPERS
# =========================================================

def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def now_utc():
    return datetime.now(timezone.utc)


def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🏙️ شهر من", callback_data="city"),
                InlineKeyboardButton(text="👑 شهردار", callback_data="mayor"),
            ],
            [
                InlineKeyboardButton(text="🏗️ ساختمان‌ها", callback_data="buildings"),
                InlineKeyboardButton(text="📦 منابع", callback_data="resources"),
            ],
            [
                InlineKeyboardButton(text="💰 اقتصاد", callback_data="economy"),
                InlineKeyboardButton(text="🚨 بحران‌ها", callback_data="crises"),
            ],
            [
                InlineKeyboardButton(text="🤝 اجتماعی", callback_data="social"),
                InlineKeyboardButton(text="🏆 رقابت", callback_data="ranking"),
            ],
            [
                InlineKeyboardButton(text="🏪 بازار", callback_data="market"),
                InlineKeyboardButton(text="👥 گروه‌ها", callback_data="groups"),
            ],
            [
                InlineKeyboardButton(text="📰 روزنامه شهر", callback_data="news"),
                InlineKeyboardButton(text="🗺️ توسعه شهر", callback_data="expansion"),
            ],
        ]
    )


def back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu")]
        ]
    )


def building_keyboard():
    rows = []

    for key, data in BUILDINGS.items():
        rows.append(
            [
                InlineKeyboardButton(
                    text=data["name"],
                    callback_data=f"building:{key}",
                )
            ]
        )

    rows.append(
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu")]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def crisis_keyboard(crisis_id):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🛠️ حل بحران",
                    callback_data=f"resolve:{crisis_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت",
                    callback_data="crises",
                )
            ],
        ]
    )


# =========================================================
# DATABASE
# =========================================================

async def init_db():
    global db_pool

    db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=5,
        command_timeout=30,
    )

    async with db_pool.acquire() as conn:

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS players (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cities (
                user_id BIGINT PRIMARY KEY REFERENCES players(user_id) ON DELETE CASCADE,
                city_name TEXT DEFAULT 'شهر من',
                population INTEGER DEFAULT 100,
                jobs INTEGER DEFAULT 50,
                satisfaction INTEGER DEFAULT 70,
                economy INTEGER DEFAULT 50,
                security INTEGER DEFAULT 0,
                fire_safety INTEGER DEFAULT 0,
                health INTEGER DEFAULT 0,
                power INTEGER DEFAULT 0,
                water INTEGER DEFAULT 0,
                education INTEGER DEFAULT 0,
                recreation INTEGER DEFAULT 0,
                pollution_control INTEGER DEFAULT 0,
                infrastructure INTEGER DEFAULT 0,
                crisis INTEGER DEFAULT 0,
                tax_rate INTEGER DEFAULT 10,
                housing_capacity INTEGER DEFAULT 150,
                land INTEGER DEFAULT 1,
                villages INTEGER DEFAULT 0,
                city_level INTEGER DEFAULT 1,
                last_tick TIMESTAMPTZ DEFAULT NOW(),
                last_income TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        migration_columns = {
            "city_name": "TEXT DEFAULT 'شهر من'",
            "security": "INTEGER DEFAULT 0",
            "fire_safety": "INTEGER DEFAULT 0",
            "health": "INTEGER DEFAULT 0",
            "power": "INTEGER DEFAULT 0",
            "water": "INTEGER DEFAULT 0",
            "education": "INTEGER DEFAULT 0",
            "recreation": "INTEGER DEFAULT 0",
            "pollution_control": "INTEGER DEFAULT 0",
            "infrastructure": "INTEGER DEFAULT 0",
            "crisis": "INTEGER DEFAULT 0",
            "tax_rate": "INTEGER DEFAULT 10",
            "housing_capacity": "INTEGER DEFAULT 150",
            "land": "INTEGER DEFAULT 1",
            "villages": "INTEGER DEFAULT 0",
            "city_level": "INTEGER DEFAULT 1",
            "last_tick": "TIMESTAMPTZ DEFAULT NOW()",
            "last_income": "TIMESTAMPTZ DEFAULT NOW()",
        }

        for column, definition in migration_columns.items():
            try:
                await conn.execute(
                    f"ALTER TABLE cities ADD COLUMN IF NOT EXISTS {column} {definition}"
                )
            except Exception:
                logging.exception("Migration error for %s", column)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS resources (
                user_id BIGINT PRIMARY KEY REFERENCES players(user_id) ON DELETE CASCADE,
                coins INTEGER DEFAULT 1000,
                food INTEGER DEFAULT 500,
                materials INTEGER DEFAULT 300,
                energy INTEGER DEFAULT 500,
                water INTEGER DEFAULT 500,
                equipment INTEGER DEFAULT 20
            )
        """)

        try:
            await conn.execute(
                "ALTER TABLE resources ADD COLUMN IF NOT EXISTS equipment INTEGER DEFAULT 20"
            )
        except Exception:
            pass

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS buildings (
                user_id BIGINT REFERENCES players(user_id) ON DELETE CASCADE,
                building_type TEXT,
                level INTEGER DEFAULT 0,
                PRIMARY KEY(user_id, building_type)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS crises (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES players(user_id) ON DELETE CASCADE,
                crisis_type TEXT NOT NULL,
                severity INTEGER NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                resolved_at TIMESTAMPTZ
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES players(user_id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS aid_logs (
                id SERIAL PRIMARY KEY,
                sender_id BIGINT,
                receiver_id BIGINT,
                coins INTEGER DEFAULT 0,
                food INTEGER DEFAULT 0,
                materials INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                owner_id BIGINT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_members (
                group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,
                user_id BIGINT REFERENCES players(user_id) ON DELETE CASCADE,
                joined_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY(group_id, user_id)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS weekly_scores (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES players(user_id) ON DELETE CASCADE,
                week_key TEXT NOT NULL,
                score INTEGER DEFAULT 0,
                claimed BOOLEAN DEFAULT FALSE,
                UNIQUE(user_id, week_key)
            )
        """)

        # Friends
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS friend_requests (
                id SERIAL PRIMARY KEY,
                sender_id BIGINT REFERENCES players(user_id) ON DELETE CASCADE,
                receiver_id BIGINT REFERENCES players(user_id) ON DELETE CASCADE,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(sender_id, receiver_id)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS friendships (
                user_id BIGINT REFERENCES players(user_id) ON DELETE CASCADE,
                friend_id BIGINT REFERENCES players(user_id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY(user_id, friend_id)
            )
        """)

        # Market
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS market_offers (
                id SERIAL PRIMARY KEY,
                seller_id BIGINT REFERENCES players(user_id) ON DELETE CASCADE,
                resource_type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                price INTEGER NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Group challenges
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_challenges (
                id SERIAL PRIMARY KEY,
                group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,
                creator_id BIGINT REFERENCES players(user_id) ON DELETE CASCADE,
                challenge_type TEXT NOT NULL,
                target INTEGER NOT NULL,
                progress INTEGER DEFAULT 0,
                reward INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                completed_at TIMESTAMPTZ
            )
        """)

        # Weekly seasons
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS weekly_seasons (
                week_key TEXT PRIMARY KEY,
                started_at TIMESTAMPTZ DEFAULT NOW(),
                ended BOOLEAN DEFAULT FALSE
            )
        """)


# =========================================================
# PLAYER
# =========================================================

async def ensure_player(message: Message):
    user = message.from_user

    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO players(user_id, username, first_name)
            VALUES($1, $2, $3)
            ON CONFLICT(user_id)
            DO UPDATE SET username=$2, first_name=$3
        """, user.id, user.username, user.first_name or "")

        await conn.execute("""
            INSERT INTO cities(user_id)
            VALUES($1)
            ON CONFLICT(user_id) DO NOTHING
        """, user.id)

        await conn.execute("""
            INSERT INTO resources(user_id)
            VALUES($1)
            ON CONFLICT(user_id) DO NOTHING
        """, user.id)

    return user.id


async def get_player(user_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM players WHERE user_id=$1",
            user_id,
        )


async def get_city(user_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM cities WHERE user_id=$1",
            user_id,
        )


async def get_resources(user_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM resources WHERE user_id=$1",
            user_id,
        )


# =========================================================
# XP
# =========================================================

async def add_xp(user_id, amount):
    async with db_pool.acquire() as conn:
        player = await conn.fetchrow(
            "SELECT xp, level FROM players WHERE user_id=$1 FOR UPDATE",
            user_id,
        )

        if not player:
            return

        xp = player["xp"] + amount
        level = player["level"]

        required = level * 250

        while xp >= required and level < MAX_LEVEL:
            xp -= required
            level += 1
            required = level * 250

        await conn.execute("""
            UPDATE players
            SET xp=$1, level=$2
            WHERE user_id=$3
        """, xp, level, user_id)


# =========================================================
# CITY CALCULATION
# =========================================================

async def recalculate_city(user_id):
    async with db_pool.acquire() as conn:

        city = await conn.fetchrow(
            "SELECT * FROM cities WHERE user_id=$1",
            user_id,
        )

        if not city:
            return

        rows = await conn.fetch("""
            SELECT building_type, level
            FROM buildings
            WHERE user_id=$1
        """, user_id)

        stats = {
            "security": 0,
            "fire_safety": 0,
            "health": 0,
            "power": 0,
            "water": 0,
            "education": 0,
            "recreation": 0,
            "pollution_control": 0,
            "infrastructure": 0,
            "crisis": 0,
        }

        economy_bonus = 0
        job_bonus = 0
        pollution = 0
        housing_bonus = 0

        for row in rows:
            building = BUILDINGS.get(row["building_type"])

            if not building:
                continue

            level = row["level"]

            for stat, effect in building["base_effect"].items():

                value = effect * level

                if stat in stats:
                    stats[stat] += value
                elif stat == "economy":
                    economy_bonus += value
                elif stat == "jobs":
                    job_bonus += value
                elif stat == "pollution":
                    pollution += value

            if row["building_type"] == "school":
                housing_bonus += level * 10

            elif row["building_type"] == "university":
                housing_bonus += level * 20

            elif row["building_type"] == "roads":
                housing_bonus += level * 20

        pollution_net = max(
            0,
            pollution - stats["pollution_control"]
        )

        economy = clamp(
            50
            + economy_bonus
            + stats["education"] // 4
            + city["population"] // 200
            - pollution_net // 3,
            0,
            100,
        )

        housing = 150 + city["land"] * 100 + housing_bonus

        jobs = max(
            20,
            50 + job_bonus + city["population"] // 3
        )

        satisfaction = (
            45
            + stats["security"] // 8
            + stats["fire_safety"] // 8
            + stats["health"] // 8
            + stats["power"] // 8
            + stats["water"] // 8
            + stats["education"] // 10
            + stats["recreation"] // 10
            + stats["infrastructure"] // 10
            - pollution_net // 3
            - max(0, city["population"] - housing) // 20
            - max(0, city["tax_rate"] - 10) * 2
        )

        satisfaction = clamp(satisfaction, 0, 100)

        await conn.execute("""
            UPDATE cities
            SET
                security=$1,
                fire_safety=$2,
                health=$3,
                power=$4,
                water=$5,
                education=$6,recreation=$7,
                pollution_control=$8,
                infrastructure=$9,
                crisis=$10,
                economy=$11,
                jobs=$12,
                satisfaction=$13,
                housing_capacity=$14
            WHERE user_id=$15
        """,
            stats["security"],
            stats["fire_safety"],
            stats["health"],
            stats["power"],
            stats["water"],
            stats["education"],
            stats["recreation"],
            stats["pollution_control"],
            stats["infrastructure"],
            stats["crisis"],
            economy,
            jobs,
            satisfaction,
            housing,
            user_id,
        )


# =========================================================
# INCOME
# =========================================================

async def collect_income(user_id):
    await recalculate_city(user_id)

    async with db_pool.acquire() as conn:

        city = await conn.fetchrow(
            "SELECT * FROM cities WHERE user_id=$1 FOR UPDATE",
            user_id,
        )

        if not city:
            return 0

        last_income = city["last_income"]

        if last_income is None:
            last_income = now_utc()

        elapsed = now_utc() - last_income

        # Income is collected at most once every 30 minutes.
        if elapsed < timedelta(minutes=25):
            return 0

        periods = max(
            1,
            int(elapsed.total_seconds() // 1800)
        )

        periods = min(periods, 8)

        tax_income = int(
            city["population"]
            * city["tax_rate"]
            * max(city["satisfaction"], 20)
            / 10000
        )

        economic_income = city["economy"] * 2

        base_income = max(
            10,
            tax_income + economic_income
        )

        maintenance = 0

        rows = await conn.fetch("""
            SELECT building_type, level
            FROM buildings
            WHERE user_id=$1
        """, user_id)

        for row in rows:
            data = BUILDINGS.get(row["building_type"])

            if data:
                maintenance += data["maintenance"] * row["level"]

        final_income = (base_income - maintenance) * periods

        await conn.execute("""
            UPDATE resources
            SET coins=GREATEST(0, coins+$1)
            WHERE user_id=$2
        """, final_income, user_id)

        await conn.execute("""
            UPDATE cities
            SET last_income=NOW()
            WHERE user_id=$1
        """, user_id)

        return final_income


# =========================================================
# CITY DASHBOARD
# =========================================================

async def city_text(user_id):
    await recalculate_city(user_id)

    city = await get_city(user_id)
    player = await get_player(user_id)

    if not city:
        return "❌ اطلاعات شهر پیدا نشد."

    return f"""
🏙️ <b>{city['city_name']}</b>

👑 شهردار: {player['first_name']}

⭐ سطح شهردار: {player['level']}
✨ XP: {player['xp']}

👥 جمعیت: {city['population']:,}
💼 شغل‌ها: {city['jobs']:,}
😊 رضایت: {city['satisfaction']}%
📈 اقتصاد: {city['economy']}%

🏠 ظرفیت مسکن: {city['housing_capacity']:,}
🗺️ زمین: {city['land']}
🏘️ روستاهای جذب‌شده: {city['villages']}

💰 مالیات: {city['tax_rate']}%
"""


# =========================================================
# START
# =========================================================

@dp.message(Command("start"))
async def start_handler(message: Message):
    user_id = await ensure_player(message)

    await process_player_tick(user_id)
    await collect_income(user_id)

    text = await city_text(user_id)

    await message.answer(
        "🏙️ <b>به شهر من خوش اومدی!</b>\n\n"
        "تو شهردار یک شهر کوچک هستی.\n"
        "شهر رو بساز، اقتصاد رو رشد بده، بحران‌ها رو مدیریت کن "
        "و با شهرداران دیگر رقابت کن.\n\n"
        + text,
        reply_markup=main_keyboard(),
    )


# =========================================================
# MENU
# =========================================================

@dp.callback_query(F.data == "menu")
async def menu_callback(callback: CallbackQuery):
    await callback.answer()

    await callback.message.edit_text(
        "🏙️ <b>شهر من</b>\n\n"
        "شهردار، شهر آماده‌ی مدیریت توئه!",
        reply_markup=main_keyboard(),
    )


# =========================================================
# CITY
# =========================================================

@dp.callback_query(F.data == "city")
async def city_callback(callback: CallbackQuery):
    await callback.answer()

    await process_player_tick(callback.from_user.id)

    await callback.message.edit_text(
        await city_text(callback.from_user.id),
        reply_markup=back_keyboard(),
    )


# =========================================================
# MAYOR
# =========================================================

@dp.callback_query(F.data == "mayor")
async def mayor_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id

    player = await get_player(user_id)
    city = await get_city(user_id)

    text = f"""
👑 <b>دفتر شهردار</b>

👤 {player['first_name']}

🏙️ شهر: {city['city_name']}

⭐ سطح: {player['level']}
✨ XP: {player['xp']}

😊 رضایت: {city['satisfaction']}%

📊 وضعیت خدمات:

🚓 امنیت: {city['security']}
🚒 ایمنی آتش: {city['fire_safety']}
🏥 سلامت: {city['health']}
⚡ برق: {city['power']}
💧 آب: {city['water']}
🎓 آموزش: {city['education']}
🌳 تفریح: {city['recreation']}
🛣️ زیرساخت: {city['infrastructure']}
♻️ کنترل آلودگی: {city['pollution_control']}
🚑 مدیریت بحران: {city['crisis']}
"""

    await callback.message.edit_text(
        text,
        reply_markup=back_keyboard(),
    )


# =========================================================
# BUILDINGS
# =========================================================

@dp.callback_query(F.data == "buildings")
async def buildings_callback(callback: CallbackQuery):
    await callback.answer()

    await callback.message.edit_text(
        "🏗️ <b>ساختمان‌های شهر</b>\n\n"
        "یک ساختمان را انتخاب کن تا سطح و هزینه‌ی ساخت/ارتقا را ببینی.",
        reply_markup=building_keyboard(),
    )


@dp.callback_query(F.data.startswith("building:"))
async def building_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    key = callback.data.split(":", 1)[1]

    data = BUILDINGS.get(key)

    if not data:
        await callback.answer("ساختمان پیدا نشد.", show_alert=True)
        return

    async with db_pool.acquire() as conn:

        async with conn.transaction():

            current = await conn.fetchval("""
                SELECT level
                FROM buildings
                WHERE user_id=$1 AND building_type=$2
                FOR UPDATE
            """, user_id, key)

            current = current or 0
            next_level = current + 1

            cost = int(data["cost"] * (1 + current * 0.45))
            material = int(data["material"] * (1 + current * 0.45))

            resources = await conn.fetchrow("""
                SELECT coins, materials
                FROM resources
                WHERE user_id=$1
                FOR UPDATE
            """, user_id)

            action = "ساخت" if current == 0 else "ارتقا"

            text = f"""
{data['name']}

📖 {data['description']}

📊 سطح فعلی: {current}
⬆️ سطح بعدی: {next_level}

💰 هزینه: {cost:,} سکه
🧱 مصالح: {material:,}
"""

            if resources["coins"] < cost or resources["materials"] < material:
                text += f"\n❌ برای {action} منابع کافی نداری."

                await callback.message.edit_text(
                    text,
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="🔙 ساختمان‌ها",
                                    callback_data="buildings",
                                )
                            ]
                        ]
                    ),
                )
                return

            await conn.execute("""
                UPDATE resources
                SET
                    coins=coins-$1,
                    materials=materials-$2
                WHERE user_id=$3
            """, cost, material, user_id)

            await conn.execute("""
                INSERT INTO buildings(user_id, building_type, level)
                VALUES($1,$2,1)
                ON CONFLICT(user_id, building_type)
                DO UPDATE SET level=buildings.level+1
            """, user_id, key)

            await conn.execute("""
                INSERT INTO news(user_id,text)
                VALUES($1,$2)
            """,
                user_id,
                f"{data['name']} به سطح {next_level} رسید.",
            )

    await add_xp(user_id, 40)
    await recalculate_city(user_id)

    await callback.answer("ساختمان با موفقیت ارتقا یافت.")

    await callback.message.edit_text(
        text
        + f"\n\n✅ {action} با موفقیت انجام شد!"
        + f"\n🏗️ سطح جدید: {next_level}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🏗️ ساختمان‌ها",
                        callback_data="buildings",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 منو",
                        callback_data="menu",
                    )
                ],
            ]
        ),
    )


# =========================================================
# RESOURCES
# =========================================================

@dp.callback_query(F.data == "resources")
async def resources_callback(callback: CallbackQuery):
    await callback.answer()

    resources = await get_resources(callback.from_user.id)

    text = f"""
📦 <b>منابع شهر</b>

💰 سکه: {resources['coins']:,}
🍞 غذا: {resources['food']:,}
🧱 مصالح: {resources['materials']:,}
⚡ انرژی: {resources['energy']:,}
💧 آب: {resources['water']:,}
🧰 تجهیزات: {resources['equipment']:,}

منابع برای توسعه، بازار، کمک به شهرهای دیگر و مدیریت بحران‌ها استفاده می‌شوند.
"""

    await callback.message.edit_text(
        text,
        reply_markup=back_keyboard(),
    )


# =========================================================
# ECONOMY
# =========================================================

async def economy_screen(callback):
    user_id = callback.from_user.id

    await recalculate_city(user_id)

    income = await collect_income(user_id)

    city = await get_city(user_id)
    resources = await get_resources(user_id)

    text = f"""
💰 <b>اقتصاد شهر</b>

📈 قدرت اقتصادی: {city['economy']}%

💵 درآمد دریافت‌شده: {income:,} سکه

💰 موجودی: {resources['coins']:,} سکه

👥 جمعیت: {city['population']:,}
💼 شغل‌ها: {city['jobs']:,}

🏷️ مالیات: {city['tax_rate']}%

مالیات بیشتر درآمد را بالا می‌برد،
اما رضایت شهروندان را کاهش می‌دهد.
"""

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📈 افزایش مالیات",
                    callback_data="tax_up",
                ),
                InlineKeyboardButton(
                    text="📉 کاهش مالیات",
                    callback_data="tax_down",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏪 بازار",
                    callback_data="market",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت",
                    callback_data="menu",
                )
            ],
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
    )


@dp.callback_query(F.data == "economy")
async def economy_callback(callback: CallbackQuery):
    await callback.answer()
    await economy_screen(callback)


@dp.callback_query(F.data == "tax_up")
async def tax_up(callback: CallbackQuery):
    user_id = callback.from_user.id

    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE cities
            SET tax_rate=LEAST(25,tax_rate+2)
            WHERE user_id=$1
        """, user_id)

    await recalculate_city(user_id)

    await callback.answer("مالیات افزایش یافت.")
    await economy_screen(callback)


@dp.callback_query(F.data == "tax_down")
async def tax_down(callback: CallbackQuery):
    user_id = callback.from_user.id

    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE cities
            SET tax_rate=GREATEST(0,tax_rate-2)
            WHERE user_id=$1
        """, user_id)

    await recalculate_city(user_id)

    await callback.answer("مالیات کاهش یافت.")
    await economy_screen(callback)


# =========================================================
# CRISIS
# =========================================================

async def get_active_crisis(user_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("""
            SELECT *
            FROM crises
            WHERE user_id=$1 AND status='active'
            ORDER BY created_at DESC
            LIMIT 1
        """, user_id)


async def create_crisis(user_id):
    existing = await get_active_crisis(user_id)

    if existing:
        return existing

    city = await get_city(user_id)

    if not city:
        return None

    crisis_type = random.choice(list(CRISES.keys()))
    data = CRISES[crisis_type]

    service = city[data["stat"]]

    severity = int(
        data["base_severity"]
        - service * 0.7
        + random.randint(-10, 15)
    )

    severity = clamp(severity, 10, 100)

    async with db_pool.acquire() as conn:

        crisis = await conn.fetchrow("""
            INSERT INTO crises(
                user_id,
                crisis_type,
                severity,
                status
            )
            VALUES($1,$2,$3,'active')
            RETURNING *
        """, user_id, crisis_type, severity)

        await conn.execute("""
            INSERT INTO news(user_id,text)
            VALUES($1,$2)
        """,
            user_id,
            f"⚠️ بحران جدید: {data['name']}",
        )

        await conn.execute("""
            UPDATE cities
            SET satisfaction=GREATEST(
                0,
                satisfaction-$1
            )
            WHERE user_id=$2
        """,
            max(1, severity // 15),
            user_id,
        )

    return crisis


@dp.callback_query(F.data == "crises")
async def crises_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id
    crisis = await get_active_crisis(user_id)

    if not crisis:
        await callback.message.edit_text(
            """
🟢 <b>بحران فعالی وجود ندارد.</b>

شهر فعلاً پایدار است. 🌆

اما همیشه آماده باش؛ بحران‌ها ناگهانی اتفاق می‌افتند.
""",
            reply_markup=back_keyboard(),
        )
        return

    data = CRISES[crisis["crisis_type"]]

    text = f"""
🚨 <b>بحران فعال!</b>

{data['name']}

🔥 شدت: {crisis['severity']} / 100

🏛️ خدمت اصلی:
{data['stat']}

🎁 پاداش:
{data['reward']} سکه

برای مدیریت بحران روی دکمه زیر بزن.
"""

    await callback.message.edit_text(
        text,
        reply_markup=crisis_keyboard(crisis["id"]),
    )


@dp.callback_query(F.data.startswith("resolve:"))
async def resolve_crisis(callback: CallbackQuery):
    user_id = callback.from_user.id

    try:
        crisis_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("شناسه بحران نامعتبر است.", show_alert=True)
        return

    async with db_pool.acquire() as conn:

        async with conn.transaction():

            crisis = await conn.fetchrow("""
                SELECT *
                FROM crises
                WHERE id=$1
                FOR UPDATE
            """, crisis_id)

            if not crisis or crisis["user_id"] != user_id:
                await callback.answer(
                    "این بحران متعلق به شهر تو نیست.",
                    show_alert=True,
                )
                return

            if crisis["status"] !="active":
                await callback.answer(
                    "این بحران قبلاً حل شده.",
                    show_alert=True,
                )
                return

            city = await conn.fetchrow("""
                SELECT *
                FROM cities
                WHERE user_id=$1
                FOR UPDATE
            """, user_id)

            resources = await conn.fetchrow("""
                SELECT *
                FROM resources
                WHERE user_id=$1
                FOR UPDATE
            """, user_id)

            data = CRISES[crisis["crisis_type"]]

            required = max(
                20,
                crisis["severity"] * 2
            )

            resource_name = data["resource"]
            available = resources[resource_name]

            if available < required:
                await callback.answer(
                    f"❌ {resource_name} کافی نیست.",
                    show_alert=True,
                )
                return

            service = city[data["stat"]]

            success_chance = clamp(
                45 + service // 2,
                20,
                95,
            )

            roll = random.randint(1, 100)

            if roll <= success_chance:

                reward = data["reward"] + city["economy"]

                await conn.execute(f"""
                    UPDATE resources
                    SET
                        {resource_name}=GREATEST(
                            0,
                            {resource_name}-$1
                        ),
                        coins=coins+$2,
                        equipment=equipment+$3
                    WHERE user_id=$4
                """,
                    required,
                    reward,
                    max(1, crisis["severity"] // 20),
                    user_id,
                )

                await conn.execute("""
                    UPDATE crises
                    SET
                        status='resolved',
                        resolved_at=NOW()
                    WHERE id=$1
                """, crisis_id)

                await conn.execute("""
                    UPDATE cities
                    SET satisfaction=LEAST(
                        100,
                        satisfaction+5
                    )
                    WHERE user_id=$1
                """, user_id)

                await conn.execute("""
                    INSERT INTO news(user_id,text)
                    VALUES($1,$2)
                """,
                    user_id,
                    f"✅ بحران {data['name']} با موفقیت مدیریت شد.",
                )

                result = f"""
✅ <b>بحران با موفقیت حل شد!</b>

{data['name']}

🎯 شانس موفقیت: {success_chance}%
🎲 نتیجه: موفق

💰 پاداش: {reward:,} سکه
🧰 تجهیزات دریافت‌شده: {max(1, crisis['severity'] // 20)}
😊 رضایت +5
"""

                xp = 100

            else:

                await conn.execute(f"""
                    UPDATE resources
                    SET {resource_name}=GREATEST(
                        0,
                        {resource_name}-$1
                    )
                    WHERE user_id=$2
                """,
                    max(1, required // 2),
                    user_id,
                )

                await conn.execute("""
                    UPDATE cities
                    SET satisfaction=GREATEST(
                        0,
                        satisfaction-5
                    )
                    WHERE user_id=$1
                """, user_id)

                result = f"""
❌ <b>مدیریت بحران شکست خورد!</b>

{data['name']}

🎯 شانس موفقیت: {success_chance}%
🎲 نتیجه: شکست

⚠️ بخشی از منابع مصرف شد.
😊 رضایت -5

دوباره تلاش کن.
"""

                xp = 30

    await add_xp(user_id, xp)
    await recalculate_city(user_id)

    await callback.answer()

    await callback.message.edit_text(
        result,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="🚨 بحران‌ها",
                        callback_data="crises",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🏙️ شهر من",
                        callback_data="city",
                    )
                ],
            ]
        ),
    )


# =========================================================
# SOCIAL
# =========================================================

@dp.callback_query(F.data == "social")
async def social_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id

    async with db_pool.acquire() as conn:

        friends = await conn.fetch("""
            SELECT p.user_id, p.first_name, c.city_name
            FROM friendships f
            JOIN players p ON p.user_id=f.friend_id
            JOIN cities c ON c.user_id=p.user_id
            WHERE f.user_id=$1
            LIMIT 10
        """, user_id)

        pending = await conn.fetchval("""
            SELECT COUNT(*)
            FROM friend_requests
            WHERE receiver_id=$1 AND status='pending'
        """, user_id)

        groups = await conn.fetch("""
            SELECT g.id, g.name
            FROM groups g
            JOIN group_members gm
              ON gm.group_id=g.id
            WHERE gm.user_id=$1
        """, user_id)

    if friends:
        friend_text = "\n".join(
            f"👤 {f['first_name']} — {f['city_name']} | <code>{f['user_id']}</code>"
            for f in friends
        )
    else:
        friend_text = "هنوز دوستی نداری."

    if groups:
        group_text = "\n".join(
            f"👥 {g['name']} | ID: {g['id']}"
            for g in groups
        )
    else:
        group_text = "عضو هیچ گروهی نیستی."

    text = f"""
🤝 <b>بخش اجتماعی</b>

👤 <b>دوستان</b>

{friend_text}

📨 درخواست‌های دوستی جدید: {pending}

👥 <b>گروه‌های من</b>

{group_text}

━━━━━━━━━━━━

📨 افزودن دوست:
<code>/addfriend PLAYER_ID</code>

📋 درخواست‌ها:
<code>/friends</code>

📤 کمک:
<code>/help PLAYER_ID COINS FOOD MATERIALS</code>

👥 ساخت گروه:
<code>/creategroup نام گروه</code>

🔗 عضویت:
<code>/joingroup GROUP_ID</code>
"""

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📨 درخواست‌ها",
                        callback_data="friend_requests",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔄 دوستان",
                        callback_data="social",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 بازگشت",
                        callback_data="menu",
                    )
                ],
            ]
        ),
    )


# =========================================================
# FRIEND REQUEST
# =========================================================

@dp.message(Command("addfriend"))
async def add_friend(message: Message):
    user_id = await ensure_player(message)

    parts = message.text.split()

    if len(parts) != 2:
        await message.answer(
            "❌ مثال:\n<code>/addfriend 123456789</code>"
        )
        return

    try:
        receiver_id = int(parts[1])
    except ValueError:
        await message.answer("❌ شناسه بازیکن اشتباه است.")
        return

    if receiver_id == user_id:
        await message.answer("❌ نمی‌توانی خودت را دوست خودت کنی.")
        return

    async with db_pool.acquire() as conn:

        target = await conn.fetchrow(
            "SELECT user_id, first_name FROM players WHERE user_id=$1",
            receiver_id,
        )

        if not target:
            await message.answer("❌ بازیکن پیدا نشد.")
            return

        exists = await conn.fetchval("""
            SELECT 1
            FROM friendships
            WHERE user_id=$1 AND friend_id=$2
        """, user_id, receiver_id)

        if exists:await message.answer("✅ این بازیکن از قبل دوست توست.")
           
        return

        await conn.execute("""
            INSERT INTO friend_requests(sender_id, receiver_id)
            VALUES($1,$2)
            ON CONFLICT(sender_id,receiver_id)
            DO UPDATE SET status='pending'
        """, user_id, receiver_id)

    await message.answer(
        f"📨 درخواست دوستی برای <b>{target['first_name']}</b> ارسال شد."
    )

    try:
        await bot.send_message(
            receiver_id,
            "📨 یک درخواست دوستی جدید داری!\n"
            "برای مشاهده از بخش «🤝 اجتماعی» استفاده کن."
        )
    except Exception:
        pass


# =========================================================
# FRIEND REQUESTS
# =========================================================

@dp.callback_query(F.data == "friend_requests")
async def friend_requests_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT fr.id, p.first_name, p.user_id
            FROM friend_requests fr
            JOIN players p ON p.user_id=fr.sender_id
            WHERE fr.receiver_id=$1
              AND fr.status='pending'
            ORDER BY fr.created_at DESC
            LIMIT 10
        """, user_id)

    if not rows:
        text = "📨 <b>درخواست دوستی</b>\n\nدرخواست جدیدی نداری."

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 اجتماعی",
                        callback_data="social",
                    )
                ]
            ]
        )

        await callback.message.edit_text(text, reply_markup=keyboard)
        return

    lines = ["📨 <b>درخواست‌های دوستی</b>\n"]

    buttons = []

    for row in rows:
        lines.append(
            f"👤 {row['first_name']} | <code>{row['user_id']}</code>"
        )

        buttons.append([
            InlineKeyboardButton(
                text=f"✅ قبول {row['first_name']}",
                callback_data=f"accept_friend:{row['id']}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            text="🔙 اجتماعی",
            callback_data="social",
        )
    ])

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dp.callback_query(F.data.startswith("accept_friend:"))
async def accept_friend(callback: CallbackQuery):
    user_id = callback.from_user.id

    try:
        request_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("درخواست نامعتبر است.", show_alert=True)
        return

    async with db_pool.acquire() as conn:

        async with conn.transaction():

            request = await conn.fetchrow("""
                SELECT *
                FROM friend_requests
                WHERE id=$1
                FOR UPDATE
            """, request_id)

            if not request or request["receiver_id"] != user_id:
                await callback.answer(
                    "درخواست پیدا نشد.",
                    show_alert=True,
                )
                return

            if request["status"] != "pending":
                await callback.answer(
                    "این درخواست قبلاً پردازش شده.",
                    show_alert=True,
                )
                return

            sender_id = request["sender_id"]

            await conn.execute("""
                UPDATE friend_requests
                SET status='accepted'
                WHERE id=$1
            """, request_id)

            await conn.execute("""
                INSERT INTO friendships(user_id,friend_id)
                VALUES($1,$2),($2,$1)
                ON CONFLICT DO NOTHING
            """, sender_id, user_id)

    await callback.answer("✅ دوستی ایجاد شد.")

    try:
        await bot.send_message(
            sender_id,
            "🎉 درخواست دوستی تو قبول شد!"
        )
    except Exception:
        pass

    await callback.message.edit_text(
        "🎉 <b>دوستی با موفقیت ایجاد شد!</b>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🤝 اجتماعی",
                        callback_data="social",
                    )
                ]
            ]
        ),
    )


# =========================================================
# AID
# =========================================================

@dp.message(Command("help"))
async def help_command(message: Message):
    user_id = await ensure_player(message)

    parts = message.text.split()

    if len(parts) != 5:
        await message.answer("""
❌ فرمت اشتباه است.

مثال:

<code>/help 123456789 100 50 30</code>

ترتیب:
PLAYER_ID
COINS
FOOD
MATERIALS
""")
        return

    try:
        receiver_id = int(parts[1])
        coins = max(0, int(parts[2]))
        food = max(0, int(parts[3]))
        materials = max(0, int(parts[4]))
    except ValueError:
        await message.answer("❌ اعداد را درست وارد کن.")
        return

    if receiver_id == user_id:
        await message.answer("❌ نمی‌توانی به شهر خودت کمک بفرستی.")
        return

    total = coins + food + materials

    if total <= 0:
        await message.answer("❌ مقدار کمک باید بیشتر از صفر باشد.")
        return

    async with db_pool.acquire() as conn:

        async with conn.transaction():

            receiver = await conn.fetchrow(
                "SELECT user_id FROM players WHERE user_id=$1",
                receiver_id,
            )

            if not receiver:
                await message.answer("❌ شهر مقصد پیدا نشد.")
                return

            sender = await conn.fetchrow("""
                SELECT *
                FROM resources
                WHERE user_id=$1
                FOR UPDATE
            """, user_id)

            target = await conn.fetchrow("""
                SELECT *
                FROM resources
                WHERE user_id=$1
                FOR UPDATE
            """, receiver_id)

            if (
                sender["coins"] < coins
                or sender["food"] < food
                or sender["materials"] < materials
            ):
                await message.answer(
                    "❌ منابع کافی برای ارسال کمک نداری."
                )
                return

            await conn.execute("""
                UPDATE resources
                SET
                    coins=coins-$1,
                    food=food-$2,
                    materials=materials-$3
                WHERE user_id=$4
            """,
                coins,
                food,
                materials,
                user_id,
            )

            await conn.execute("""
                UPDATE resources
                SET
                    coins=coins+$1,
                    food=food+$2,
                    materials=materials+$3
                WHERE user_id=$4
            """,
                coins,
                food,
                materials,
                receiver_id,
            )

            await conn.execute("""
                INSERT INTO aid_logs(
                    sender_id,
                    receiver_id,
                    coins,
                    food,
                    materials
                )
                VALUES($1,$2,$3,$4,$5)
            """,
                user_id,
                receiver_id,
                coins,
                food,
                materials,
            )

    await add_xp(user_id, 20)

    await message.answer(
        f"""
🤝 <b>کمک با موفقیت ارسال شد!</b>

💰 سکه: {coins:,}
🍞 غذا: {food:,}
🧱 مصالح: {materials:,}

⭐ +20 XP
"""
    )

    try:
        await bot.send_message(
            receiver_id,
            "🤝 یک شهردار برای شهر تو کمک ارسال کرد!"
        )
    except Exception:
        pass


# =========================================================
# GROUP CREATE
# =========================================================

@dp.message(Command("creategroup"))
async def create_group(message: Message):
    user_id = await ensure_player(message)

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer(
            "❌ مثال:\n<code>/creategroup شهرداران تبریز</code>"
        )
        return

    name = parts[1][:40]

    async with db_pool.acquire() as conn:

        group = await conn.fetchrow("""
            INSERT INTO groups(name, owner_id)
            VALUES($1,$2)
            RETURNING id
        """, name, user_id)

        await conn.execute("""
            INSERT INTO group_members(group_id,user_id)
            VALUES($1,$2)
        """, group["id"], user_id)

    await message.answer(
        f"""
👥 <b>گروه ساخته شد!</b>

نام: {name}
🆔 Group ID: <code>{group['id']}</code>

این ID را برای دوستانت بفرست.
"""
    )


# =========================================================
# JOIN GROUP
# =========================================================

@dp.message(Command("joingroup"))
async def join_group(message: Message):
    user_id = await ensure_player(message)

    parts = message.text.split()

    if len(parts) != 2:
        await message.answer(
            "❌ مثال:\n<code>/joingroup 12</code>"
        )
        return

    try:
        group_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Group ID اشتباه است.")
        return

    async with db_pool.acquire() as conn:

        group = await conn.fetchrow(
            "SELECT * FROM groups WHERE id=$1",
            group_id,
        )

        if not group:
            await message.answer("❌ گروه پیدا نشد.")
            return

        await conn.execute("""
            INSERT INTO group_members(group_id,user_id)
            VALUES($1,$2)
            ON CONFLICT DO NOTHING
        """, group_id, user_id)

    await message.answer(
        f"""
✅ وارد گروه شدی!

👥 گروه: {group['name']}
🆔 ID: {group_id}
"""
    )


# =========================================================
# GROUPS SCREEN
# =========================================================

@dp.callback_query(F.data == "groups")
async def groups_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id

    async with db_pool.acquire() as conn:

        groups = await conn.fetch("""
            SELECT
                g.id,
                g.name,
                g.owner_id,
                COUNT(gm2.user_id) AS members
            FROM groups g
            JOIN group_members gm
              ON gm.group_id=g.id
            LEFT JOIN group_members gm2
              ON gm2.group_id=g.id
            WHERE gm.user_id=$1
            GROUP BY g.id
            ORDER BY g.created_at DESC
        """, user_id)

    if not groups:
        text = """
👥 <b>گروه‌ها</b>

هنوز عضو گروهی نیستی.

برای ساخت گروه:
<code>/creategroup نام گروه</code>

برای ورود:
<code>/joingroup GROUP_ID</code>
"""
    else:
        lines = ["👥 <b>گروه‌های من</b>\n"]

        for g in groups:
            lines.append(
                f"👥 {g['name']}\n"
                f"🆔 {g['id']} | 👤 اعضا: {g['members']}"
            )

        text = "\n\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🏆 چالش‌های گروهی",
                        callback_data="group_challenges",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 بازگشت",
                        callback_data="menu",
                    )
                ],
            ]
        ),
    )


# =========================================================
# GROUP CHALLENGES
# =========================================================

CHALLENGES = {
    "population": {
        "name": "👥 رشد جمعیت",
        "target": 100,
        "reward": 500,
    },
    "economy": {
        "name": "📈 اقتصاد",
        "target": 300,
        "reward": 600,
    },
    "crisis": {
        "name": "🚨 مدیریت بحران",
        "target": 5,
        "reward": 700,
    },
}


async def get_user_group(user_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("""
            SELECT g.*
            FROM groups g
            JOIN group_members gm
              ON gm.group_id=g.id
            WHERE gm.user_id=$1
            LIMIT 1
        """, user_id)


@dp.callback_query(F.data == "group_challenges")
async def group_challenges_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id
    group = await get_user_group(user_id)

    if not group:
        await callback.message.edit_text(
            "❌ ابتدا باید عضو یک گروه باشی.",
            reply_markup=back_keyboard(),
        )
        return

    async with db_pool.acquire() as conn:

        challenges = await conn.fetch("""
            SELECT *
            FROM group_challenges
            WHERE group_id=$1
              AND status='active'
            ORDER BY created_at DESC
            LIMIT 5
        """, group["id"])

    lines = [
        f"🏆 <b>چالش‌های گروه {group['name']}</b>\n"
    ]

    buttons = []

    if challenges:
        for challenge in challenges:
            data = CHALLENGES.get(challenge["challenge_type"])

            if data:
                lines.append(
                    f"{data['name']}\n"
                    f"📊 {challenge['progress']} / {challenge['target']}\n"
                    f"🎁 جایزه: {challenge['reward']:,} سکه"
                )
    else:
        lines.append(
            "هنوز چالش فعالی وجود ندارد.\n\n"
            "مدیر گروه می‌تواند چالش ایجاد کند."
        )

    buttons.append([
        InlineKeyboardButton(
            text="➕ ایجاد چالش",
            callback_data="create_challenge",
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            text="🔙 گروه‌ها",
            callback_data="groups",
        )
    ])

    await callback.message.edit_text(
        "\n\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@dp.callback_query(F.data == "create_challenge")
async def create_challenge_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    group = await get_user_group(user_id)

    if not group:
        await callback.answer(
            "ابتدا وارد گروه شو.",
            show_alert=True,
        )
        return

    if group["owner_id"] != user_id:
        await callback.answer(
            "فقط سازنده گروه می‌تواند چالش ایجاد کند.",
            show_alert=True,
        )
        return

    async with db_pool.acquire() as conn:

        active = await conn.fetchval("""
            SELECT COUNT(*)
            FROM group_challenges
            WHERE group_id=$1 AND status='active'
        """, group["id"])

        if active >= 3:
            await callback.answer(
                "گروه حداکثر ۳ چالش فعال می‌تواند داشته باشد.",
                show_alert=True,
            )
            return

        challenge_type = random.choice(list(CHALLENGES.keys()))
        data = CHALLENGES[challenge_type]

        target = data["target"]

        if challenge_type == "population":
            target = 100
        elif challenge_type == "economy":
            target = 300
        elif challenge_type == "crisis":
            target = 5

        await conn.execute("""
            INSERT INTO group_challenges(
                group_id,
                creator_id,
                challenge_type,
                target,
                progress,
                reward
            )
            VALUES($1,$2,$3,$4,0,$5)
        """,
            group["id"],
            user_id,
            challenge_type,
            target,
            data["reward"],
        )

    await callback.answer("🏆 چالش جدید ساخته شد!")

    await group_challenges_callback(callback)


# =========================================================
# MARKET
# =========================================================

MARKET_RESOURCES = {
    "food": "🍞 غذا",
    "materials": "🧱 مصالح",
    "energy": "⚡ انرژی",
    "water": "💧 آب",
    "equipment": "🧰 تجهیزات",
}


@dp.callback_query(F.data == "market")
async def market_callback(callback: CallbackQuery):
    await callback.answer()

    async with db_pool.acquire() as conn:
        offers = await conn.fetch("""
            SELECT
                mo.*,
                p.first_name
            FROM market_offers mo
            JOIN players p ON p.user_id=mo.seller_id
            WHERE mo.status='active'
            ORDER BY mo.created_at DESC
            LIMIT 10
        """)

    if not offers:
        text = """
🏪 <b>بازار شهر</b>

بازار فعلاً خالی است.

برای فروش منابع:
<code>/sell food 100 50</code>

یعنی:
۱۰۰ غذا با قیمت کل ۵۰ سکه
"""
    else:
        lines = ["🏪 <b>بازار شهر</b>\n"]

        for offer in offers:
            resource_name = MARKET_RESOURCES.get(
                offer["resource_type"],
                offer["resource_type"],
            )

            lines.append(
                f"🆔 {offer['id']}\n"
                f"{resource_name} × {offer['amount']:,}\n"
                f"💰 قیمت کل: {offer['price']:,}\n"
                f"👤 فروشنده: {offer['first_name']}"
            )

        text = "\n\n".join(lines)

    text += """

━━━━━━━━━━━━

🛒 خرید:
<code>/buy OFFER_ID</code>

📤 فروش:
<code>/sell RESOURCE AMOUNT PRICE</code>

منابع قابل معامله:
food
materials
energy
water
equipment
"""

    await callback.message.edit_text(
        text,
        reply_markup=back_keyboard(),
    )


@dp.message(Command("sell"))
async def sell_command(message: Message):
    user_id = await ensure_player(message)

    parts = message.text.split()

    if len(parts) != 4:
        await message.answer(
            "❌ مثال:\n<code>/sell food 100 50</code>"
        )
        return

    resource_type = parts[1].lower()

    if resource_type not in MARKET_RESOURCES:
        await message.answer(
            "❌ این منبع قابل معامله نیست."
        )
        return

    try:
        amount = int(parts[2])
        price = int(parts[3])
    except ValueError:
        await message.answer("❌ مقدار و قیمت باید عدد باشند.")
        return

    if amount <= 0 or price <= 0:
        await message.answer("❌ مقدار و قیمت باید بیشتر از صفر باشند.")
        return

    if amount > 100000 or price > 1000000:
        await message.answer("❌ مقدار معامله بیش از حد مجاز است.")
        return

    async with db_pool.acquire() as conn:

        async with conn.transaction():

            resources = await conn.fetchrow("""
                SELECT *
                FROM resources
                WHERE user_id=$1
                FOR UPDATE
            """, user_id)

            if resources[resource_type] < amount:
                await message.answer(
                    "❌ منابع کافی برای فروش نداری."
                )
                return

            await conn.execute(f"""
                UPDATE resources
                SET {resource_type}={resource_type}-$1
                WHERE user_id=$2
            """, amount, user_id)

            offer = await conn.fetchrow("""
                INSERT INTO market_offers(
                    seller_id,
                    resource_type,
                    amount,
                    price
                )
                VALUES($1,$2,$3,$4)
                RETURNING id
            """,
                user_id,
                resource_type,
                amount,
                price,
            )

    await message.answer(
        f"""
📤 <b>عرضه در بازار انجام شد!</b>

🆔 Offer ID: <code>{offer['id']}</code>

{MARKET_RESOURCES[resource_type]}: {amount:,}
💰 قیمت کل: {price:,} سکه
"""
    )


@dp.message(Command("buy"))
async def buy_command(message: Message):
    user_id = await ensure_player(message)

    parts = message.text.split()

    if len(parts) != 2:
        await message.answer(
            "❌ مثال:\n<code>/buy 15</code>"
        )
        return

    try:
        offer_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Offer ID اشتباه است.")
        return

    async with db_pool.acquire() as conn:

        async with conn.transaction():

            offer = await conn.fetchrow("""
                SELECT *
                FROM market_offers
                WHERE id=$1
                FOR UPDATE
            """, offer_id)

            if not offer or offer["status"] != "active":
                await message.answer(
                    "❌ این پیشنهاد دیگر فعال نیست."
                )
                return

            if offer["seller_id"] == user_id:
                await message.answer(
                    "❌ نمی‌توانی پیشنهاد خودت را بخری."
                )
                return

            buyer = await conn.fetchrow("""
                SELECT *
                FROM resources
                WHERE user_id=$1
                FOR UPDATE
            """, user_id)

            seller = await conn.fetchrow("""
                SELECT *
                FROM resources
                WHERE user_id=$1
                FOR UPDATE
            """, offer["seller_id"])

            if buyer["coins"] < offer["price"]:
                await message.answer(
                    "❌ سکه کافی نداری."
                )
                return

            await conn.execute("""
                UPDATE resources
                SET coins=coins-$1
                WHERE user_id=$2
            """,
                offer["price"],
                user_id,
            )

            await conn.execute("""
                UPDATE resources
                SET coins=coins+$1
                WHERE user_id=$2
            """,
                offer["price"],
                offer["seller_id"],
            )

            resource_type = offer["resource_type"]

            await conn.execute(f"""
                UPDATE resources
                SET {resource_type}={resource_type}+$1
                WHERE user_id=$2
            """,
                offer["amount"],
                user_id,
            )

            await conn.execute("""
                UPDATE market_offers
                SET status='sold'
                WHERE id=$1
            """, offer_id)

    await add_xp(user_id, 15)

    await message.answer(
        f"""
🛒 <b>خرید موفق بود!</b>

📦 {MARKET_RESOURCES[offer['resource_type']]}
مقدار: {offer['amount']:,}

💰 پرداخت: {offer['price']:,} سکه

⭐ +15 XP
"""
    )


# =========================================================
# WEEKLY COMPETITION
# =========================================================

def week_key():
    today = now_utc().date()
    year, week, _ = today.isocalendar()
    return f"{year}-W{week}"


async def update_weekly_score(user_id):
    await recalculate_city(user_id)

    city = await get_city(user_id)

    if not city:
        return

    score = (
        city["satisfaction"] * 5
        + city["economy"] * 4
        + city["population"] // 10
        + city["jobs"] // 5
        + city["city_level"] * 100
        + city["security"] // 2
        + city["health"] // 2
        + city["infrastructure"] // 2
    )

    key = week_key()

    async with db_pool.acquire() as conn:

        await conn.execute("""
            INSERT INTO weekly_seasons(week_key)
            VALUES($1)
            ON CONFLICT DO NOTHING
        """, key)

        await conn.execute("""
            INSERT INTO weekly_scores(
                user_id,
                week_key,
                score
            )
            VALUES($1,$2,$3)
            ON CONFLICT(user_id,week_key)
            DO UPDATE SET score=GREATEST(
                weekly_scores.score,
                EXCLUDED.score
            )
        """,
            user_id,
            key,
            score,
        )


@dp.callback_query(F.data == "ranking")
async def ranking_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id

    await update_weekly_score(user_id)

    key = week_key()

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                ws.user_id,
                ws.score,
                ws.claimed,
                p.first_name,
                c.city_name
            FROM weekly_scores ws
            JOIN players p
              ON p.user_id=ws.user_id
            JOIN cities c
              ON c.user_id=ws.user_id
            WHERE ws.week_key=$1
            ORDER BY ws.score DESC
            LIMIT 10
        """, key)

        my_rank = await conn.fetchval("""
            SELECT COUNT(*) + 1
            FROM weekly_scores
            WHERE week_key=$1
              AND score > (
                  SELECT score
                  FROM weekly_scores
                  WHERE week_key=$1 AND user_id=$2
              )
        """, key, user_id)

    if not rows:
        text = "هنوز امتیازی ثبت نشده."
    else:
        lines = [
            "🏆 <b>رقابت هفتگی</b>",
            f"📅 فصل: {key}",
            "",
        ]

        medals = ["🥇", "🥈", "🥉"]

        for i, row in enumerate(rows, 1):
            medal = medals[i - 1] if i <= 3 else f"{i}."

            lines.append(
                f"{medal} {row['city_name']} — "
                f"{row['score']:,}"
            )

        lines.append("")
        lines.append(
            f"📍 رتبه فعلی تو: {my_rank or '-'}"
        )
        lines.append("")
        lines.append(
            "🎁 جوایز فعلی:\n"
            "🥇 نفر اول: 3000 سکه\n"
            "🥈 نفر دوم: 1800 سکه\n"
            "🥉 نفر سوم: 1000 سکه"
        )

        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🎁 دریافت جایزه",
                        callback_data="claim_weekly",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 بازگشت",
                        callback_data="menu",
                    )
                ],
            ]
        ),
    )


@dp.callback_query(F.data == "claim_weekly")
async def claim_weekly(callback: CallbackQuery):
    user_id = callback.from_user.id
    key = week_key()

    async with db_pool.acquire() as conn:

        async with conn.transaction():

            row = await conn.fetchrow("""
                SELECT *
                FROM weekly_scores
                WHERE user_id=$1 AND week_key=$2
                FOR UPDATE
            """, user_id, key)

            if not row:
                await callback.answer(
                    "هنوز امتیازی ثبت نکردی.",
                    show_alert=True,
                )
                return

            if row["claimed"]:
                await callback.answer(
                    "جایزه این هفته قبلاً دریافت شده.",
                    show_alert=True,
                )
                return

            rank = await conn.fetchval("""
                SELECT COUNT(*) + 1
                FROM weekly_scores
                WHERE week_key=$1
                  AND score > $2
            """, key, row["score"])

            rewards = {
                1: 3000,
                2: 1800,
                3: 1000,
            }

            reward = rewards.get(rank, 0)

            if reward <= 0:
                await callback.answer(
                    "فقط سه نفر اول جایزه می‌گیرند.",
                    show_alert=True,
                )
                return

            await conn.execute("""
                UPDATE resources
                SET coins=coins+$1
                WHERE user_id=$2
            """, reward, user_id)

            await conn.execute("""
                UPDATE weekly_scores
                SET claimed=TRUE
                WHERE user_id=$1 AND week_key=$2
            """, user_id, key)

    await callback.answer("🎁 جایزه دریافت شد!")

    await callback.message.edit_text(
        f"""
🎉 <b>جایزه هفتگی دریافت شد!</b>

🏆 رتبه: {rank}

💰 جایزه: {reward:,} سکه

آفرین شهردار! هفته بعد دوباره برای رتبه بهتر تلاش کن. 🔥
""",
        reply_markup=main_keyboard(),
    )


# =========================================================
# NEWS
# =========================================================

@dp.callback_query(F.data == "news")
async def news_callback(callback: CallbackQuery):
    await callback.answer()

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT text, created_at
            FROM news
            WHERE user_id=$1
            ORDER BY created_at DESC
            LIMIT 10
        """, callback.from_user.id)

    if not rows:
        text = """
📰 <b>روزنامه شهر</b>

هنوز خبر خاصی در شهر ثبت نشده.

شهر تو تازه شروع به رشد کرده! 🌱
"""
    else:
        lines = ["📰 <b>روزنامه شهر</b>\n"]

        for row in rows:
            lines.append(f"• {row['text']}")

        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=back_keyboard(),
    )


# =========================================================
# EXPANSION
# =========================================================

@dp.callback_query(F.data == "expansion")
async def expansion_callback(callback: CallbackQuery):
    await callback.answer()

    city = await get_city(callback.from_user.id)

    needed_level = 10 + city["villages"] * 5

    if city["city_level"] < needed_level:
        text = f"""
🗺️ <b>توسعه شهر</b>

برای جذب روستای بعدی باید به سطح شهر {needed_level} برسی.

⭐ سطح فعلی: {city['city_level']}

🏘️ روستاهای جذب‌شده: {city['villages']}

شهر را توسعه بده تا بتوانی محدوده اطراف را به شهر اضافه کنی.
"""
        await callback.message.edit_text(
            text,
            reply_markup=back_keyboard(),
        )
        return

    cost = 2500 + city["villages"] * 1500

    text = f"""
🗺️ <b>توسعه شهر</b>

یک روستای جدید آماده‌ی پیوستن به شهر است! 🏘️

🏙️ سطح شهر: {city['city_level']}
🏘️ روستاهای فعلی: {city['villages']}

💰 هزینه توسعه: {cost:,} سکه

با توسعه:

👥 ظرفیت جمعیت افزایش می‌یابد
🏠 ظرفیت مسکن افزایش می‌یابد
🗺️ زمین شهر بیشتر می‌شود
"""

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏘️ جذب روستا",
                    callback_data="expand_village",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت",
                    callback_data="menu",
                )
            ],
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
    )


@dp.callback_query(F.data == "expand_village")
async def expand_village(callback: CallbackQuery):
    user_id = callback.from_user.id

    async with db_pool.acquire() as conn:

        async with conn.transaction():

            city = await conn.fetchrow("""
                SELECT *
                FROM cities
                WHERE user_id=$1
                FOR UPDATE
            """, user_id)

            needed_level = 10 + city["villages"] * 5

            if city["city_level"] < needed_level:
                await callback.answer(
                    "❌ سطح شهر کافی نیست.",
                    show_alert=True,
                )
                return

            cost = 2500 + city["villages"] * 1500

            resources = await conn.fetchrow("""
                SELECT coins
                FROM resources
                WHERE user_id=$1
                FOR UPDATE
            """, user_id)

            if resources["coins"] < cost:
                await callback.answer(
                    "❌ سکه کافی نداری.",
                    show_alert=True,
                )
                return

            await conn.execute("""
                UPDATE resources
                SET coins=coins-$1
                WHERE user_id=$2
            """, cost, user_id)

            await conn.execute("""
                UPDATE cities
                SET
                    villages=villages+1,
                    land=land+1,
                    housing_capacity=housing_capacity+200,
                    population=population+50
                WHERE user_id=$1
            """, user_id)

            await conn.execute("""
                INSERT INTO news(user_id,text)VALUES($1,$2)
            """,
                user_id,
                "🏘️ یک روستای جدید به محدوده شهر اضافه شد!",
            )

    await add_xp(user_id, 250)
    await recalculate_city(user_id)

    await callback.answer("🏘️ توسعه با موفقیت انجام شد!")

    await callback.message.edit_text(
        """
🎉 <b>توسعه موفق بود!</b>

🏘️ یک روستا به شهر تو پیوست.

🗺️ محدوده شهر بزرگ‌تر شد.
🏠 ظرفیت مسکن افزایش یافت.
👥 جمعیت افزایش یافت.

شهردار، شهر تو در حال تبدیل شدن به یک منطقه بزرگ است! 🏙️
""",
        reply_markup=main_keyboard(),
    )


# =========================================================
# GAME TICK
# =========================================================

async def game_tick():
    while True:

        try:

            async with db_pool.acquire() as conn:
                users = await conn.fetch(
                    "SELECT user_id FROM players"
                )

            for row in users:

                try:
                    await process_player_tick(row["user_id"])
                except Exception as e:
                    logging.exception(
                        "Player tick error %s: %s",
                        row["user_id"],
                        e,
                    )

        except Exception as e:
            logging.exception(
                "Game tick error: %s",
                e,
            )

        await asyncio.sleep(1800)


async def process_player_tick(user_id):

    city = await get_city(user_id)

    if not city:
        return

    last_tick = city["last_tick"]

    if last_tick is None:
        last_tick = now_utc()

    current = now_utc()
    elapsed = current - last_tick

    if elapsed < timedelta(minutes=25):
        return

    await recalculate_city(user_id)

    city = await get_city(user_id)

    food_need = max(
        1,
        city["population"] // 50
    )

    water_need = max(
        1,
        city["population"] // 45
    )

    energy_need = max(
        1,
        city["population"] // 60
    )

    async with db_pool.acquire() as conn:

        await conn.execute("""
            UPDATE resources
            SET
                food=GREATEST(0,food-$1),
                water=GREATEST(0,water-$2),
                energy=GREATEST(0,energy-$3)
            WHERE user_id=$4
        """,
            food_need,
            water_need,
            energy_need,
            user_id,
        )

        resources = await conn.fetchrow(
            "SELECT * FROM resources WHERE user_id=$1",
            user_id,
        )

        satisfaction_change = 0

        if resources["food"] <= 0:
            satisfaction_change -= 5

        if resources["water"] <= 0:
            satisfaction_change -= 5

        if resources["energy"] <= 0:
            satisfaction_change -= 4

        population = city["population"]

        if city["satisfaction"] >= 80:
            population_change = random.randint(1, 5)
        elif city["satisfaction"] >= 60:
            population_change = random.randint(0, 2)
        elif city["satisfaction"] >= 40:
            population_change = random.randint(-1, 1)
        else:
            population_change = random.randint(-5, 0)

        new_population = max(
            50,
            population + population_change
        )

        # Migration effect
        if city["satisfaction"] >= 85:
            new_population += random.randint(1, 3)

        elif city["satisfaction"] < 30:
            new_population = max(
                50,
                new_population - random.randint(1, 3)
            )

        level = city["city_level"]
        required_population = level * 250

        if (
            new_population >= required_population
            and city["satisfaction"] >= 65
            and level < MAX_LEVEL
        ):
            level += 1

            await conn.execute("""
                INSERT INTO news(user_id,text)
                VALUES($1,$2)
            """,
                user_id,
                f"🎉 شهر به سطح {level} رسید!",
            )

        await conn.execute("""
            UPDATE cities
            SET
                population=$1,
                city_level=$2,
                satisfaction=GREATEST(
                    0,
                    LEAST(
                        100,
                        satisfaction+$3
                    )
                ),
                last_tick=NOW()
            WHERE user_id=$4
        """,
            new_population,
            level,
            satisfaction_change,
            user_id,
        )

    await collect_income(user_id)

    city = await get_city(user_id)

    active = await get_active_crisis(user_id)

    if not active:

        danger = 15

        danger -= city["security"] // 10
        danger -= city["fire_safety"] // 10
        danger -= city["health"] // 10
        danger -= city["infrastructure"] // 10
        danger -= city["crisis"] // 10

        danger += max(
            0,
            60 - city["satisfaction"]
        ) // 5

        danger = clamp(
            danger,
            2,
            20,
        )

        if random.randint(1, 100) <= danger:

            crisis = await create_crisis(user_id)

            if crisis:

                try:
                    data = CRISES[crisis["crisis_type"]]

                    await bot.send_message(
                        user_id,
                        f"""
🚨 <b>هشدار شهری!</b>

{data['name']}

یک بحران جدید در شهر اتفاق افتاده!

🔥 شدت: {crisis['severity']} / 100

سریع وارد بخش «🚨 بحران‌ها» شو.
""",
                    )
                except Exception:
                    pass

    await update_weekly_score(user_id)


# =========================================================
# COMMANDS
# =========================================================

@dp.message(Command("city"))
async def city_command(message: Message):
    user_id = await ensure_player(message)

    await process_player_tick(user_id)

    await message.answer(
        await city_text(user_id),
        reply_markup=main_keyboard(),
    )


@dp.message(Command("menu"))
async def menu_command(message: Message):
    await ensure_player(message)

    await message.answer(
        "🏙️ <b>منوی اصلی شهر من</b>",
        reply_markup=main_keyboard(),
    )


@dp.message(Command("profile"))
async def profile_command(message: Message):
    user_id = await ensure_player(message)

    player = await get_player(user_id)
    city = await get_city(user_id)

    await message.answer(
        f"""
👑 <b>پروفایل شهردار</b>

👤 {player['first_name']}

🏙️ شهر: {city['city_name']}

⭐ سطح: {player['level']}
✨ XP: {player['xp']}

👥 جمعیت: {city['population']:,}
😊 رضایت: {city['satisfaction']}%
📈 اقتصاد: {city['economy']}%
"""
    )


# =========================================================
# FRIENDS COMMAND
# =========================================================

@dp.message(Command("friends"))
async def friends_command(message: Message):
    user_id = await ensure_player(message)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.user_id, p.first_name, c.city_name
            FROM friendships f
            JOIN players p ON p.user_id=f.friend_id
            JOIN cities c ON c.user_id=p.user_id
            WHERE f.user_id=$1
            LIMIT 20
        """, user_id)

        requests = await conn.fetch("""
            SELECT p.first_name, p.user_id
            FROM friend_requests fr
            JOIN players p ON p.user_id=fr.sender_id
            WHERE fr.receiver_id=$1
              AND fr.status='pending'
            LIMIT 10
        """, user_id)

    if rows:
        friends_text = "\n".join(
            f"👤 {r['first_name']} — {r['city_name']}\n"
            f"ID: <code>{r['user_id']}</code>"
            for r in rows
        )
    else:
        friends_text = "هنوز دوستی نداری."

    if requests:
        request_text = "\n".join(
            f"📨 {r['first_name']} — <code>{r['user_id']}</code>"
            for r in requests
        )
    else:
        request_text = "درخواست جدیدی نداری."

    await message.answer(
        f"""
🤝 <b>دوستان من</b>

👥 دوستان:

{friends_text}

━━━━━━━━━━━━

📨 درخواست‌ها:

{request_text}

برای مدیریت درخواست‌ها وارد بخش اجتماعی شو.
""",
        reply_markup=main_keyboard(),
    )


# =========================================================
# CITY NAME
# =========================================================

@dp.message(Command("namecity"))
async def name_city_command(message: Message):
    user_id = await ensure_player(message)

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer("""
❌ اسم شهر را وارد نکردی.

مثال:

<code>/namecity تبریز نو</code>
""")
        return

    name = parts[1].strip()[:40]

    if len(name) < 2:
        await message.answer(
            "❌ اسم شهر خیلی کوتاه است."
        )
        return

    async with db_pool.acquire() as conn:

        await conn.execute("""
            UPDATE cities
            SET city_name=$1
            WHERE user_id=$2
        """, name, user_id)

        await conn.execute("""
            INSERT INTO news(user_id,text)
            VALUES($1,$2)
        """,
            user_id,
            f"🏙️ نام شهر به «{name}» تغییر کرد.",
        )

    await message.answer(
        f"""
✅ نام شهر تغییر کرد!

🏙️ نام جدید:
<b>{name}</b>
"""
    )


# =========================================================
# HELP
# =========================================================

@dp.message(Command("commands"))
async def commands_command(message: Message):
    await ensure_player(message)

    await message.answer("""
📚 <b>دستورات شهر من</b>

/start
/menu
/city
/profile

/namecity نام شهر

🤝 اجتماعی:

/addfriend PLAYER_ID
/friends
/help PLAYER_ID COINS FOOD MATERIALS

👥 گروه:

/creategroup نام گروه
/joingroup GROUP_ID

🏪 بازار:

/sell food 100 50
/buy OFFER_ID

برای بقیه امکانات از منوی اصلی استفاده کن.
""",
        reply_markup=main_keyboard(),
    )


# =========================================================
# UNKNOWN TEXT
# =========================================================

@dp.message()
async def unknown_message(message: Message):
    await message.answer("""
🏙️ برای مدیریت شهر از منوی زیر استفاده کن:

/start
/menu
/city
/profile
/commands

یا از دکمه‌های منو استفاده کن.
""",
        reply_markup=main_keyboard(),
    )


# =========================================================
# RENDER HEALTH SERVER
# =========================================================

async def health(request):
    return web.Response(
        text="Shahr Man Bot is running."
    )


async def start_web_server():
    app = web.Application()

    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        host="0.0.0.0",
        port=PORT,
    )

    await site.start()

    logging.info(
        "Health server started on port %s",
        PORT,
    )

    return runner


# =========================================================
# MAIN
# =========================================================

async def main():

    await init_db()

    logging.info("Database connected.")

    web_runner = await start_web_server()

    tick_task = asyncio.create_task(
        game_tick()
    )

    try:

        logging.info(
            "Shahr Man bot started."
        )

        await dp.start_polling(bot)

    finally:

        tick_task.cancel()

        try:
            await tick_task
        except asyncio.CancelledError:
            pass

        await web_runner.cleanup()

        await db_pool.close()

        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
