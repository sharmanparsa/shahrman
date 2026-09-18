import asyncio
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from html import escape

import asyncpg
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ChatMemberUpdated,
    ForceReply,
    ReplyKeyboardMarkup,
    KeyboardButton,
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

bot = Bot(
    BOT_TOKEN,
    default=DefaultBotProperties(
        parse_mode=ParseMode.HTML
    ),
)

dp = Dispatcher()

class TelegramGroupMessageGuard(BaseMiddleware):
    async def __call__(self, handler, event, data):
        chat = getattr(event, "chat", None)
        if chat and chat.type in {"group", "supergroup"}:
            text = (getattr(event, "text", None) or "").strip()
            if text == "شهر من":
                return await handler(event, data)
            # ثبت بی‌صدای شهردارهای موجود در گروه؛ ربات برای پیام‌های دیگر پاسخی نمی‌دهد.
            user = getattr(event, "from_user", None)
            if user and db_pool is not None:
                try:
                    async with db_pool.acquire() as conn:
                        exists = await conn.fetchval("SELECT 1 FROM players WHERE user_id=$1", user.id)
                        if exists:
                            await conn.execute(
                                """
                                UPDATE players
                                SET username=$2, first_name=$3
                                WHERE user_id=$1
                                """,
                                user.id, user.username, user.first_name or ""
                            )
                            await conn.execute(
                                """
                                INSERT INTO telegram_group_mayors(chat_id,user_id,username,first_name,last_seen)
                                VALUES($1,$2,$3,$4,NOW())
                                ON CONFLICT(chat_id,user_id) DO UPDATE SET
                                    username=EXCLUDED.username, first_name=EXCLUDED.first_name, last_seen=NOW()
                                """,
                                chat.id, user.id, user.username, user.first_name or ""
                            )
                            await conn.execute(
                                """
                                INSERT INTO telegram_groups(chat_id,title,bot_is_admin,updated_at)
                                VALUES($1,$2,TRUE,NOW())
                                ON CONFLICT(chat_id) DO UPDATE SET
                                    title=EXCLUDED.title, bot_is_admin=TRUE, updated_at=NOW()
                                """,
                                chat.id, getattr(chat, "title", None) or "گروه تلگرام"
                            )
                except Exception:
                    pass
            reply = getattr(event, "reply_to_message", None)
            user = getattr(event, "from_user", None)
            if reply and user and (chat.id, user.id) in group_transfer_state:
                return await handler(event, data)
            return None
        return await handler(event, data)

dp.message.outer_middleware(TelegramGroupMessageGuard())

db_pool = None

# وضعیت موقت انتقال دارایی داخل گروه‌های واقعی تلگرام
group_transfer_state = {}

TRANSFER_RESOURCES = {
    "coins": "💰 سکه",
    "food": "🍞 غذا",
    "materials": "🧱 مصالح",
    "energy": "⚡ انرژی",
    "water": "💧 آب",
    "equipment": "🧰 تجهیزات",
}
TRANSFER_ALIASES = {
    "سکه": "coins", "پول": "coins", "coins": "coins",
    "غذا": "food", "food": "food",
    "مصالح": "materials", "آجر": "materials", "اجر": "materials", "materials": "materials",
    "انرژی": "energy", "energy": "energy",
    "آب": "water", "water": "water",
    "تجهیزات": "equipment", "equipment": "equipment",
}


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

IRAN_TZ = ZoneInfo("Asia/Tehran")
WEEKLY_REWARDS = {1: 3000, 2: 1800, 3: 1000}
NATURAL_DISASTERS = [
    ("🌊 سیل", 1),
    ("🌪️ طوفان", 1),
    ("❄️ کولاک شدید", 1),
    ("🔥 آتش‌سوزی گسترده", 2),
    ("🌧️ بارندگی شدید", 1),
    ("🌨️ برف سنگین", 1),
    ("🌡️ موج گرما", 1),
    ("⚡ طوفان الکتریکی", 2),
    ("🌫️ آلودگی شدید", 1),
]
MIN_DISASTER_GAP_MINUTES = 120

# زمان ارتقای ساختمان‌ها (ساعت)
BUILDING_UPGRADE_HOURS = {
    1: 2,
    2: 10,
    3: 20,
    4: 40,
}

CRISIS_STAT_NAMES = {
    "security": "امنیت",
    "fire_safety": "ایمنی در برابر آتش‌سوزی",
    "health": "سلامت",
    "power": "برق",
    "water": "آب",
    "education": "آموزش",
    "recreation": "تفریح",
    "pollution_control": "کنترل آلودگی",
    "infrastructure": "زیرساخت",
    "crisis": "مدیریت بحران",
    "economy": "اقتصاد",
}


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
        "income_hourly": 20,
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
        "income_hourly": 10,
        "name": "🎓 دانشگاه",
        "cost": 800,
        "material": 250,
        "base_effect": {
            "education": 18,
            "economy": 5,
        },
        "maintenance": 18,
        "description": "اقتصاد و آموزش پیشرفته.",
    },
    "park": {
        "name": "🌳 پارک",
        "cost": 300,
        "material": 80,
        "base_effect": {
            "recreation": 12,
            "pollution_control": 5,
        },
        "maintenance": 5,
        "description": "تفریح و کاهش آلودگی.",
    },
    "shopping": {
        "income_hourly": 40,
        "name": "🛍️ مرکز خرید",
        "cost": 700,
        "material": 220,
        "base_effect": {
            "economy": 12,
            "jobs": 15,
        },
        "maintenance": 12,
        "description": "افزایش اشتغال و اقتصاد.",
    },
    "stadium": {
        "income_hourly": 30,
        "name": "🏟️ ورزشگاه",
        "cost": 1000,
        "material": 300,
        "base_effect": {
            "recreation": 20,
            "economy": 5,
            "jobs": 20,
        },
        "maintenance": 20,
        "description": "تفریح، اشتغال و اقتصاد.",
    },
    "recycling": {
        "material_income_hourly": 10,
        "name": "♻️ مرکز بازیافت",
        "cost": 600,
        "material": 200,
        "base_effect": {
            "pollution_control": 18,
        },
        "maintenance": 12,
        "description": "کنترل آلودگی و زباله.",
    },
    "emergency": {
        "name": "🚑 مرکز اورژانس",
        "cost": 750,
        "material": 220,
        "base_effect": {
            "crisis": 15,
            "health": 8,
        },
        "maintenance": 15,
        "description": "سرعت واکنش به بحران‌ها.",
    },
    "roads": {
        "income_hourly": 10,
        "name": "🛣️ اداره راه",
        "cost": 650,
        "material": 250,
        "base_effect": {
            "infrastructure": 15,
            "jobs": 10,
        },
        "maintenance": 15,
        "description": "زیرساخت و حمل‌ونقل.",
    },
    "waste": {
        "material_income_hourly": 5,
        "name": "🗑️ مدیریت پسماند",
        "cost": 450,
        "material": 150,
        "base_effect": {
            "pollution_control": 12,
        },
        "maintenance": 9,
        "description": "مدیریت زباله و پاکیزگی.",
    },
    "industry": {
        "income_hourly": 50,
        "material_income_hourly": 15,
        "name": "🏭 منطقه صنعتی",
        "cost": 900,
        "material": 300,
        "base_effect": {
            "economy": 20,
            "jobs": 35,
            "pollution": 8,
        },
        "maintenance": 20,
        "description": "اقتصاد و اشتغال زیاد، اما آلودگی بیشتر.",
    },
    "housing": {
        "name": "🏘️ مجتمع مسکونی",
        "cost": 600,
        "material": 200,
        "base_effect": {
            "infrastructure": 4,
        },
        "maintenance": 8,
        "housing": 150,
        "description": "ظرفیت مسکن شهر را افزایش می‌دهد.",
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
# MARKET
# =========================================================

MARKET_RESOURCES = {
    "food": "🍞 غذا",
    "materials": "🧱 مصالح",
    "energy": "⚡ انرژی",
    "water": "💧 آب",
    "equipment": "🧰 تجهیزات",
}


# =========================================================
# HELPERS
# =========================================================

def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def now_utc():
    return datetime.now(timezone.utc)


def safe_text(value):
    if value is None:
        return ""
    return escape(str(value))


def satisfaction_status(value):
    if value >= 85:
        return "😊 بسیار راضی"
    if value >= 70:
        return "🙂 راضی"
    if value >= 55:
        return "😐 معمولی"
    if value >= 40:
        return "😕 ناراضی"
    return "😡 بسیار ناراضی"


def employment_status(population, jobs):
    if population <= 0:
        return 0, 0

    employed = min(population, max(0, jobs))
    unemployment = clamp(
        int((population - employed) * 100 / population),
        0,
        100,
    )

    return unemployment, employed


def citizen_bar(value):
    value = clamp(int(value), 0, 100)

    filled = value // 10
    empty = 10 - filled

    return "🟩" * filled + "⬜" * empty


def start_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚀 شروع بازی")]],
        resize_keyboard=True,
        is_persistent=True,
    )


def main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🏙️ شهر من",
                    callback_data="city",
                ),
                InlineKeyboardButton(
                    text="👑 شهردار",
                    callback_data="mayor",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👥 شهروندان",
                    callback_data="citizens",
                ),
                InlineKeyboardButton(
                    text="🏗️ ساختمان‌ها",
                    callback_data="buildings",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📦 منابع",
                    callback_data="resources",
                ),
                InlineKeyboardButton(
                    text="💰 اقتصاد",
                    callback_data="economy",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🚨 بحران‌ها",
                    callback_data="crises",
                ),
                InlineKeyboardButton(
                    text="🤝 اجتماعی",
                    callback_data="social",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏆 رقابت",
                    callback_data="ranking",
                ),
                InlineKeyboardButton(
                    text="🏪 بازار",
                    callback_data="market",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📰 روزنامه شهر",
                    callback_data="news",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🗺️ توسعه شهر",
                    callback_data="expansion",
                ),
            ],
        ]
    )


def back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت",
                    callback_data="menu",
                )
            ]
        ]
    )


async def building_keyboard(user_id):
    rows = []
    async with db_pool.acquire() as conn:
        levels = {
            r["building_type"]: r["level"]
            for r in await conn.fetch(
                "SELECT building_type, level FROM buildings WHERE user_id=$1", user_id
            )
        }
        active = await conn.fetchrow(
            "SELECT building_type, target_level, ready_at FROM building_constructions WHERE user_id=$1 AND completed=FALSE ORDER BY ready_at LIMIT 1",
            user_id,
        )

    for key, data in BUILDINGS.items():
        level = levels.get(key, 0)
        if active and active["building_type"] == key:
            remaining = max(0, int((active["ready_at"] - now_utc()).total_seconds()))
            hours, rem = divmod(remaining, 3600)
            minutes = rem // 60
            status = f"⏳ تا سطح {active['target_level']} ({hours}س {minutes}د)"
        elif level > 0:
            status = f"سطح {level}"
        else:
            status = "🔒 قفل"
        rows.append([InlineKeyboardButton(text=f"{data['name']} — {status}", callback_data=f"building:{key}")])

    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu")])
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

async def migrate_players_table(conn):
    """
    Migration مخصوص دیتابیس‌های قدیمی.
    اگر جدول players قبلاً ساخته شده باشد ولی user_id نداشته باشد،
    CREATE TABLE IF NOT EXISTS به‌تنهایی آن را اصلاح نمی‌کند.
    """

    columns = await conn.fetch(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema='public'
          AND table_name='players'
        """
    )

    existing = {
        row["column_name"]: row["data_type"]
        for row in columns
    }

    if not existing:
        await conn.execute(
            """
            CREATE TABLE players (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1
            )
            """
        )
        return

    if "user_id" not in existing:
        old_column = None

        for candidate in (
            "id",
            "telegram_id",
            "chat_id",
            "user",
        ):
            if candidate in existing:
                old_column = candidate
                break

        if old_column:
            logging.warning(
                "Migrating players.%s -> players.user_id",
                old_column,
            )

            await conn.execute(
                f"""
                ALTER TABLE players
                RENAME COLUMN {old_column} TO user_id
                """
            )
        else:
            await conn.execute(
                """
                ALTER TABLE players
                ADD COLUMN user_id BIGINT
                """
            )

            raise RuntimeError(
                "players table exists but has no usable user identifier. "
                "Please inspect the old players table."
            )

    await conn.execute(
        """
        ALTER TABLE players
        ALTER COLUMN user_id TYPE BIGINT
        USING user_id::BIGINT
        """
    )

    required_columns = {
        "username": "TEXT",
        "first_name": "TEXT",
        "created_at": "TIMESTAMPTZ DEFAULT NOW()",
        "xp": "INTEGER DEFAULT 0",
        "level": "INTEGER DEFAULT 1",
    }

    for column, definition in required_columns.items():
        await conn.execute(
            f"""
            ALTER TABLE players
            ADD COLUMN IF NOT EXISTS {column} {definition}
            """
        )

    # تلاش برای تضمین unique بودن user_id
    await conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
        players_user_id_unique_idx
        ON players(user_id)
        """
    )


async def init_db():
    global db_pool

    db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=5,
        command_timeout=30,
    )

    async with db_pool.acquire() as conn:
        await migrate_players_table(conn)

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cities (
                user_id BIGINT PRIMARY KEY
                    REFERENCES players(user_id)
                    ON DELETE CASCADE,
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
            """
        )

        migration_columns = {
            "city_name": "TEXT DEFAULT 'شهر من'",
            "population": "INTEGER DEFAULT 100",
            "jobs": "INTEGER DEFAULT 50",
            "satisfaction": "INTEGER DEFAULT 70",
            "economy": "INTEGER DEFAULT 50",
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
                    f"""
                    ALTER TABLE cities
                    ADD COLUMN IF NOT EXISTS {column} {definition}
                    """
                )
            except Exception:
                logging.exception(
                    "Migration error for cities.%s",
                    column,
                )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS resources (
                user_id BIGINT PRIMARY KEY
                    REFERENCES players(user_id)
                    ON DELETE CASCADE,
                coins INTEGER DEFAULT 1000,
                food INTEGER DEFAULT 500,
                materials INTEGER DEFAULT 300,
                energy INTEGER DEFAULT 500,
                water INTEGER DEFAULT 500,
                equipment INTEGER DEFAULT 20
            )
            """
        )

        resource_columns = {
            "coins": "INTEGER DEFAULT 1000",
            "food": "INTEGER DEFAULT 500",
            "materials": "INTEGER DEFAULT 300",
            "energy": "INTEGER DEFAULT 500",
            "water": "INTEGER DEFAULT 500",
            "equipment": "INTEGER DEFAULT 20",
        }

        for column, definition in resource_columns.items():
            await conn.execute(
                f"""
                ALTER TABLE resources
                ADD COLUMN IF NOT EXISTS {column} {definition}
                """
            )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS buildings (
                user_id BIGINT
                    REFERENCES players(user_id)
                    ON DELETE CASCADE,
                building_type TEXT,
                level INTEGER DEFAULT 0,
                PRIMARY KEY(user_id, building_type)
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS building_constructions (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES players(user_id) ON DELETE CASCADE,
                building_type TEXT NOT NULL,
                target_level INTEGER NOT NULL,
                started_at TIMESTAMPTZ DEFAULT NOW(),
                ready_at TIMESTAMPTZ NOT NULL,
                completed BOOLEAN DEFAULT FALSE
            )
            """
        )

        await conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_building_construction_per_user
            ON building_constructions(user_id)
            WHERE completed=FALSE
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS crises (
                id SERIAL PRIMARY KEY,
                user_id BIGINT
                    REFERENCES players(user_id)
                    ON DELETE CASCADE,
                crisis_type TEXT NOT NULL,
                severity INTEGER NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                resolved_at TIMESTAMPTZ
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS news (
                id SERIAL PRIMARY KEY,
                user_id BIGINT
                    REFERENCES players(user_id)
                    ON DELETE CASCADE,
                text TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS aid_logs (
                id SERIAL PRIMARY KEY,
                sender_id BIGINT,
                receiver_id BIGINT,
                coins INTEGER DEFAULT 0,
                food INTEGER DEFAULT 0,
                materials INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS groups (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                owner_id BIGINT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS group_members (
                group_id INTEGER
                    REFERENCES groups(id)
                    ON DELETE CASCADE,
                user_id BIGINT
                    REFERENCES players(user_id)
                    ON DELETE CASCADE,
                joined_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY(group_id, user_id)
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weekly_scores (
                id SERIAL PRIMARY KEY,
                user_id BIGINT
                    REFERENCES players(user_id)
                    ON DELETE CASCADE,
                week_key TEXT NOT NULL,
                score INTEGER DEFAULT 0,
                claimed BOOLEAN DEFAULT FALSE,
                UNIQUE(user_id, week_key)
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS friend_requests (
                id SERIAL PRIMARY KEY,
                sender_id BIGINT
                    REFERENCES players(user_id)
                    ON DELETE CASCADE,
                receiver_id BIGINT
                    REFERENCES players(user_id)
                    ON DELETE CASCADE,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(sender_id, receiver_id)
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS friendships (
                user_id BIGINT
                    REFERENCES players(user_id)
                    ON DELETE CASCADE,
                friend_id BIGINT
                    REFERENCES players(user_id)
                    ON DELETE CASCADE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY(user_id, friend_id)
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_offers (
                id SERIAL PRIMARY KEY,
                seller_id BIGINT
                    REFERENCES players(user_id)
                    ON DELETE CASCADE,
                resource_type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                price INTEGER NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS group_challenges (
                id SERIAL PRIMARY KEY,
                group_id INTEGER
                    REFERENCES groups(id)
                    ON DELETE CASCADE,
                creator_id BIGINT
                    REFERENCES players(user_id)
                    ON DELETE CASCADE,
                challenge_type TEXT NOT NULL,
                target INTEGER NOT NULL,
                progress INTEGER DEFAULT 0,
                reward INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                completed_at TIMESTAMPTZ
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_groups (
                chat_id BIGINT PRIMARY KEY,
                title TEXT,
                bot_is_admin BOOLEAN DEFAULT FALSE,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_group_mayors (
                chat_id BIGINT REFERENCES telegram_groups(chat_id) ON DELETE CASCADE,
                user_id BIGINT REFERENCES players(user_id) ON DELETE CASCADE,
                username TEXT,
                first_name TEXT,
                last_seen TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY(chat_id, user_id)
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS group_transfers (
                id BIGSERIAL PRIMARY KEY,
                chat_id BIGINT REFERENCES telegram_groups(chat_id) ON DELETE CASCADE,
                sender_id BIGINT REFERENCES players(user_id) ON DELETE CASCADE,
                recipient_id BIGINT REFERENCES players(user_id) ON DELETE CASCADE,
                resource_type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                deliver_at TIMESTAMPTZ NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weekly_seasons (
                week_key TEXT PRIMARY KEY,
                started_at TIMESTAMPTZ DEFAULT NOW(),
                ended BOOLEAN DEFAULT FALSE
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weekly_payouts (
                week_key TEXT PRIMARY KEY,
                paid_at TIMESTAMPTZ DEFAULT NOW(),
                first_user_id BIGINT,
                second_user_id BIGINT,
                third_user_id BIGINT,
                first_reward INTEGER DEFAULT 0,
                second_reward INTEGER DEFAULT 0,
                third_reward INTEGER DEFAULT 0
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS natural_disaster_schedule (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES players(user_id) ON DELETE CASCADE,
                disaster_date DATE NOT NULL,
                occurrence_no INTEGER NOT NULL,
                scheduled_at TIMESTAMPTZ NOT NULL,
                disaster_name TEXT NOT NULL,
                triggered BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(user_id, disaster_date, occurrence_no)
            )
            """
        )

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS natural_disaster_events (
                id BIGSERIAL PRIMARY KEY,
                schedule_id BIGINT REFERENCES natural_disaster_schedule(id) ON DELETE CASCADE,
                user_id BIGINT REFERENCES players(user_id) ON DELETE CASCADE,
                disaster_name TEXT NOT NULL,
                building_type TEXT,
                damage INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                repaired BOOLEAN DEFAULT FALSE,
                repaired_at TIMESTAMPTZ
            )
            """
        )

    logging.info("Database schema initialized.")


# =========================================================
# PLAYER
# =========================================================

async def ensure_player(message: Message):
    user = message.from_user

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO players(
                    user_id,
                    username,
                    first_name
                )
                VALUES($1,$2,$3)
                ON CONFLICT(user_id)
                DO UPDATE SET
                    username=$2,
                    first_name=$3
                """,
                user.id,
                user.username,
                user.first_name or "",
            )

            await conn.execute(
                """
                INSERT INTO cities(user_id)
                VALUES($1)
                ON CONFLICT(user_id)
                DO NOTHING
                """,
                user.id,
            )

            await conn.execute(
                """
                INSERT INTO resources(
                    user_id,
                    coins,
                    food,
                    materials,
                    energy,
                    water,
                    equipment
                )
                VALUES($1,$2,$3,$4,$5,$6,$7)
                ON CONFLICT(user_id)
                DO NOTHING
                """,
                user.id,
                START_COINS,
                START_FOOD,
                START_MATERIALS,
                START_ENERGY,
                START_WATER,
                START_EQUIPMENT,
            )

    return user.id


async def get_player(user_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT *
            FROM players
            WHERE user_id=$1
            """,
            user_id,
        )


async def get_city(user_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT *
            FROM cities
            WHERE user_id=$1
            """,
            user_id,
        )


async def get_resources(user_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT *
            FROM resources
            WHERE user_id=$1
            """,
            user_id,
        )


# =========================================================
# XP
# =========================================================

async def add_xp(user_id, amount):
    if amount <= 0:
        return

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            player = await conn.fetchrow(
                """
                SELECT xp, level
                FROM players
                WHERE user_id=$1
                FOR UPDATE
                """,
                user_id,
            )

            if not player:
                return

            xp = player["xp"] + amount
            level = player["level"]

            while level < MAX_LEVEL:
                required = level * 250

                if xp < required:
                    break

                xp -= required
                level += 1

            await conn.execute(
                """
                UPDATE players
                SET xp=$1,
                    level=$2
                WHERE user_id=$3
                """,
                xp,
                level,
                user_id,
            )


# =========================================================
# CITY CALCULATION
# =========================================================

async def recalculate_city(user_id):
    async with db_pool.acquire() as conn:
        city = await conn.fetchrow(
            """
            SELECT *
            FROM cities
            WHERE user_id=$1
            """,
            user_id,
        )

        if not city:
            return

        rows = await conn.fetch(
            """
            SELECT building_type, level
            FROM buildings
            WHERE user_id=$1
            """,
            user_id,
        )

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

            level = max(0, row["level"])

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

            housing_bonus += (
                building.get("housing", 0) * level
            )

            if row["building_type"] == "school":
                housing_bonus += level * 10

            elif row["building_type"] == "university":
                housing_bonus += level * 20

            elif row["building_type"] == "roads":
                housing_bonus += level * 20

        pollution_net = max(
            0,
            pollution - stats["pollution_control"],
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

        housing = (
            150
            + city["land"] * 100
            + housing_bonus
        )

        jobs = max(
            20,
            START_JOBS
            + job_bonus
            + city["population"] // 3,
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
            - max(
                0,
                city["population"] - housing,
            ) // 20
            - max(
                0,
                city["tax_rate"] - 10,
            ) * 2
        )

        satisfaction = clamp(
            satisfaction,
            0,
            MAX_SATISFACTION,
        )

        await conn.execute(
            """
            UPDATE cities
            SET
                security=$1,
                fire_safety=$2,
                health=$3,
                power=$4,
                water=$5,
                education=$6,
                recreation=$7,
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
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock($1)",
                int(user_id),
            )

            city = await conn.fetchrow(
                """
                SELECT *
                FROM cities
                WHERE user_id=$1
                FOR UPDATE
                """,
                user_id,
            )

            if not city:
                return 0

            last_income = city["last_income"]

            if last_income is None:
                last_income = now_utc()

            elapsed = now_utc() - last_income

            if elapsed < timedelta(minutes=25):
                return 0

            periods = max(
                1,
                int(
                    elapsed.total_seconds()
                    // 1800
                ),
            )

            periods = min(periods, 8)

            tax_income = int(
                city["population"]
                * city["tax_rate"]
                * max(city["satisfaction"], 20)
                / 10000
            )

            economic_income = city["economy"] * 2

            maintenance = 0
            building_income_hourly = 0
            building_materials_hourly = 0

            rows = await conn.fetch(
                """
                SELECT building_type, level
                FROM buildings
                WHERE user_id=$1
                """,
                user_id,
            )

            for row in rows:
                data = BUILDINGS.get(
                    row["building_type"]
                )

                if data:
                    maintenance += (
                        data["maintenance"]
                        * row["level"]
                    )
                    building_income_hourly += (
                        data.get("income_hourly", 0)
                        * row["level"]
                    )
                    building_materials_hourly += (
                        data.get("material_income_hourly", 0)
                        * row["level"]
                    )

            # حداقل درآمد خالص شهر: ۵۰ سکه در ساعت (۲۵ سکه در هر دوره ۳۰ دقیقه‌ای).
            base_income = max(
                25 + maintenance,
                tax_income + economic_income + (building_income_hourly // 2),
            )

            final_income = max(25, base_income - maintenance) * periods
            material_gain = 10 * periods + (building_materials_hourly * periods)

            await conn.execute(
                """
                UPDATE resources
                SET coins=GREATEST(0, coins+$1),
                    materials=GREATEST(0, materials+$2)
                WHERE user_id=$3
                """,
                final_income, material_gain, user_id,
            )

            await conn.execute(
                """
                UPDATE cities
                SET last_income=NOW()
                WHERE user_id=$1
                """,
                user_id,
            )

            return final_income


# =========================================================
# CITY DASHBOARD
# =========================================================

async def city_text(user_id):
    await recalculate_city(user_id)

    city = await get_city(user_id)
    player = await get_player(user_id)

    if not city or not player:
        return "❌ اطلاعات شهر پیدا نشد."

    city_name = safe_text(city["city_name"])
    first_name = safe_text(
        player["first_name"] or "شهردار"
    )

    return (
        f"🏙️ <b>{city_name}</b>\n\n"
        f"👑 شهردار: {first_name}\n\n"
        f"⭐ سطح شهردار: {player['level']}\n"
        f"✨ XP: {player['xp']}\n\n"
        f"👥 جمعیت: {city['population']:,}\n"
        f"💼 شغل‌ها: {city['jobs']:,}\n"
        f"😊 رضایت: {city['satisfaction']}%\n"
        f"📈 اقتصاد: {city['economy']}%\n\n"
        f"🏠 ظرفیت مسکن: "
        f"{city['housing_capacity']:,}\n"
        f"🗺️ زمین: {city['land']}\n"
        f"🏘️ روستاهای جذب‌شده: "
        f"{city['villages']}\n\n"
        f"💰 مالیات: {city['tax_rate']}%"
    )


# =========================================================
# CITIZENS SYSTEM
# =========================================================

async def calculate_citizen_metrics(user_id):
    await recalculate_city(user_id)

    city = await get_city(user_id)

    if not city:
        return None

    population = city["population"]
    jobs = city["jobs"]

    unemployment, employed = employment_status(
        population,
        jobs,
    )

    housing_capacity = city["housing_capacity"]

    if population <= housing_capacity:
        housing_score = 100
    else:
        shortage = population - housing_capacity
        housing_score = clamp(
            100 - shortage * 2,
            0,
            100,
        )

    employment_score = clamp(
        100 - unemployment * 2,
        0,
        100,
    )

    tax_score = clamp(
        100
        - max(0, city["tax_rate"] - 5) * 5,
        0,
        100,
    )

    water_score = clamp(
        city["water"],
        0,
        100,
    )

    power_score = clamp(
        city["power"],
        0,
        100,
    )

    security_score = clamp(
        city["security"],
        0,
        100,
    )

    health_score = clamp(
        city["health"],
        0,
        100,
    )

    education_score = clamp(
        city["education"],
        0,
        100,
    )

    recreation_score = clamp(
        city["recreation"],
        0,
        100,
    )

    infrastructure_score = clamp(
        city["infrastructure"],
        0,
        100,
    )

    pollution_score = clamp(
        100 - max(
            0,
            city["pollution_control"] - 20,
        ),
        0,
        100,
    )

    overall = int(
        security_score * 0.14
        + health_score * 0.14
        + employment_score * 0.14
        + housing_score * 0.14
        + water_score * 0.10
        + power_score * 0.10
        + education_score * 0.08
        + recreation_score * 0.06
        + infrastructure_score * 0.06
        + tax_score * 0.04
    )

    overall = clamp(
        overall,
        0,
        100,
    )

    return {
        "population": population,
        "jobs": jobs,
        "employed": employed,
        "unemployment": unemployment,
        "housing": housing_score,
        "security": security_score,
        "health": health_score,
        "employment": employment_score,
        "water": water_score,
        "power": power_score,
        "education": education_score,
        "recreation": recreation_score,
        "infrastructure": infrastructure_score,
        "pollution": pollution_score,
        "tax": tax_score,
        "overall": overall,
    }


@dp.callback_query(F.data == "citizens")
async def citizens_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id

    await ensure_callback_player(user_id)
    await process_player_tick(user_id)

    metrics = await calculate_citizen_metrics(
        user_id
    )

    if not metrics:
        await callback.message.edit_text(
            "❌ اطلاعات شهروندان پیدا نشد.",
            reply_markup=back_keyboard(),
        )
        return

    city = await get_city(user_id)

    city_name = safe_text(
        city["city_name"]
    )

    status = satisfaction_status(
        metrics["overall"]
    )

    text = (
        "👥 <b>شهروندان شهر</b>\n\n"
        f"🏙️ شهر: {city_name}\n\n"
        f"👥 جمعیت: {metrics['population']:,}\n"
        f"💼 شاغلان: {metrics['employed']:,}\n"
        f"📉 بیکاری: {metrics['unemployment']}%\n\n"
        f"😊 رضایت شهروندان: "
        f"<b>{metrics['overall']}%</b> {status}\n\n"
        f"{citizen_bar(metrics['overall'])}\n\n"
        "━━━━━━━━━━━━\n\n"
        f"🏠 مسکن: {metrics['housing']}%\n"
        f"{citizen_bar(metrics['housing'])}\n\n"
        f"💼 اشتغال: {metrics['employment']}%\n"
        f"{citizen_bar(metrics['employment'])}\n\n"
        f"🚓 امنیت: {metrics['security']}%\n"
        f"{citizen_bar(metrics['security'])}\n\n"
        f"🏥 سلامت: {metrics['health']}%\n"
        f"{citizen_bar(metrics['health'])}\n\n"
        f"💧 آب: {metrics['water']}%\n"
        f"{citizen_bar(metrics['water'])}\n\n"
        f"⚡ برق: {metrics['power']}%\n"
        f"{citizen_bar(metrics['power'])}\n\n"
        f"🎓 آموزش: {metrics['education']}%\n"
        f"{citizen_bar(metrics['education'])}\n\n"
        f"🌳 تفریح: {metrics['recreation']}%\n"
        f"{citizen_bar(metrics['recreation'])}\n\n"
        f"🛣️ زیرساخت: "
        f"{metrics['infrastructure']}%\n"
        f"{citizen_bar(metrics['infrastructure'])}\n\n"
        f"🌫️ محیط‌زیست: "
        f"{metrics['pollution']}%\n"
        f"{citizen_bar(metrics['pollution'])}\n\n"
        f"💰 رضایت از مالیات: "
        f"{metrics['tax']}%\n"
        f"{citizen_bar(metrics['tax'])}\n\n"
        "━━━━━━━━━━━━\n\n"
        "<b>اثر رضایت بالا:</b>\n\n"
        "📈 رشد جمعیت بیشتر\n"
        "💰 درآمد شهر بیشتر\n"
        "👥 مهاجرت مثبت بیشتر\n"
        "🏙️ توسعه شهر سریع‌تر"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 بروزرسانی",
                    callback_data="citizens",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏙️ شهر من",
                    callback_data="city",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 منوی اصلی",
                    callback_data="menu",
                )
            ],
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
    )


# =========================================================
# CALLBACK PLAYER
# =========================================================

async def ensure_callback_player(user_id):
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO players(
                user_id,
                username,
                first_name
            )
            VALUES($1,NULL,'')
            ON CONFLICT(user_id)
            DO NOTHING
            """,
            user_id,
        )

        await conn.execute(
            """
            INSERT INTO cities(user_id)
            VALUES($1)
            ON CONFLICT(user_id)
            DO NOTHING
            """,
            user_id,
        )

        await conn.execute(
            """
            INSERT INTO resources(user_id)
            VALUES($1)
            ON CONFLICT(user_id)
            DO NOTHING
            """,
            user_id,
        )


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
        "شهر رو بساز، اقتصاد رو رشد بده، "
        "بحران‌ها رو مدیریت کن و با "
        "شهرداران دیگر رقابت کن.\n\n"
        + text,
        reply_markup=main_keyboard(),
    )

    await message.answer(
        "برای ورود سریع به بازی از دکمه پایین استفاده کن. 🚀",
        reply_markup=start_reply_keyboard(),
    )


@dp.message(F.text == "🚀 شروع بازی")
async def start_button_handler(message: Message):
    await start_handler(message)


# =========================================================
# MENU
# =========================================================

@dp.callback_query(F.data == "menu")
async def menu_callback(callback: CallbackQuery):
    await callback.answer()

    await ensure_callback_player(
        callback.from_user.id
    )

    await callback.message.edit_text(
        "🏙️ <b>شهر من</b>\n\n"
        "شهردار، شهر آماده مدیریت توئه!",
        reply_markup=main_keyboard(),
    )


# =========================================================
# CITY
# =========================================================

@dp.callback_query(F.data == "city")
async def city_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id

    await ensure_callback_player(user_id)
    await process_player_tick(user_id)

    await callback.message.edit_text(
        await city_text(user_id),
        reply_markup=back_keyboard(),
    )


# =========================================================
# MAYOR
# =========================================================

@dp.callback_query(F.data == "mayor")
async def mayor_callback(callback: CallbackQuery):
    await callback.answer()

    user_id = callback.from_user.id

    await ensure_callback_player(user_id)
    await process_player_tick(user_id)

    player = await get_player(user_id)
    city = await get_city(user_id)

    if not player or not city:
        await callback.message.edit_text(
            "❌ اطلاعات شهردار پیدا نشد.",
            reply_markup=back_keyboard(),
        )
        return

    text = (
        "👑 <b>دفتر شهردار</b>\n\n"
        f"👤 {safe_text(player['first_name'] or 'شهردار')}\n\n"
        f"🏙️ شهر: {safe_text(city['city_name'])}\n\n"
        f"⭐ سطح: {player['level']}\n"
        f"✨ XP: {player['xp']}\n\n"
        f"😊 رضایت: {city['satisfaction']}%\n"
        f"📈 اقتصاد: {city['economy']}%\n\n"
        "📊 <b>وضعیت خدمات:</b>\n\n"
        f"🚓 امنیت: {city['security']}\n"
        f"🚒 ایمنی آتش: {city['fire_safety']}\n"
        f"🏥 سلامت: {city['health']}\n"
        f"⚡ برق: {city['power']}\n"
        f"💧 آب: {city['water']}\n"
        f"🎓 آموزش: {city['education']}\n"
        f"🌳 تفریح: {city['recreation']}\n"
        f"🛣️ زیرساخت: {city['infrastructure']}\n"
        f"♻️ کنترل آلودگی: "
        f"{city['pollution_control']}\n"
        f"🚑 مدیریت بحران: {city['crisis']}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=back_keyboard(),
    )


# =========================================================
# BUILDINGS
# =========================================================

@dp.callback_query(F.data == "buildings")
async def buildings_callback(
    callback: CallbackQuery
):
    await callback.answer()

    user_id = callback.from_user.id
    await ensure_callback_player(user_id)

    async with db_pool.acquire() as conn:
        damages = await conn.fetch(
            """
            SELECT id, building_type, damage, created_at
            FROM natural_disaster_events
            WHERE user_id=$1 AND repaired=FALSE
            ORDER BY created_at DESC
            """,
            user_id,
        )

    damage_text = ""
    damage_buttons = []
    if damages:
        damage_text = "\n\n🚨 <b>خسارت‌های تعمیرنشده</b>\n"
        for d in damages:
            current_damage = d["damage"] + max(0, int((now_utc() - d["created_at"]).total_seconds() // 3600)) * 10
            bname = BUILDINGS.get(d["building_type"], {}).get("name", d["building_type"])
            damage_text += f"\n🏢 {safe_text(bname)} — 💰 {current_damage:,} سکه\n"
            damage_buttons.append([InlineKeyboardButton(text=f"🔧 تعمیر {bname} ({current_damage:,})", callback_data=f"natural_repair:{d['id']}")])

    await callback.message.edit_text(
        "🏗️ <b>ساختمان‌های شهر</b>\n\n"
        "یک ساختمان را انتخاب کن تا سطح، هزینه و اثر آن را ببینی." + damage_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=damage_buttons + (await building_keyboard(user_id)).inline_keyboard),
    )


@dp.callback_query(F.data.startswith("building:"))
async def building_handler(
    callback: CallbackQuery
):
    await callback.answer()

    user_id = callback.from_user.id

    await ensure_callback_player(user_id)

    key = callback.data.split(
        ":",
        1,
    )[1]

    data = BUILDINGS.get(key)

    if not data:
        await callback.answer(
            "ساختمان پیدا نشد.",
            show_alert=True,
        )
        return

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock($1)",
                int(user_id),
            )

            active_construction = await conn.fetchrow(
                "SELECT * FROM building_constructions WHERE user_id=$1 AND completed=FALSE FOR UPDATE",
                user_id,
            )
            if active_construction:
                remaining = max(0, int((active_construction["ready_at"] - now_utc()).total_seconds()))
                hours, rem = divmod(remaining, 3600)
                minutes = rem // 60
                await callback.answer(
                    f"⏳ هنوز ساخت/ارتقای {BUILDINGS[active_construction['building_type']]['name']} تمام نشده؛ {hours} ساعت و {minutes} دقیقه باقی مانده.",
                    show_alert=True,
                )
                return

            current = await conn.fetchval(
                "SELECT level FROM buildings WHERE user_id=$1 AND building_type=$2 FOR UPDATE",
                user_id, key,
            ) or 0
            next_level = current + 1
            cost = int(data["cost"] * (1 + current * 0.45))
            material = int(data["material"] * (1 + current * 0.45))
            duration_hours = BUILDING_UPGRADE_HOURS.get(current, 80 if current >= 5 else 2)

            resources = await conn.fetchrow(
                """
                SELECT coins, materials
                FROM resources
                WHERE user_id=$1
                FOR UPDATE
                """,
                user_id,
            )

            action = "ساخت" if current == 0 else "ارتقا"
            housing_effect = data.get("housing", 0)
            text = (
                f"{data['name']}\n\n"
                f"📖 {safe_text(data['description'])}\n\n"
                f"📊 سطح فعلی: {current if current else 'ساخته نشده'}\n"
                f"⬆️ سطح بعدی: {next_level}\n"
                f"⏱️ زمان {action}: {duration_hours} ساعت\n\n"
                f"💰 هزینه: {cost:,} سکه\n"
                f"🧱 مصالح: {material:,}\n"
            )

            if housing_effect:
                text += (
                    f"\n🏠 افزایش ظرفیت مسکن: "
                    f"+{housing_effect}"
                )

            if (
                resources["coins"] < cost
                or resources["materials"] < material
            ):
                text += (
                    f"\n\n❌ برای {action} "
                    "منابع کافی نداری."
                )

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

            await conn.execute(
                """
                UPDATE resources
                SET
                    coins=coins-$1,
                    materials=materials-$2
                WHERE user_id=$3
                """,
                cost,
                material,
                user_id,
            )

            ready_at = now_utc() + timedelta(hours=duration_hours)
            await conn.execute(
                "INSERT INTO building_constructions(user_id, building_type, target_level, ready_at) VALUES($1,$2,$3,$4)",
                user_id, key, next_level, ready_at,
            )

    await add_xp(user_id, 20)

    try:
        await bot.send_message(
            user_id,
            f"🏗️ <b>{safe_text(data['name'])}</b>\n\n"
            f"{action} سطح {next_level} با موفقیت شروع شد.\n"
            f"⏳ زمان لازم: <b>{duration_hours} ساعت</b>\n"
            f"پس از پایان زمان، سطح {next_level} فعال می‌شود."
        )
    except Exception:
        logging.exception("Could not notify building construction start")

    await callback.message.edit_text(
        text
        + f"\n\n⏳ {action} شروع شد."
        + f"\n🏗️ بعد از {duration_hours} ساعت، سطح {next_level} فعال می‌شود.",
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
async def resources_callback(
    callback: CallbackQuery
):
    await callback.answer()

    user_id = callback.from_user.id

    await ensure_callback_player(user_id)
    await process_player_tick(user_id)

    resources = await get_resources(user_id)

    if not resources:
        await callback.message.edit_text(
            "❌ منابع شهر پیدا نشد.",
            reply_markup=back_keyboard(),
        )
        return

    text = (
        "📦 <b>منابع شهر</b>\n\n"
        f"💰 سکه: {resources['coins']:,}\n"
        f"🍞 غذا: {resources['food']:,}\n"
        f"🧱 مصالح: {resources['materials']:,}\n"
        f"⚡ انرژی: {resources['energy']:,}\n"
        f"💧 آب: {resources['water']:,}\n"
        f"🧰 تجهیزات: {resources['equipment']:,}\n\n"
        "منابع برای توسعه، بازار، کمک به "
        "شهرهای دیگر و مدیریت بحران‌ها استفاده می‌شوند."
    )

    await callback.message.edit_text(
        text,
        reply_markup=back_keyboard(),
    )


# =========================================================
# ECONOMY
# =========================================================

async def economy_screen(callback):
    user_id = callback.from_user.id

    await ensure_callback_player(user_id)

    await recalculate_city(user_id)

    income = await collect_income(user_id)

    city = await get_city(user_id)
    resources = await get_resources(user_id)

    if not city or not resources:
        await callback.message.edit_text(
            "❌ اطلاعات اقتصاد پیدا نشد.",
            reply_markup=back_keyboard(),
        )
        return

    text = (
        "💰 <b>اقتصاد شهر</b>\n\n"
        f"📈 قدرت اقتصادی: {city['economy']}%\n\n"
        f"💵 درآمد دریافت‌شده: "
        f"{income:,} سکه\n"
        f"💰 موجودی: "
        f"{resources['coins']:,} سکه\n\n"
        f"👥 جمعیت: {city['population']:,}\n"
        f"💼 شغل‌ها: {city['jobs']:,}\n\n"
        f"🏷️ مالیات: {city['tax_rate']}%\n"
        f"😊 رضایت: {city['satisfaction']}%\n\n"
        "مالیات بیشتر درآمد را بالا می‌برد، "
        "اما می‌تواند رضایت شهروندان را کاهش دهد."
    )

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
async def economy_callback(
    callback: CallbackQuery
):
    await callback.answer()
    await economy_screen(callback)


@dp.callback_query(F.data == "tax_up")
async def tax_up(callback: CallbackQuery):
    user_id = callback.from_user.id

    await ensure_callback_player(user_id)

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE cities
            SET tax_rate=LEAST(
                25,
                tax_rate+2
            )
            WHERE user_id=$1
            """,
            user_id,
        )

    await recalculate_city(user_id)

    await callback.answer(
        "مالیات افزایش یافت."
    )

    await economy_screen(callback)


@dp.callback_query(F.data == "tax_down")
async def tax_down(callback: CallbackQuery):
    user_id = callback.from_user.id

    await ensure_callback_player(user_id)

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE cities
            SET tax_rate=GREATEST(
                0,
                tax_rate-2
            )
            WHERE user_id=$1
            """,
            user_id,
        )

    await recalculate_city(user_id)

    await callback.answer(
        "مالیات کاهش یافت."
    )

    await economy_screen(callback)


# =========================================================
# CRISIS
# =========================================================

async def get_active_crisis(user_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT *
            FROM crises
            WHERE user_id=$1
              AND status='active'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            user_id,
        )


async def create_crisis(user_id):
    existing = await get_active_crisis(user_id)

    if existing:
        return existing

    city = await get_city(user_id)

    if not city:
        return None

    crisis_type = random.choice(
        list(CRISES.keys())
    )

    data = CRISES[crisis_type]

    service = city[data["stat"]]

    severity = int(
        data["base_severity"]
        - service * 0.7
        + random.randint(-10, 15)
    )

    severity = clamp(
        severity,
        10,
        100,
    )

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            crisis = await conn.fetchrow(
                """
                INSERT INTO crises(
                    user_id,
                    crisis_type,
                    severity,
                    status
                )
                VALUES($1,$2,$3,'active')
                RETURNING *
                """,
                user_id,
                crisis_type,
                severity,
            )

            await conn.execute(
                """
                INSERT INTO news(
                    user_id,
                    text
                )
                VALUES($1,$2)
                """,
                user_id,
                f"⚠️ بحران جدید: {data['name']}",
            )

            await conn.execute(
                """
                UPDATE cities
                SET satisfaction=GREATEST(
                    0,
                    satisfaction-$1
                )
                WHERE user_id=$2
                """,
                max(
                    1,
                    severity // 15,
                ),
                user_id,
            )

    return crisis


@dp.callback_query(F.data == "crises")
async def crises_callback(
    callback: CallbackQuery
):
    await callback.answer()

    user_id = callback.from_user.id

    await ensure_callback_player(user_id)
    await process_player_tick(user_id)

    crisis = await get_active_crisis(user_id)

    if not crisis:
        await callback.message.edit_text(
            "🟢 <b>بحران فعالی وجود ندارد.</b>\n\n"
            "شهر فعلاً پایدار است. 🌆\n\n"
            "اما همیشه آماده باش؛ "
            "بحران‌ها ناگهانی اتفاق می‌افتند.",
            reply_markup=back_keyboard(),
        )
        return

    data = CRISES.get(
        crisis["crisis_type"]
    )

    if not data:
        await callback.message.edit_text(
            "❌ نوع بحران نامعتبر است.",
            reply_markup=back_keyboard(),
        )
        return

    text = (
        "🚨 <b>بحران فعال!</b>\n\n"
        f"{data['name']}\n\n"
        f"🔥 شدت: {crisis['severity']} / 100\n"
        f"🏛️ خدمت اصلی: "
        f"{CRISIS_STAT_NAMES.get(data['stat'], data['stat'])}\n"
        f"🎁 پاداش: "
        f"{data['reward']} سکه\n\n"
        "برای مدیریت بحران روی دکمه زیر بزن."
    )

    await callback.message.edit_text(
        text,
        reply_markup=crisis_keyboard(
            crisis["id"]
        ),
    )


@dp.callback_query(
    F.data.startswith("resolve:")
)
async def resolve_crisis(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    await ensure_callback_player(user_id)

    try:
        crisis_id = int(
            callback.data.split(
                ":",
                1,
            )[1]
        )
    except ValueError:
        await callback.answer(
            "شناسه بحران نامعتبر است.",
            show_alert=True,
        )
        return

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock($1)",
                int(user_id),
            )

            crisis = await conn.fetchrow(
                """
                SELECT *
                FROM crises
                WHERE id=$1
                FOR UPDATE
                """,
                crisis_id,
            )

            if (
                not crisis
                or crisis["user_id"] != user_id
            ):
                await callback.answer(
                    "این بحران متعلق به شهر تو نیست.",
                    show_alert=True,
                )
                return

            if crisis["status"] != "active":
                await callback.answer(
                    "این بحران قبلاً حل شده.",
                    show_alert=True,
                )
                return

            city = await conn.fetchrow(
                """
                SELECT *
                FROM cities
                WHERE user_id=$1
                FOR UPDATE
                """,
                user_id,
            )

            resources = await conn.fetchrow(
                """
                SELECT *
                FROM resources
                WHERE user_id=$1
                FOR UPDATE
                """,
                user_id,
            )

            data = CRISES.get(
                crisis["crisis_type"]
            )

            if not data:
                await callback.answer(
                    "نوع بحران نامعتبر است.",
                    show_alert=True,
                )
                return

            required = max(
                20,
                crisis["severity"] * 2,
            )

            resource_name = data["resource"]

            available = resources[
                resource_name
            ]

            if available < required:
                resource_labels = {
                    "coins": "سکه",
                    "water": "آب",
                    "energy": "انرژی",
                    "materials": "مصالح",
                }

                await callback.answer(
                    "❌ "
                    + resource_labels.get(
                        resource_name,
                        "منبع",
                    )
                    + " کافی نیست.",
                    show_alert=True,
                )
                return

            service = city[data["stat"]]

            success_chance = clamp(
                45 + service // 2,
                20,
                95,
            )

            roll = random.randint(
                1,
                100,
            )

            if roll <= success_chance:
                reward = (
                    data["reward"]
                    + city["economy"]
                )

                equipment_reward = max(
                    1,
                    crisis["severity"] // 20,
                )

                await conn.execute(
                    f"""
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
                    equipment_reward,
                    user_id,
                )

                await conn.execute(
                    """
                    UPDATE crises
                    SET
                        status='resolved',
                        resolved_at=NOW()
                    WHERE id=$1
                    """,
                    crisis_id,
                )

                await conn.execute(
                    """
                    UPDATE cities
                    SET satisfaction=LEAST(
                        100,
                        satisfaction+5
                    )
                    WHERE user_id=$1
                    """,
                    user_id,
                )

                await conn.execute(
                    """
                    INSERT INTO news(
                        user_id,
                        text
                    )
                    VALUES($1,$2)
                    """,
                    user_id,
                    f"✅ بحران {data['name']} "
                    "با موفقیت مدیریت شد.",
                )

                result = (
                    "✅ <b>بحران با موفقیت حل شد!</b>\n\n"
                    f"{data['name']}\n\n"
                    f"🎯 شانس موفقیت: "
                    f"{success_chance}%\n"
                    "🎲 نتیجه: موفق\n\n"
                    f"💰 پاداش: {reward:,} سکه\n"
                    f"🧰 تجهیزات دریافت‌شده: "
                    f"{equipment_reward}\n"
                    "😊 رضایت +5"
                )

                xp = 100

            else:
                failed_cost = max(
                    1,
                    required // 2,
                )

                await conn.execute(
                    f"""
                    UPDATE resources
                    SET {resource_name}=GREATEST(
                        0,
                        {resource_name}-$1
                    )
                    WHERE user_id=$2
                    """,
                    failed_cost,
                    user_id,
                )

                await conn.execute(
                    """
                    UPDATE cities
                    SET satisfaction=GREATEST(
                        0,
                        satisfaction-5
                    )
                    WHERE user_id=$1
                    """,
                    user_id,
                )

                result = (
                    "❌ <b>مدیریت بحران شکست خورد!</b>\n\n"
                    f"{data['name']}\n\n"
                    f"🎯 شانس موفقیت: "
                    f"{success_chance}%\n"
                    "🎲 نتیجه: شکست\n\n"
                    "⚠️ بخشی از منابع مصرف شد.\n"
                    "😊 رضایت -5\n\n"
                    "دوباره تلاش کن."
                )

                xp = 30

    await add_xp(
        user_id,
        xp,
    )

    await recalculate_city(
        user_id
    )

    await callback.answer()

    await callback.message.edit_text(
        result,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🚨 بحران‌ها",
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
async def social_callback(
    callback: CallbackQuery
):
    await callback.answer()

    user_id = callback.from_user.id

    await ensure_callback_player(user_id)

    async with db_pool.acquire() as conn:
        friends = await conn.fetch(
            """
            SELECT
                p.user_id,
                p.first_name,
                c.city_name
            FROM friendships f
            JOIN players p
                ON p.user_id=f.friend_id
            JOIN cities c
                ON c.user_id=p.user_id
            WHERE f.user_id=$1
            LIMIT 10
            """,
            user_id,
        )

        pending = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM friend_requests
            WHERE receiver_id=$1
              AND status='pending'
            """,
            user_id,
        )


    if friends:
        friend_lines = []

        for friend in friends:
            friend_lines.append(
                f"👤 {safe_text(friend['first_name'])}\n"
                f"🏙️ {safe_text(friend['city_name'])}"
            )

        friend_text = "\n\n".join(
            friend_lines
        )

    else:
        friend_text = (
            "هنوز دوستی نداری.\n"
            "می‌توانی یک شهردار دیگر را "
            "به دوستانت اضافه کنی."
        )


    pending = pending or 0

    text = (
        "🤝 <b>بخش اجتماعی</b>\n\n"
        "👤 <b>دوستان من</b>\n\n"
        f"{friend_text}\n\n"
        "━━━━━━━━━━━━\n\n"
        "📨 <b>درخواست‌های جدید</b>\n\n"
        f"تعداد درخواست‌های جدید: "
        f"{pending}\n\n"
        "━━━━━━━━━━━━\n\n"
        "از دکمه‌های زیر برای مدیریت "
        "ارتباطاتت استفاده کن."
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📨 درخواست‌ها",
                    callback_data="friend_requests",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 بروزرسانی",
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
    )

    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
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
            "❌ فرمت اشتباه است.\n\n"
            "مثال:\n"
            "<code>/addfriend 123456789</code>"
        )
        return

    try:
        receiver_id = int(parts[1])
    except ValueError:
        await message.answer(
            "❌ شناسه بازیکن اشتباه است."
        )
        return

    if receiver_id == user_id:
        await message.answer(
            "❌ نمی‌توانی خودت را دوست خودت کنی."
        )
        return

    async with db_pool.acquire() as conn:
        target = await conn.fetchrow(
            """
            SELECT user_id, first_name
            FROM players
            WHERE user_id=$1
            """,
            receiver_id,
        )

        if not target:
            await message.answer(
                "❌ بازیکن پیدا نشد."
            )
            return

        exists = await conn.fetchval(
            """
            SELECT 1
            FROM friendships
            WHERE user_id=$1
              AND friend_id=$2
            """,
            user_id,
            receiver_id,
        )

        if exists:
            await message.answer(
                "✅ این بازیکن از قبل دوست توست."
            )
            return

        await conn.execute(
            """
            INSERT INTO friend_requests(
                sender_id,
                receiver_id,
                status
            )
            VALUES($1,$2,'pending')
            ON CONFLICT(
                sender_id,
                receiver_id
            )
            DO UPDATE SET
                status='pending'
            """,
            user_id,
            receiver_id,
        )

    await message.answer(
        "📨 درخواست دوستی برای "
        f"<b>{safe_text(target['first_name'])}</b> "
        "ارسال شد."
    )

    try:
        await bot.send_message(
            receiver_id,
            "📨 یک درخواست دوستی جدید داری!\n"
            "برای مشاهده از بخش «🤝 اجتماعی» استفاده کن.",
        )
    except Exception:
        pass


# =========================================================
# FRIEND REQUESTS
# =========================================================

@dp.callback_query(
    F.data == "friend_requests"
)
async def friend_requests_callback(
    callback: CallbackQuery
):
    await callback.answer()

    user_id = callback.from_user.id

    await ensure_callback_player(user_id)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                fr.id,
                p.first_name,
                p.user_id
            FROM friend_requests fr
            JOIN players p
                ON p.user_id=fr.sender_id
            WHERE fr.receiver_id=$1
              AND fr.status='pending'
            ORDER BY fr.created_at DESC
            LIMIT 10
            """,
            user_id,
        )

    if not rows:
        text = (
            "📨 <b>درخواست دوستی</b>\n\n"
            "درخواست جدیدی نداری."
        )

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

        await callback.message.edit_text(
            text,
            reply_markup=keyboard,
        )
        return

    lines = [
        "📨 <b>درخواست‌های دوستی</b>\n"
    ]

    buttons = []

    for row in rows:
        lines.append(
            f"👤 {safe_text(row['first_name'])}\n"
            f"🆔 شناسه: {row['user_id']}"
        )

        buttons.append(
            [
                InlineKeyboardButton(
                    text=(
                        "✅ قبول "
                        f"{safe_text(row['first_name'])}"
                    ),
                    callback_data=(
                        f"accept_friend:{row['id']}"
                    ),
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="🔙 اجتماعی",
                callback_data="social",
            )
        ]
    )

    await callback.message.edit_text(
        "\n\n".join(lines),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        ),
    )


@dp.callback_query(
    F.data.startswith("accept_friend:")
)
async def accept_friend(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    try:
        request_id = int(
            callback.data.split(
                ":",
                1,
            )[1]
        )
    except ValueError:
        await callback.answer(
            "درخواست نامعتبر است.",
            show_alert=True,
        )
        return

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            request = await conn.fetchrow(
                """
                SELECT *
                FROM friend_requests
                WHERE id=$1
                FOR UPDATE
                """,
                request_id,
            )

            if (
                not request
                or request["receiver_id"] != user_id
            ):
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

            await conn.execute(
                """
                UPDATE friend_requests
                SET status='accepted'
                WHERE id=$1
                """,
                request_id,
            )

            await conn.execute(
                """
                INSERT INTO friendships(
                    user_id,
                    friend_id
                )
                VALUES($1,$2),($2,$1)
                ON CONFLICT DO NOTHING
                """,
                sender_id,
                user_id,
            )

    await callback.answer(
        "✅ دوستی ایجاد شد."
    )

    try:
        await bot.send_message(
            sender_id,
            "🎉 درخواست دوستی تو قبول شد!",
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
        await message.answer(
            "❌ فرمت اشتباه است.\n\n"
            "مثال:\n"
            "<code>/help 123456789 100 50 30</code>\n\n"
            "ترتیب:\n"
            "PLAYER_ID COINS FOOD MATERIALS"
        )
        return

    try:
        receiver_id = int(parts[1])
        coins = max(0, int(parts[2]))
        food = max(0, int(parts[3]))
        materials = max(0, int(parts[4]))
    except ValueError:
        await message.answer(
            "❌ اعداد را درست وارد کن."
        )
        return

    if receiver_id == user_id:
        await message.answer(
            "❌ نمی‌توانی به شهر خودت کمک بفرستی."
        )
        return

    total = coins + food + materials

    if total <= 0:
        await message.answer(
            "❌ مقدار کمک باید بیشتر از صفر باشد."
        )
        return

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            receiver = await conn.fetchrow(
                """
                SELECT user_id
                FROM players
                WHERE user_id=$1
                """,
                receiver_id,
            )

            if not receiver:
                await message.answer(
                    "❌ شهر مقصد پیدا نشد."
                )
                return

            ids = sorted(
                [user_id, receiver_id]
            )

            resources_rows = await conn.fetch(
                """
                SELECT *
                FROM resources
                WHERE user_id = ANY($1::bigint[])
                ORDER BY user_id
                FOR UPDATE
                """,
                ids,
            )

            resources_map = {
                row["user_id"]: row
                for row in resources_rows
            }

            sender = resources_map.get(
                user_id
            )

            target = resources_map.get(
                receiver_id
            )

            if not sender or not target:
                await message.answer(
                    "❌ اطلاعات منابع پیدا نشد."
                )
                return

            if (
                sender["coins"] < coins
                or sender["food"] < food
                or sender["materials"] < materials
            ):
                await message.answer(
                    "❌ منابع کافی برای ارسال کمک نداری."
                )
                return

            await conn.execute(
                """
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

            await conn.execute(
                """
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

            await conn.execute(
                """
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

    await add_xp(
        user_id,
        20,
    )

    await message.answer(
        "🤝 <b>کمک با موفقیت ارسال شد!</b>\n\n"
        f"💰 سکه: {coins:,}\n"
        f"🍞 غذا: {food:,}\n"
        f"🧱 مصالح: {materials:,}\n\n"
        "⭐ +20 XP"
    )

    try:
        await bot.send_message(
            receiver_id,
            "🤝 یک شهردار برای شهر تو کمک ارسال کرد!",
        )
    except Exception:
        pass


# =========================================================
# MARKET
# =========================================================

@dp.callback_query(F.data == "market")
async def market_callback(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    await ensure_callback_player(user_id)

    async with db_pool.acquire() as conn:
        offers = await conn.fetch(
            """
            SELECT mo.*, p.first_name
            FROM market_offers mo
            JOIN players p ON p.user_id=mo.seller_id
            WHERE mo.status='active'
            ORDER BY mo.created_at DESC
            LIMIT 10
            """
        )

    lines = ["🏪 <b>بازار شهر</b>", "", "منابع موجود برای خرید:"]
    keyboard = []
    if not offers:
        lines += ["", "بازار فعلاً خالی است."]
    else:
        for offer in offers:
            resource_name = MARKET_RESOURCES.get(offer["resource_type"], "منبع")
            lines.append(
                f"\n📦 {resource_name} × {offer['amount']:,}\n"
                f"💰 قیمت: {offer['price']:,} سکه\n"
                f"👤 فروشنده: {safe_text(offer['first_name'])}"
            )
            keyboard.append([
                InlineKeyboardButton(
                    text=f"🛒 خرید پیشنهاد {offer['id']}",
                    callback_data=f"market_buy:{offer['id']}"
                )
            ])

    lines += [
        "",
        "━━━━━━━━━━━━",
        "برای فروش منابع، دکمه زیر را بزنید."
    ]
    keyboard.append([
        InlineKeyboardButton(text="📤 فروش منابع", callback_data="market_sell")
    ])
    keyboard.append([
        InlineKeyboardButton(text="🔄 به‌روزرسانی بازار", callback_data="market")
    ])
    keyboard.append([
        InlineKeyboardButton(text="🔙 بازگشت", callback_data="back_main")
    ])

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


market_state = {}


@dp.callback_query(F.data == "market_sell")
async def market_sell_callback(callback: CallbackQuery):
    await callback.answer()
    market_state[(callback.message.chat.id, callback.from_user.id)] = {"step": "resource"}
    keyboard = [
        [InlineKeyboardButton(text="🍞 غذا", callback_data="market_res:food")],
        [InlineKeyboardButton(text="🧱 مصالح", callback_data="market_res:materials")],
        [InlineKeyboardButton(text="⚡ انرژی", callback_data="market_res:energy")],
        [InlineKeyboardButton(text="💧 آب", callback_data="market_res:water")],
        [InlineKeyboardButton(text="🧰 تجهیزات", callback_data="market_res:equipment")],
        [InlineKeyboardButton(text="🔙 بازگشت به بازار", callback_data="market")],
    ]
    await callback.message.edit_text(
        "📤 <b>فروش منابع</b>\n\nکدام منبع را می‌خواهی بفروشی؟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )


@dp.callback_query(F.data.startswith("market_res:"))
async def market_resource_callback(callback: CallbackQuery):
    await callback.answer()
    resource = callback.data.split(":", 1)[1]
    key = (callback.message.chat.id, callback.from_user.id)
    market_state[key] = {"step": "amount", "resource": resource}
    await callback.message.edit_text(
        f"📤 <b>فروش {MARKET_RESOURCES[resource]}</b>\n\n"
        "مقدار موردنظر را به صورت عدد بفرست.\n"
        "مثلاً: <code>100</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت به بازار", callback_data="market")]
        ])
    )


@dp.callback_query(F.data.startswith("market_buy:"))
async def market_buy_callback(callback: CallbackQuery):
    await callback.answer()
    offer_id = callback.data.split(":", 1)[1]
    try:
        offer_id = int(offer_id)
    except ValueError:
        await callback.message.answer("❌ پیشنهاد نامعتبر است.")
        return

    user_id = await callback.from_user.id if False else callback.from_user.id
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            offer = await conn.fetchrow(
                "SELECT * FROM market_offers WHERE id=$1 FOR UPDATE", offer_id
            )
            if not offer or offer["status"] != "active":
                await callback.message.answer("❌ این پیشنهاد دیگر فعال نیست.")
                return
            if offer["seller_id"] == user_id:
                await callback.message.answer("❌ نمی‌توانی پیشنهاد خودت را بخری.")
                return
            ids = sorted([user_id, offer["seller_id"]])
            rows = await conn.fetch(
                "SELECT * FROM resources WHERE user_id=ANY($1::bigint[]) ORDER BY user_id FOR UPDATE", ids
            )
            rm = {r["user_id"]: r for r in rows}
            buyer, seller = rm.get(user_id), rm.get(offer["seller_id"])
            if not buyer or not seller:
                await callback.message.answer("❌ اطلاعات منابع پیدا نشد.")
                return
            if buyer["coins"] < offer["price"]:
                await callback.message.answer("❌ سکه کافی نداری.")
                return
            resource = offer["resource_type"]
            await conn.execute("UPDATE resources SET coins=coins-$1 WHERE user_id=$2", offer["price"], user_id)
            await conn.execute("UPDATE resources SET coins=coins+$1 WHERE user_id=$2", offer["price"], offer["seller_id"])
            await conn.execute(f"UPDATE resources SET {resource}={resource}+$1 WHERE user_id=$2", offer["amount"], user_id)
            await conn.execute("UPDATE market_offers SET status='sold' WHERE id=$1", offer_id)

    await add_xp(user_id, 15)
    await callback.message.answer(
        "🛒 <b>خرید با موفقیت انجام شد!</b>\n\n"
        f"📦 {MARKET_RESOURCES[offer['resource_type']]}\n"
        f"مقدار: {offer['amount']:,}\n"
        f"💰 پرداخت: {offer['price']:,} سکه\n\n⭐ +15 XP"
    )
    await market_callback(callback)


@dp.message(lambda m: m.chat.type == "private" and bool(m.text) and (m.chat.id, m.from_user.id) in market_state)
async def market_text_input(message: Message):
    key = (message.chat.id, message.from_user.id)
    state = market_state.get(key)
    if not state or state.get("step") != "amount":
        return
    try:
        amount = int(message.text.strip())
    except ValueError:
        await message.answer("❌ مقدار باید عدد باشد؛ مثلاً 100")
        return
    if amount <= 0:
        await message.answer("❌ مقدار باید بیشتر از صفر باشد.")
        return
    resource = state["resource"]
    async with db_pool.acquire() as conn:
        balance = await conn.fetchval(f"SELECT {resource} FROM resources WHERE user_id=$1", message.from_user.id)
    if balance is None:
        await message.answer("❌ منابع پیدا نشد.")
        market_state.pop(key, None)
        return
    if balance < amount:
        await message.answer(f"❌ موجودی کافی نیست. موجودی فعلی: <b>{balance:,}</b>")
        return
    state["amount"] = amount
    state["step"] = "price"
    await message.answer(
        f"💰 قیمت کل {amount:,} واحد {MARKET_RESOURCES[resource]} را به سکه وارد کن.\n"
        "مثلاً: <code>500</code>",
        reply_markup=ForceReply(selective=True)
    )


@dp.message(lambda m: m.chat.type == "private" and bool(m.text) and (m.chat.id, m.from_user.id) in market_state)
async def market_price_input(message: Message):
    key = (message.chat.id, message.from_user.id)
    state = market_state.get(key)
    if not state or state.get("step") != "price":
        return
    try:
        price = int(message.text.strip())
    except ValueError:
        await message.answer("❌ قیمت باید عدد باشد؛ مثلاً 500")
        return
    if price <= 0:
        await message.answer("❌ قیمت باید بیشتر از صفر باشد.")
        return
    resource, amount = state["resource"], state["amount"]
    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            resources = await conn.fetchrow("SELECT * FROM resources WHERE user_id=$1 FOR UPDATE", user_id)
            if not resources or resources[resource] < amount:
                await message.answer("❌ موجودی منابع برای این فروش کافی نیست.")
                market_state.pop(key, None)
                return
            await conn.execute(f"UPDATE resources SET {resource}={resource}-$1 WHERE user_id=$2", amount, user_id)
            offer = await conn.fetchrow(
                """INSERT INTO market_offers(seller_id, resource_type, amount, price) VALUES($1,$2,$3,$4) RETURNING id""",
                user_id, resource, amount, price
            )
    market_state.pop(key, None)
    await message.answer(
        "📤 <b>عرضه در بازار انجام شد!</b>\n\n"
        f"🆔 شناسه پیشنهاد: <code>{offer['id']}</code>\n"
        f"📦 {MARKET_RESOURCES[resource]}: {amount:,}\n"
        f"💰 قیمت کل: {price:,} سکه",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏪 مشاهده بازار", callback_data="market")]
        ])
    )


@dp.message(Command("sell"))
async def sell_command(message: Message):
    user_id = await ensure_player(message)

    parts = message.text.split()

    if len(parts) != 4:
        await message.answer(
            "❌ مثال:\n"
            "<code>/sell food 100 50</code>"
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
        await message.answer(
            "❌ مقدار و قیمت باید عدد باشند."
        )
        return

    if amount <= 0 or price <= 0:
        await message.answer(
            "❌ مقدار و قیمت باید بیشتر از صفر باشند."
        )
        return

    if amount > 100000 or price > 1000000:
        await message.answer(
            "❌ مقدار معامله بیش از حد مجاز است."
        )
        return

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            resources = await conn.fetchrow(
                """
                SELECT *
                FROM resources
                WHERE user_id=$1
                FOR UPDATE
                """,
                user_id,
            )

            if not resources:
                await message.answer(
                    "❌ منابع پیدا نشد."
                )
                return

            if resources[resource_type] < amount:
                await message.answer(
                    "❌ منابع کافی برای فروش نداری."
                )
                return

            await conn.execute(
                f"""
                UPDATE resources
                SET {resource_type}=
                    {resource_type}-$1
                WHERE user_id=$2
                """,
                amount,
                user_id,
            )

            offer = await conn.fetchrow(
                """
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
        "📤 <b>عرضه در بازار انجام شد!</b>\n\n"
        f"🆔 شناسه پیشنهاد: "
        f"<code>{offer['id']}</code>\n\n"
        f"{MARKET_RESOURCES[resource_type]}: "
        f"{amount:,}\n"
        f"💰 قیمت کل: {price:,} سکه"
    )


@dp.message(Command("buy"))
async def buy_command(message: Message):
    user_id = await ensure_player(message)

    parts = message.text.split()

    if len(parts) != 2:
        await message.answer(
            "❌ مثال:\n"
            "<code>/buy 15</code>"
        )
        return

    try:
        offer_id = int(parts[1])
    except ValueError:
        await message.answer(
            "❌ شناسه پیشنهاد اشتباه است."
        )
        return

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            offer = await conn.fetchrow(
                """
                SELECT *
                FROM market_offers
                WHERE id=$1
                FOR UPDATE
                """,
                offer_id,
            )

            if (
                not offer
                or offer["status"] != "active"
            ):
                await message.answer(
                    "❌ این پیشنهاد دیگر فعال نیست."
                )
                return

            if offer["seller_id"] == user_id:
                await message.answer(
                    "❌ نمی‌توانی پیشنهاد خودت را بخری."
                )
                return

            ids = sorted(
                [
                    user_id,
                    offer["seller_id"],
                ]
            )

            resource_rows = await conn.fetch(
                """
                SELECT *
                FROM resources
                WHERE user_id=ANY($1::bigint[])
                ORDER BY user_id
                FOR UPDATE
                """,
                ids,
            )

            resource_map = {
                row["user_id"]: row
                for row in resource_rows
            }

            buyer = resource_map.get(
                user_id
            )

            seller = resource_map.get(
                offer["seller_id"]
            )

            if not buyer or not seller:
                await message.answer(
                    "❌ اطلاعات منابع پیدا نشد."
                )
                return

            if buyer["coins"] < offer["price"]:
                await message.answer(
                    "❌ سکه کافی نداری."
                )
                return

            resource_type = offer[
                "resource_type"
            ]

            await conn.execute(
                """
                UPDATE resources
                SET coins=coins-$1
                WHERE user_id=$2
                """,
                offer["price"],
                user_id,
            )

            await conn.execute(
                """
                UPDATE resources
                SET coins=coins+$1
                WHERE user_id=$2
                """,
                offer["price"],
                offer["seller_id"],
            )

            await conn.execute(
                f"""
                UPDATE resources
                SET {resource_type}=
                    {resource_type}+$1
                WHERE user_id=$2
                """,
                offer["amount"],
                user_id,
            )

            await conn.execute(
                """
                UPDATE market_offers
                SET status='sold'
                WHERE id=$1
                """,
                offer_id,
            )

    await add_xp(
        user_id,
        15,
    )

    await message.answer(
        "🛒 <b>خرید موفق بود!</b>\n\n"
        f"📦 {MARKET_RESOURCES[offer['resource_type']]}\n"
        f"مقدار: {offer['amount']:,}\n\n"
        f"💰 پرداخت: {offer['price']:,} سکه\n\n"
        "⭐ +15 XP"
    )


# =========================================================
# تعامل با گروه واقعی تلگرام
# =========================================================

async def is_bot_admin(chat_id):
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
        return member.status in {"administrator", "creator"}
    except Exception:
        return False


async def register_telegram_group(chat_id, title, admin=False):
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO telegram_groups(chat_id, title, bot_is_admin, updated_at)
            VALUES($1,$2,$3,NOW())
            ON CONFLICT(chat_id) DO UPDATE SET
                title=EXCLUDED.title,
                bot_is_admin=EXCLUDED.bot_is_admin,
                updated_at=NOW()
            """,
            chat_id, title or "گروه تلگرام", admin,
        )


async def register_group_user(chat_id, user):
    if not await is_bot_admin(chat_id):
        return False
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO telegram_group_mayors(chat_id,user_id,username,first_name,last_seen)
            VALUES($1,$2,$3,$4,NOW())
            ON CONFLICT(chat_id,user_id) DO UPDATE SET
                username=EXCLUDED.username,
                first_name=EXCLUDED.first_name,
                last_seen=NOW()
            """,
            chat_id, user.id, user.username, user.first_name,
        )
    return True


async def register_group_mayor(message):
    if message.chat.type not in {"group", "supergroup"}:
        return False
    if not await is_bot_admin(message.chat.id):
        return False
    await register_telegram_group(message.chat.id, message.chat.title, True)
    await ensure_player(message)
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO telegram_group_mayors(chat_id,user_id,username,first_name,last_seen)
            VALUES($1,$2,$3,$4,NOW())
            ON CONFLICT(chat_id,user_id) DO UPDATE SET
                username=EXCLUDED.username,
                first_name=EXCLUDED.first_name,
                last_seen=NOW()
            """,
            message.chat.id,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
        )
    return True


def group_assets_text(row):
    return (
        "💼 <b>پنل دارایی شهردار</b>\n\n"
        f"💰 سکه: <b>{row['coins']:,}</b>\n"
        f"🧱 مصالح: <b>{row['materials']:,}</b>\n"
        f"🍞 غذا: <b>{row['food']:,}</b>\n"
        f"⚡ انرژی: <b>{row['energy']:,}</b>\n"
        f"💧 آب: <b>{row['water']:,}</b>\n"
        f"🧰 تجهیزات: <b>{row['equipment']:,}</b>\n\n"
        "از دکمه زیر می‌توانی دارایی را به شهردار دیگری در همین گروه منتقل کنی."
    )


def group_assets_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 انتقال دارایی", callback_data="telegram_group:transfer")],
    ])


@dp.my_chat_member()
async def bot_group_status(update: ChatMemberUpdated):
    if update.chat.type not in {"group", "supergroup"}:
        return
    status = update.new_chat_member.status
    admin = status in {"administrator", "creator"}
    await register_telegram_group(update.chat.id, update.chat.title, admin)


@dp.message(lambda m: m.chat.type in {"group", "supergroup"} and (m.text or "").strip() == "شهر من")
async def group_city_panel(message: Message):
    if not await is_bot_admin(message.chat.id):
        await message.reply("⚠️ برای استفاده از امکانات شهر من، ابتدا ربات را مدیر گروه کنید.")
        return
    await register_group_mayor(message)
    user_id = message.from_user.id
    await process_player_tick(user_id)
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM resources WHERE user_id=$1", user_id)
    if not row:
        await message.reply("❌ منابع شهر پیدا نشد.")
        return
    await message.reply(group_assets_text(row), reply_markup=group_assets_keyboard())


async def get_resource_balance(user_id, resource_type):
    async with db_pool.acquire() as conn:
        return await conn.fetchval(f"SELECT {resource_type} FROM resources WHERE user_id=$1", user_id) or 0


@dp.callback_query(F.data == "telegram_group:transfer")
async def telegram_group_transfer_start(callback: CallbackQuery):
    if callback.message.chat.type not in {"group", "supergroup"}:
        await callback.answer("فقط داخل گروه فعال است.", show_alert=True)
        return
    if not await is_bot_admin(callback.message.chat.id):
        await callback.answer("ربات باید مدیر گروه باشد.", show_alert=True)
        return
    await register_group_user(callback.message.chat.id, callback.from_user)
    uid = callback.from_user.id
    balances = {}
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT coins,food,materials,energy,water,equipment FROM resources WHERE user_id=$1", uid)
    if row:
        balances = dict(row)
    key = (callback.message.chat.id, uid)
    group_transfer_state[key] = {"step": "resource", "prompt_id": None, "balances": balances}
    msg = await callback.message.reply(
        "💸 <b>انتقال دارایی</b>\n\n"
        "چه منبعی را می‌خواهی انتقال بدهی؟\n"
        "روی همین پیام ریپلای کن و یکی از این موارد را بنویس: سکه، مصالح، غذا، انرژی، آب یا تجهیزات.",
        reply_markup=ForceReply(selective=True),
    )
    group_transfer_state[key]["prompt_id"] = msg.message_id
    await callback.answer()


async def process_telegram_group_reply(message: Message):
    if message.chat.type not in {"group", "supergroup"} or not message.reply_to_message or not message.text:
        return False
    key = (message.chat.id, message.from_user.id)
    state = group_transfer_state.get(key)
    if not state or state.get("prompt_id") != message.reply_to_message.message_id:
        return False

    if state["step"] == "resource":
        resource_type = TRANSFER_ALIASES.get(message.text.strip().lower())
        if not resource_type:
            await message.reply("❌ منبع شناخته نشد. بنویس: سکه، غذا، آجر، مصالح، انرژی، آب یا تجهیزات.")
            return True
        balance = state["balances"].get(resource_type, 0)
        state["resource"] = resource_type
        state["step"] = "amount"
        msg = await message.reply(
            f"📦 {TRANSFER_RESOURCES[resource_type]}\n\n"
            f"موجودی فعلی: <b>{balance:,}</b>\n\n"
            "چه مقداری می‌خواهی انتقال بدهی؟ هر عددی که در محدوده موجودی داری بنویس.",
            reply_markup=ForceReply(selective=True),
        )
        state["prompt_id"] = msg.message_id
        return True

    if state["step"] == "amount":
        try:
            amount = int(message.text.strip().replace(",", ""))
        except ValueError:
            await message.reply("❌ مقدار باید یک عدد باشد؛ مثلاً 100")
            return True
        if amount <= 0:
            await message.reply("❌ مقدار باید بیشتر از صفر باشد.")
            return True
        resource_type = state["resource"]
        balance = await get_resource_balance(message.from_user.id, resource_type)
        if amount > balance:
            await message.reply(f"❌ موجودی کافی نیست. موجودی فعلی: <b>{balance:,}</b>")
            return True
        state["amount"] = amount
        state["step"] = "recipient_id"
        msg = await message.reply(
            f"📤 {TRANSFER_RESOURCES[resource_type]} × <b>{amount:,}</b>\n\n"
            "نام کاربری شهردار مقصد را بفرست.\n"
            "روی همین پیام ریپلای کن و با @ بنویس؛ مثلاً @username",
            reply_markup=ForceReply(selective=True),
        )
        state["prompt_id"] = msg.message_id
        return True
    return False


@dp.message(lambda m: m.chat.type in {"group", "supergroup"} and bool(m.reply_to_message) and bool(m.text))
async def telegram_group_transfer_reply_router(message: Message):
    key = (message.chat.id, message.from_user.id)
    state = group_transfer_state.get(key)
    if not state or state.get("prompt_id") != message.reply_to_message.message_id:
        return

    if state["step"] in {"resource", "amount"}:
        await process_telegram_group_reply(message)
        return

    if state["step"] != "recipient_id":
        return

    target = message.text.strip()
    if not target.startswith("@"):
        await message.reply("❌ نام کاربری مقصد باید با @ شروع شود؛ مثلاً @username", reply_markup=ForceReply(selective=True))
        return

    username = target[1:].strip().split()[0] if target[1:].strip() else ""
    if not username:
        await message.reply("❌ نام کاربری معتبر نیست. مثلاً @username را بفرست.", reply_markup=ForceReply(selective=True))
        return

    sender_username = message.from_user.username or ""
    if sender_username.lower() == username.lower():
        await message.reply("❌ نمی‌توانی دارایی را به شهر خودت انتقال بدهی. @username یک شهردار دیگر را بفرست.", reply_markup=ForceReply(selective=True))
        return

    async with db_pool.acquire() as conn:
        recipient = await conn.fetchrow(
            """
            SELECT p.user_id, p.first_name, COALESCE(NULLIF(gm.username,''), p.username) AS username, c.city_name
            FROM players p
            INNER JOIN cities c ON c.user_id=p.user_id
            INNER JOIN telegram_group_mayors gm
                ON gm.user_id=p.user_id AND gm.chat_id=$1
            WHERE LOWER(COALESCE(NULLIF(gm.username,''), p.username,''))=LOWER($2)
            LIMIT 1
            """,
            message.chat.id, username,
        )

    if not recipient:
        await message.reply("❌ این شخص شهر ندارد.", reply_markup=ForceReply(selective=True))
        return

    resource_type = state["resource"]
    amount = state["amount"]
    delay = random.randint(10, 60)
    deliver_at = now_utc() + timedelta(minutes=delay)

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            src = await conn.fetchrow("SELECT * FROM resources WHERE user_id=$1 FOR UPDATE", message.from_user.id)
            if not src or src[resource_type] < amount:
                await message.reply(f"❌ موجودی تو تغییر کرده و کافی نیست. موجودی فعلی: <b>{(src[resource_type] if src else 0):,}</b>")
                group_transfer_state.pop(key, None)
                return
            await conn.execute(
                f"UPDATE resources SET {resource_type}={resource_type}-$1 WHERE user_id=$2",
                amount, message.from_user.id,
            )
            await conn.execute(
                """
                INSERT INTO group_transfers(chat_id,sender_id,recipient_id,resource_type,amount,deliver_at)
                VALUES($1,$2,$3,$4,$5,$6)
                """,
                message.chat.id, message.from_user.id, recipient["user_id"], resource_type, amount, deliver_at,
            )

    group_transfer_state.pop(key, None)
    recipient_name = recipient["first_name"] or (f"@{recipient['username']}" if recipient["username"] else "شهردار مقصد")
    await message.reply(
        f"🚚 <b>کامیون بارگیری شد!</b>\n\n"
        f"{TRANSFER_RESOURCES[resource_type]}: <b>{amount:,}</b>\n"
        f"🏙️ در حال انتقال به شهر <b>{safe_text(recipient_name)}</b> هستیم.\n"
        f"⏳ زمان رسیدن: <b>{delay} دقیقه</b>"
    )


@dp.callback_query(F.data == "telegram_group:cancel")
async def telegram_group_cancel(callback: CallbackQuery):
    group_transfer_state.pop((callback.message.chat.id, callback.from_user.id), None)
    await callback.answer("انتقال لغو شد.")
    await callback.message.edit_text("❌ انتقال دارایی لغو شد.")


async def process_group_transfers():
    completed = []
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                "SELECT * FROM group_transfers WHERE status='pending' AND deliver_at<=NOW() ORDER BY id FOR UPDATE SKIP LOCKED"
            )
            for row in rows:
                recipient_exists = await conn.fetchval("SELECT 1 FROM resources WHERE user_id=$1", row["recipient_id"])
                if recipient_exists:
                    rt = row["resource_type"]
                    await conn.execute(f"UPDATE resources SET {rt}={rt}+$1 WHERE user_id=$2", row["amount"], row["recipient_id"])
                await conn.execute("UPDATE group_transfers SET status='completed' WHERE id=$1", row["id"])
                completed.append(row)
    for row in completed:
        label = TRANSFER_RESOURCES.get(row["resource_type"], "دارایی")
        try:
            await bot.send_message(row["recipient_id"], f"📦 <b>انتقال دارایی تکمیل شد!</b>\n\n{label}: {row['amount']:,}\nدارایی به شهر شما رسید.")
        except Exception:
            pass
        try:
            await bot.send_message(row["sender_id"], f"✅ <b>انتقال انجام شد!</b>\n\n{label}: {row['amount']:,}\nدارایی به شهر مقصد رسید.")
        except Exception:
            pass


# =========================================================
# WEEKLY COMPETITION
# =========================================================

def iran_now():
    return datetime.now(IRAN_TZ)


def week_key(for_date=None):
    day = for_date or iran_now().date()
    year, week, _ = day.isocalendar()
    return f"{year}-W{week}"


def previous_week_key():
    return week_key(iran_now().date() - timedelta(days=7))


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
        await conn.execute(
            "INSERT INTO weekly_seasons(week_key) VALUES($1) ON CONFLICT DO NOTHING", key
        )
        await conn.execute(
            """
            INSERT INTO weekly_scores(user_id, week_key, score)
            VALUES($1,$2,$3)
            ON CONFLICT(user_id, week_key)
            DO UPDATE SET score=GREATEST(weekly_scores.score, EXCLUDED.score)
            """,
            user_id, key, score,
        )


async def process_weekly_payout():
    # پرداخت در پایان جمعه به وقت ایران؛ در صورت خاموش بودن بات، شنبه/یکشنبه جبران می‌شود.
    local = iran_now()
    if local.weekday() == 4 and local.hour < 23:
        return
    if local.weekday() < 4:
        return

    target_key = week_key() if local.weekday() == 4 else previous_week_key()

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            # جلوگیری از پرداخت دوباره در صورت اجرای هم‌زمان دو نمونه بات
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext($1))",
                "weekly_payout:" + target_key,
            )
            already = await conn.fetchval(
                "SELECT 1 FROM weekly_payouts WHERE week_key=$1", target_key
            )
            if already:
                return

            rows = await conn.fetch(
                """
                SELECT ws.user_id, ws.score, p.first_name, c.city_name
                FROM weekly_scores ws
                JOIN players p ON p.user_id=ws.user_id
                JOIN cities c ON c.user_id=ws.user_id
                WHERE ws.week_key=$1
                ORDER BY ws.score DESC, ws.user_id ASC
                LIMIT 3
                """, target_key
            )

            ids = [r["user_id"] for r in rows]
            rewards = [WEEKLY_REWARDS[1], WEEKLY_REWARDS[2], WEEKLY_REWARDS[3]]
            for i, row in enumerate(rows):
                await conn.execute(
                    "UPDATE resources SET coins=coins+$1 WHERE user_id=$2",
                    rewards[i], row["user_id"]
                )

            await conn.execute(
                """
                INSERT INTO weekly_payouts(
                    week_key, paid_at, first_user_id, second_user_id, third_user_id,
                    first_reward, second_reward, third_reward
                ) VALUES($1,NOW(),$2,$3,$4,$5,$6,$7)
                """,
                target_key,
                ids[0] if len(ids)>0 else None,
                ids[1] if len(ids)>1 else None,
                ids[2] if len(ids)>2 else None,
                rewards[0] if len(rows)>0 else 0,
                rewards[1] if len(rows)>1 else 0,
                rewards[2] if len(rows)>2 else 0,
            )

    for i, row in enumerate(rows, 1):
        try:
            await bot.send_message(
                row["user_id"],
                "🏆 <b>نتیجه رقابت هفتگی</b>\n\n"
                f"{['🥇','🥈','🥉'][i-1]} رتبه شما: {i}\n"
                f"👤 برنده: {safe_text(row['first_name'])}\n"
                f"🏙️ شهر: {safe_text(row['city_name'])}\n"
                f"💰 جایزه: {WEEKLY_REWARDS[i]:,} سکه\n\n"
                "🎁 جایزه به‌صورت خودکار به موجودی شهر اضافه شد؛ دریافت دستی ندارد.",
            )
        except Exception:
            logging.exception("Could not notify weekly winner %s", row["user_id"])


@dp.callback_query(F.data == "ranking")
async def ranking_callback(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    await ensure_callback_player(user_id)
    await update_weekly_score(user_id)
    key = week_key()

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT ws.user_id, ws.score, p.first_name, c.city_name
            FROM weekly_scores ws
            JOIN players p ON p.user_id=ws.user_id
            JOIN cities c ON c.user_id=ws.user_id
            WHERE ws.week_key=$1
            ORDER BY ws.score DESC, ws.user_id ASC
            LIMIT 10
            """, key
        )
        my_rank = await conn.fetchval(
            """
            SELECT rank FROM (
                SELECT user_id, ROW_NUMBER() OVER(ORDER BY score DESC, user_id ASC) AS rank
                FROM weekly_scores WHERE week_key=$1
            ) r WHERE user_id=$2
            """, key, user_id
        )

    lines=["🏆 <b>رقابت هفتگی</b>", f"📅 هفته: {key}", ""]
    medals=["🥇","🥈","🥉"]
    for i in range(3):
        if i < len(rows):
            r=rows[i]
            lines.append(f"{medals[i]} نفر {i+1}: <b>{safe_text(r['first_name'])}</b> — {safe_text(r['city_name'])} — {r['score']:,} امتیاز")
        else:
            lines.append(f"{medals[i]} نفر {i+1}: هنوز برنده‌ای ثبت نشده")
    if len(rows)>3:
        lines.append("")
        for i,r in enumerate(rows[3:],4):
            lines.append(f"{i}. {safe_text(r['first_name'])} — {r['score']:,} امتیاز")
    lines += [
        "", f"📍 رتبه فعلی تو: {my_rank or '-'}", "",
        "🎁 <b>جوایز پایان هفته</b>",
        "🥇 نفر اول: ۳۰۰۰ سکه", "🥈 نفر دوم: ۱۸۰۰ سکه", "🥉 نفر سوم: ۱۰۰۰ سکه",
        "", "⏰ پرداخت خودکار: جمعه ساعت ۲۳:۰۰ به وقت ایران",
        "💰 جایزه مستقیم به موجودی اضافه می‌شود و دریافت دستی ندارد.",
    ]
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 بروزرسانی رتبه‌بندی", callback_data="ranking")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu")],
        ]),
    )


@dp.callback_query(F.data == "claim_weekly")
async def claim_weekly(callback: CallbackQuery):
    await callback.answer("🎁 جوایز پایان هفته خودکار پرداخت می‌شوند و دریافت دستی ندارند.", show_alert=True)


# =========================================================
# NEWS
# =========================================================

@dp.callback_query(F.data == "news")
async def news_callback(
    callback: CallbackQuery
):
    await callback.answer()

    user_id = callback.from_user.id

    await ensure_callback_player(user_id)

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT text, created_at
            FROM news
            WHERE user_id=$1
            ORDER BY created_at DESC
            LIMIT 10
            """,
            user_id,
        )

    if not rows:
        text = (
            "📰 <b>روزنامه شهر</b>\n\n"
            "هنوز خبر خاصی در شهر ثبت نشده.\n\n"
            "شهر تو تازه شروع به رشد کرده! 🌱"
        )

    else:
        lines = [
            "📰 <b>روزنامه شهر</b>\n"
        ]

        for row in rows:
            lines.append(
                f"• {safe_text(row['text'])}"
            )

        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=back_keyboard(),
    )


# =========================================================
# EXPANSION
# =========================================================

@dp.callback_query(F.data == "expansion")
async def expansion_callback(
    callback: CallbackQuery
):
    await callback.answer()

    user_id = callback.from_user.id

    await ensure_callback_player(user_id)

    city = await get_city(user_id)

    if not city:
        await callback.message.edit_text(
            "❌ اطلاعات شهر پیدا نشد.",
            reply_markup=back_keyboard(),
        )
        return

    needed_level = (
        10 + city["villages"] * 5
    )

    if city["city_level"] < needed_level:
        text = (
            "🗺️ <b>توسعه شهر</b>\n\n"
            f"برای جذب روستای بعدی باید "
            f"به سطح شهر {needed_level} برسی.\n\n"
            f"⭐ سطح فعلی: "
            f"{city['city_level']}\n"
            f"🏘️ روستاهای جذب‌شده: "
            f"{city['villages']}\n\n"
            "شهر را توسعه بده تا بتوانی "
            "محدوده اطراف را به شهر اضافه کنی."
        )

        await callback.message.edit_text(
            text,
            reply_markup=back_keyboard(),
        )
        return

    cost = (
        2500
        + city["villages"] * 1500
    )

    text = (
        "🗺️ <b>توسعه شهر</b>\n\n"
        "یک روستای جدید آماده پیوستن "
        "به شهر است! 🏘️\n\n"
        f"🏙️ سطح شهر: "
        f"{city['city_level']}\n"
        f"🏘️ روستاهای فعلی: "
        f"{city['villages']}\n\n"
        f"💰 هزینه توسعه: "
        f"{cost:,} سکه\n\n"
        "با توسعه:\n\n"
        "👥 ظرفیت جمعیت افزایش می‌یابد\n"
        "🏠 ظرفیت مسکن افزایش می‌یابد\n"
        "🗺️ زمین شهر بیشتر می‌شود"
    )

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


@dp.callback_query(
    F.data == "expand_village"
)
async def expand_village(
    callback: CallbackQuery
):
    user_id = callback.from_user.id

    await ensure_callback_player(user_id)

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock($1)",
                int(user_id),
            )

            city = await conn.fetchrow(
                """
                SELECT *
                FROM cities
                WHERE user_id=$1
                FOR UPDATE
                """,
                user_id,
            )

            if not city:
                await callback.answer(
                    "اطلاعات شهر پیدا نشد.",
                    show_alert=True,
                )
                return

            needed_level = (
                10 + city["villages"] * 5
            )

            if city["city_level"] < needed_level:
                await callback.answer(
                    "❌ سطح شهر کافی نیست.",
                    show_alert=True,
                )
                return

            cost = (
                2500
                + city["villages"] * 1500
            )

            resources = await conn.fetchrow(
                """
                SELECT coins
                FROM resources
                WHERE user_id=$1
                FOR UPDATE
                """,
                user_id,
            )

            if not resources:
                await callback.answer(
                    "منابع شهر پیدا نشد.",
                    show_alert=True,
                )
                return

            if resources["coins"] < cost:
                await callback.answer(
                    "❌ سکه کافی نداری.",
                    show_alert=True,
                )
                return

            await conn.execute(
                """
                UPDATE resources
                SET coins=coins-$1
                WHERE user_id=$2
                """,
                cost,
                user_id,
            )

            await conn.execute(
                """
                UPDATE cities
                SET
                    villages=villages+1,
                    land=land+1,
                    housing_capacity=
                        housing_capacity+200,
                    population=population+50
                WHERE user_id=$1
                """,
                user_id,
            )

            await conn.execute(
                """
                INSERT INTO news(
                    user_id,
                    text
                )
                VALUES($1,$2)
                """,
                user_id,
                "🏘️ یک روستای جدید به "
                "محدوده شهر اضافه شد!",
            )

    await add_xp(
        user_id,
        250,
    )

    await recalculate_city(
        user_id
    )

    await callback.answer(
        "🏘️ توسعه با موفقیت انجام شد!"
    )

    await callback.message.edit_text(
        "🎉 <b>توسعه موفق بود!</b>\n\n"
        "🏘️ یک روستا به شهر تو پیوست.\n"
        "🗺️ محدوده شهر بزرگ‌تر شد.\n"
        "🏠 ظرفیت مسکن افزایش یافت.\n"
        "👥 جمعیت افزایش یافت.\n\n"
        "شهردار، شهر تو در حال تبدیل شدن "
        "به یک منطقه بزرگ است! 🏙️",
        reply_markup=main_keyboard(),
    )


# =========================================================
# GAME TICK
# =========================================================

async def process_player_tick(user_id):
    """
    هر بازیکن حداکثر یک بار در 25 دقیقه پردازش می‌شود.
    """

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock($1)",
                int(user_id),
            )

            city = await conn.fetchrow(
                """
                SELECT *
                FROM cities
                WHERE user_id=$1
                FOR UPDATE
                """,
                user_id,
            )

            if not city:
                return

            last_tick = city["last_tick"]

            if last_tick is None:
                last_tick = now_utc()

            current = now_utc()

            elapsed = current - last_tick

            if elapsed < timedelta(minutes=25):
                return

            # -------------------------------------------------
            # Calculate current services
            # -------------------------------------------------

            rows = await conn.fetch(
                """
                SELECT building_type, level
                FROM buildings
                WHERE user_id=$1
                """,
                user_id,
            )

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
                building = BUILDINGS.get(
                    row["building_type"]
                )

                if not building:
                    continue

                level = max(
                    0,
                    row["level"],
                )

                for stat, effect in building[
                    "base_effect"
                ].items():
                    value = effect * level

                    if stat in stats:
                        stats[stat] += value

                    elif stat == "economy":
                        economy_bonus += value

                    elif stat == "jobs":
                        job_bonus += value

                    elif stat == "pollution":
                        pollution += value

                housing_bonus += (
                    building.get("housing", 0)
                    * level
                )

                if row["building_type"] == "school":
                    housing_bonus += level * 10

                elif row["building_type"] == "university":
                    housing_bonus += level * 20

                elif row["building_type"] == "roads":
                    housing_bonus += level * 20

            pollution_net = max(
                0,
                pollution
                - stats["pollution_control"],
            )

            housing_capacity = (
                150
                + city["land"] * 100
                + housing_bonus
            )

            jobs = max(
                20,
                START_JOBS
                + job_bonus
                + city["population"] // 3,
            )

            population = city[
                "population"
            ]

            # -------------------------------------------------
            # Resource consumption
            # -------------------------------------------------

            food_need = max(
                1,
                population // 50,
            )

            water_need = max(
                1,
                population // 45,
            )

            energy_need = max(
                1,
                population // 60,
            )

            resources = await conn.fetchrow(
                """
                SELECT *
                FROM resources
                WHERE user_id=$1
                FOR UPDATE
                """,
                user_id,
            )

            if not resources:
                return

            food_available = (
                resources["food"]
                >= food_need
            )

            water_available = (
                resources["water"]
                >= water_need
            )

            energy_available = (
                resources["energy"]
                >= energy_need
            )

            await conn.execute(
                """
                UPDATE resources
                SET
                    food=GREATEST(
                        0,
                        food-$1
                    ),
                    water=GREATEST(
                        0,
                        water-$2
                    ),
                    energy=GREATEST(
                        0,
                        energy-$3
                    )
                WHERE user_id=$4
                """,
                food_need,
                water_need,
                energy_need,
                user_id,
            )

            # -------------------------------------------------
            # Satisfaction
            # -------------------------------------------------

            satisfaction_change = 0

            if not food_available:
                satisfaction_change -= 6

            if not water_available:
                satisfaction_change -= 7

            if not energy_available:
                satisfaction_change -= 6

            if population > housing_capacity:
                shortage = (
                    population
                    - housing_capacity
                )

                satisfaction_change -= min(
                    8,
                    max(
                        1,
                        shortage // 30,
                    ),
                )

            if population > jobs:
                unemployment = (
                    population - jobs
                )

                satisfaction_change -= min(
                    8,
                    max(
                        1,
                        unemployment // 40,
                    ),
                )

            if city["tax_rate"] > 15:
                satisfaction_change -= min(
                    5,
                    (
                        city["tax_rate"]
                        - 15
                    ) // 2,
                )

            if stats["security"] >= 60:
                satisfaction_change += 1

            if stats["health"] >= 60:
                satisfaction_change += 1

            if stats["recreation"] >= 60:
                satisfaction_change += 1

            if stats["education"] >= 60:
                satisfaction_change += 1

            if stats["infrastructure"] >= 60:
                satisfaction_change += 1

            if stats["water"] < 20:
                satisfaction_change -= 2

            if stats["power"] < 20:
                satisfaction_change -= 2

            if pollution_net >= 20:
                satisfaction_change -= 2

            # -------------------------------------------------
            # Population growth / migration
            # -------------------------------------------------

            satisfaction = city[
                "satisfaction"
            ]

            population_change = 0

            if satisfaction >= 90:
                population_change = random.randint(
                    3,
                    7,
                )

            elif satisfaction >= 80:
                population_change = random.randint(
                    2,
                    5,
                )

            elif satisfaction >= 70:
                population_change = random.randint(
                    1,
                    3,
                )

            elif satisfaction >= 60:
                population_change = random.randint(
                    0,
                    2,
                )

            elif satisfaction >= 45:
                population_change = random.randint(
                    -1,
                    1,
                )

            elif satisfaction >= 30:
                population_change = random.randint(
                    -3,
                    0,
                )

            else:
                population_change = random.randint(
                    -6,
                    -1,
                )

            # Housing pressure
            if population >= housing_capacity:
                population_change -= random.randint(
                    1,
                    3,
                )

            # Employment pressure
            if population > jobs * 1.2:
                population_change -= random.randint(
                    1,
                    2,
                )

            # High satisfaction migration
            if satisfaction >= 85:
                population_change += random.randint(
                    1,
                    3,
                )

            # Very low satisfaction migration
            if satisfaction < 30:
                population_change -= random.randint(
                    1,
                    3,
                )

            # Strong economy attracts citizens
            if city["economy"] >= 80:
                population_change += random.randint(
                    0,
                    2,
                )

            # -------------------------------------------------
            # Population limits
            # -------------------------------------------------

            new_population = max(
                50,
                population + population_change,
            )

            # Do not allow extreme housing overload
            if (
                new_population
                > housing_capacity + 250
            ):
                new_population = min(
                    new_population,
                    housing_capacity + 250,
                )

            # -------------------------------------------------
            # City level
            # -------------------------------------------------

            level = city[
                "city_level"
            ]

            required_population = (
                level * 250
            )

            if (
                new_population
                >= required_population
                and satisfaction >= 65
                and level < MAX_LEVEL
            ):
                level += 1

                await conn.execute(
                    """
                    INSERT INTO news(
                        user_id,
                        text
                    )
                    VALUES($1,$2)
                    """,
                    user_id,
                    f"🎉 شهر به سطح {level} رسید!",
                )

            # -------------------------------------------------
            # Apply satisfaction/population
            # -------------------------------------------------

            new_satisfaction = clamp(
                satisfaction
                + satisfaction_change,
                0,
                100,
            )

            await conn.execute(
                """
                UPDATE cities
                SET
                    population=$1,
                    jobs=$2,
                    city_level=$3,
                    satisfaction=$4,
                    security=$5,
                    fire_safety=$6,
                    health=$7,
                    power=$8,
                    water=$9,
                    education=$10,
                    recreation=$11,
                    pollution_control=$12,
                    infrastructure=$13,
                    crisis=$14,
                    economy=$15,
                    housing_capacity=$16,
                    last_tick=NOW()
                WHERE user_id=$17
                """,
                new_population,
                jobs,
                level,
                new_satisfaction,
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
                clamp(
                    50
                    + economy_bonus
                    + stats["education"] // 4
                    + new_population // 200
                    - pollution_net // 3,
                    0,
                    100,
                ),
                housing_capacity,
                user_id,
            )

    # ---------------------------------------------------------
    # Income
    # ---------------------------------------------------------

    await recalculate_city(user_id)
    await collect_income(user_id)

    city = await get_city(user_id)

    if not city:
        return

    # ---------------------------------------------------------
    # Crisis generation
    # ---------------------------------------------------------

    active = await get_active_crisis(
        user_id
    )

    if not active:
        danger = 15

        danger -= city["security"] // 10
        danger -= city["fire_safety"] // 10
        danger -= city["health"] // 10
        danger -= city["infrastructure"] // 10
        danger -= city["crisis"] // 10

        danger += max(
            0,
            60 - city["satisfaction"],
        ) // 5

        danger = clamp(
            danger,
            2,
            20,
        )

        if random.randint(
            1,
            100,
        ) <= danger:

            crisis = await create_crisis(
                user_id
            )

            if crisis:
                try:
                    data = CRISES[
                        crisis["crisis_type"]
                    ]

                    await bot.send_message(
                        user_id,
                        "🚨 <b>هشدار شهری!</b>\n\n"
                        f"{data['name']}\n\n"
                        "یک بحران جدید در شهر اتفاق افتاده!\n\n"
                        f"🔥 شدت: "
                        f"{crisis['severity']} از 100\n\n"
                        "سریع وارد بخش «🚨 بحران‌ها» شو.",
                    )
                except Exception:
                    logging.exception(
                        "Could not notify user about crisis."
                    )

    # ---------------------------------------------------------
    # Weekly score
    # ---------------------------------------------------------

    await update_weekly_score(
        user_id
    )


# =========================================================
# NATURAL DISASTERS
# =========================================================

async def create_daily_disaster_schedule():
    today=iran_now().date()
    day_start=datetime.combine(today, datetime.min.time(), tzinfo=IRAN_TZ)
    max_minute=23*60+30
    async with db_pool.acquire() as conn:
        cities=await conn.fetch("SELECT user_id FROM cities")
        for city in cities:
            uid=city["user_id"]
            exists=await conn.fetchval("SELECT 1 FROM natural_disaster_schedule WHERE user_id=$1 AND disaster_date=$2 LIMIT 1", uid, today)
            if exists:
                continue
            count=random.randint(1,4)
            minutes=None
            for _ in range(200):
                candidate=sorted(random.sample(range(30,max_minute+1),count))
                if all(candidate[i]-candidate[i-1] >= MIN_DISASTER_GAP_MINUTES for i in range(1,count)):
                    minutes=candidate; break
            if minutes is None:
                minutes=[30+i*MIN_DISASTER_GAP_MINUTES for i in range(count)]
            disasters=[x[0] for x in random.sample(NATURAL_DISASTERS,count)]
            for occurrence,(minute,name) in enumerate(zip(minutes,disasters),1):
                scheduled=(day_start+timedelta(minutes=minute)).astimezone(timezone.utc)
                await conn.execute(
                    """INSERT INTO natural_disaster_schedule(user_id,disaster_date,occurrence_no,scheduled_at,disaster_name) VALUES($1,$2,$3,$4,$5) ON CONFLICT(user_id,disaster_date,occurrence_no) DO NOTHING""",
                    uid,today,occurrence,scheduled,name
                )


async def trigger_due_natural_disasters():
    now=now_utc()
    async with db_pool.acquire() as conn:
        due=await conn.fetch("""SELECT id,user_id,disaster_name FROM natural_disaster_schedule WHERE triggered=FALSE AND scheduled_at <= $1 ORDER BY scheduled_at ASC LIMIT 100""",now)
    for sch in due:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                row=await conn.fetchrow("SELECT * FROM natural_disaster_schedule WHERE id=$1 AND triggered=FALSE FOR UPDATE",sch["id"])
                if not row: continue
                building=await conn.fetchrow("SELECT building_type FROM buildings WHERE user_id=$1 AND level>0 ORDER BY RANDOM() LIMIT 1",sch["user_id"])
                btype=building["building_type"] if building else None
                damage=random.randint(10,500) if btype else 0
                event=await conn.fetchrow("""INSERT INTO natural_disaster_events(schedule_id,user_id,disaster_name,building_type,damage) VALUES($1,$2,$3,$4,$5) RETURNING id""",row["id"],sch["user_id"],row["disaster_name"],btype,damage)
                await conn.execute("UPDATE natural_disaster_schedule SET triggered=TRUE WHERE id=$1",row["id"])
        try:
            if btype:
                bname=BUILDINGS.get(btype,{}).get("name",btype)
                kb=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=f"🔧 تعمیر فوری ({damage:,} 🪙)",callback_data=f"natural_repair:{event['id']}")],
                    [InlineKeyboardButton(text="⏳ بعداً پرداخت می‌کنم",callback_data=f"natural_later:{event['id']}")],
                ])
                text=("🚨 <b>هشدار بلای طبیعی!</b>\n\n" f"{safe_text(row['disaster_name'])} بر سر شهرتون اومد!\n\n" f"🏢 ساختمان آسیب‌دیده: {safe_text(bname)}\n" f"💰 هزینه اولیه تعمیر: {damage:,} سکه\n\n" "⚠️ با هر ساعت تأخیر، ۱۰ سکه به هزینه تعمیر اضافه می‌شود.\n\nفوراً اقدام لازم را انجام دهید.")
            else:
                kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏙️ مشاهده شهر",callback_data="city")],[InlineKeyboardButton(text="🔙 منو",callback_data="menu")]])
                text=("🚨 <b>هشدار بلای طبیعی!</b>\n\n" f"{safe_text(row['disaster_name'])} بر سر شهرتون اومد!\n\n" "فعلاً ساختمانی برای آسیب‌دیدن وجود نداشت؛ حادثه در سوابق شهر ثبت شد.")
            await bot.send_message(sch["user_id"],text,reply_markup=kb)
        except Exception:
            logging.exception("Could not notify natural disaster for %s",sch["user_id"])


@dp.callback_query(F.data.startswith("natural_repair:"))
async def natural_repair_callback(callback: CallbackQuery):
    event_id=int(callback.data.split(":",1)[1]); uid=callback.from_user.id
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            row=await conn.fetchrow("SELECT * FROM natural_disaster_events WHERE id=$1 AND user_id=$2 AND repaired=FALSE FOR UPDATE",event_id,uid)
            if not row:
                await callback.answer("این خسارت قبلاً تعمیر شده یا پیدا نشد.",show_alert=True); return
            cost=row["damage"]+max(0,int((now_utc()-row["created_at"]).total_seconds()//3600))*10
            balance=await conn.fetchval("SELECT coins FROM resources WHERE user_id=$1 FOR UPDATE",uid)
            if balance < cost:
                await callback.answer(f"سکه کافی نیست. هزینه فعلی {cost:,} سکه است.",show_alert=True); return
            await conn.execute("UPDATE resources SET coins=coins-$1 WHERE user_id=$2",cost,uid)
            await conn.execute("UPDATE natural_disaster_events SET repaired=TRUE,repaired_at=NOW() WHERE id=$1",event_id)
    await callback.answer("تعمیر با موفقیت انجام شد. 🔧")
    await callback.message.edit_text(f"✅ <b>ساختمان تعمیر شد.</b>\n\n💰 هزینه تعمیر: {cost:,} سکه",reply_markup=main_keyboard())


@dp.callback_query(F.data.startswith("natural_later:"))
async def natural_later_callback(callback: CallbackQuery):
    await callback.answer("خسارت باقی ماند؛ هر ساعت ۱۰ سکه به هزینه اضافه می‌شود.")
    await callback.message.edit_text("⏳ <b>تعمیر به بعد موکول شد.</b>\n\n🏗️ خسارت در بخش ساختمان‌ها باقی می‌ماند.\n💰 هزینه تعمیر هر ساعت ۱۰ سکه افزایش پیدا می‌کند.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏗️ ساختمان‌ها",callback_data="buildings")],[InlineKeyboardButton(text="🔙 منو",callback_data="menu")]]))


# =========================================================
# BACKGROUND GAME TICK
# =========================================================

async def complete_building_constructions():
    now = now_utc()
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, user_id, building_type, target_level FROM building_constructions WHERE completed=FALSE AND ready_at <= $1 ORDER BY ready_at LIMIT 100",
            now,
        )
    for row in rows:
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                locked = await conn.fetchrow(
                    "SELECT * FROM building_constructions WHERE id=$1 AND completed=FALSE FOR UPDATE", row["id"]
                )
                if not locked:
                    continue
                await conn.execute(
                    "INSERT INTO buildings(user_id, building_type, level) VALUES($1,$2,$3) ON CONFLICT(user_id,building_type) DO UPDATE SET level=EXCLUDED.level",
                    row["user_id"], row["building_type"], row["target_level"],
                )
                await conn.execute("UPDATE building_constructions SET completed=TRUE WHERE id=$1", row["id"])
                name = BUILDINGS.get(row["building_type"], {}).get("name", "ساختمان")
                await conn.execute("INSERT INTO news(user_id,text) VALUES($1,$2)", row["user_id"], f"🎉 {name} با موفقیت به سطح {row['target_level']} رسید.")
        try:
            await recalculate_city(row["user_id"])
            await bot.send_message(row["user_id"], f"🎉 <b>ارتقای ساختمان تمام شد!</b>\n\n{safe_text(name)} اکنون در <b>سطح {row['target_level']}</b> قرار دارد.")
        except Exception:
            logging.exception("Could not notify completed construction")


async def game_tick():
    """
    حلقه اصلی بازی.
    هر 30 دقیقه همه بازیکنان فعال را بررسی می‌کند.
    """

    logging.info(
        "Background game tick started."
    )

    while True:
        try:
            await complete_building_constructions()
            await create_daily_disaster_schedule()
            await trigger_due_natural_disasters()
            await process_weekly_payout()
            await process_group_transfers()

            async with db_pool.acquire() as conn:
                users = await conn.fetch(
                    """
                    SELECT user_id
                    FROM players
                    """
                )

            logging.info(
                "Game tick: processing %s players.",
                len(users),
            )

            for row in users:
                user_id = row["user_id"]

                try:
                    await process_player_tick(
                        user_id
                    )
                except Exception:
                    logging.exception(
                        "Game tick failed for user %s",
                        user_id,
                    )

                # فشار کمتر روی دیتابیس
                await asyncio.sleep(0.05)

        except asyncio.CancelledError:
            logging.info(
                "Background game tick cancelled."
            )
            raise

        except Exception:
            logging.exception(
                "Global game tick error."
            )

        await asyncio.sleep(
            30 * 60
        )


# =========================================================
# COMMANDS
# =========================================================

@dp.message(Command("city"))
async def city_command(message: Message):
    user_id = await ensure_player(message)

    await process_player_tick(
        user_id
    )

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
async def profile_command(
    message: Message
):
    user_id = await ensure_player(message)

    await process_player_tick(
        user_id
    )

    player = await get_player(
        user_id
    )

    city = await get_city(
        user_id
    )

    if not player or not city:
        await message.answer(
            "❌ اطلاعات پروفایل پیدا نشد."
        )
        return

    await message.answer(
        "👑 <b>پروفایل شهردار</b>\n\n"
        f"👤 {safe_text(player['first_name'] or 'شهردار')}\n"
        f"🏙️ شهر: "
        f"{safe_text(city['city_name'])}\n\n"
        f"⭐ سطح: {player['level']}\n"
        f"✨ XP: {player['xp']}\n\n"
        f"👥 جمعیت: "
        f"{city['population']:,}\n"
        f"😊 رضایت: "
        f"{city['satisfaction']}%\n"
        f"📈 اقتصاد: "
        f"{city['economy']}%"
    )


# =========================================================
# FRIENDS COMMAND
# =========================================================

@dp.message(Command("friends"))
async def friends_command(
    message: Message
):
    user_id = await ensure_player(
        message
    )

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                p.user_id,
                p.first_name,
                c.city_name
            FROM friendships f
            JOIN players p
                ON p.user_id=f.friend_id
            JOIN cities c
                ON c.user_id=p.user_id
            WHERE f.user_id=$1
            LIMIT 20
            """,
            user_id,
        )

        requests = await conn.fetch(
            """
            SELECT
                p.first_name,
                p.user_id
            FROM friend_requests fr
            JOIN players p
                ON p.user_id=fr.sender_id
            WHERE fr.receiver_id=$1
              AND fr.status='pending'
            LIMIT 10
            """,
            user_id,
        )

    if rows:
        friends_text = "\n\n".join(
            (
                f"👤 {safe_text(row['first_name'])}\n"
                f"🏙️ {safe_text(row['city_name'])}"
            )
            for row in rows
        )
    else:
        friends_text = (
            "هنوز دوستی نداری."
        )

    if requests:
        request_text = "\n\n".join(
            (
                f"📨 {safe_text(row['first_name'])}\n"
                f"🆔 شناسه: {row['user_id']}"
            )
            for row in requests
        )
    else:
        request_text = (
            "درخواست جدیدی نداری."
        )

    await message.answer(
        "🤝 <b>دوستان من</b>\n\n"
        "👥 <b>دوستان</b>\n\n"
        f"{friends_text}\n\n"
        "━━━━━━━━━━━━\n\n"
        "📨 <b>درخواست‌ها</b>\n\n"
        f"{request_text}\n\n"
        "━━━━━━━━━━━━\n\n"
        "برای مدیریت درخواست‌ها وارد "
        "بخش اجتماعی شو.",
        reply_markup=main_keyboard(),
    )


# =========================================================
# CITY NAME
# =========================================================

@dp.message(Command("namecity"))
async def name_city_command(
    message: Message
):
    user_id = await ensure_player(
        message
    )

    parts = message.text.split(
        maxsplit=1
    )

    if len(parts) < 2:
        await message.answer(
            "❌ اسم شهر را وارد نکردی.\n\n"
            "مثال:\n"
            "<code>/namecity تبریز نو</code>"
        )
        return

    name = parts[1].strip()[:40]

    if len(name) < 2:
        await message.answer(
            "❌ اسم شهر خیلی کوتاه است."
        )
        return

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE cities
            SET city_name=$1
            WHERE user_id=$2
            """,
            name,
            user_id,
        )

        await conn.execute(
            """
            INSERT INTO news(
                user_id,
                text
            )
            VALUES($1,$2)
            """,
            user_id,
            f"🏙️ نام شهر به «{name}» تغییر کرد.",
        )

    await message.answer(
        "✅ <b>نام شهر تغییر کرد!</b>\n\n"
        f"🏙️ نام جدید: "
        f"<b>{safe_text(name)}</b>"
    )


# =========================================================
# COMMANDS HELP
# =========================================================

@dp.message(Command("commands"))
async def commands_command(
    message: Message
):
    await ensure_player(message)

    await message.answer(
        "📚 <b>دستورات شهر من</b>\n\n"
        "<code>/start</code>\n"
        "<code>/menu</code>\n"
        "<code>/city</code>\n"
        "<code>/profile</code>\n\n"
        "🏙️ <b>شهر:</b>\n"
        "<code>/namecity نام شهر</code>\n\n"
        "🤝 <b>اجتماعی:</b>\n"
        "<code>/addfriend PLAYER_ID</code>\n"
        "<code>/friends</code>\n"
        "<code>/help PLAYER_ID COINS FOOD MATERIALS</code>\n\n"
        "🏙️ <b>گروه تلگرامی:</b> ربات را به گروه اضافه و مدیر کن؛ سپس اعضا با نوشتن «شهر من» پنل دارایی خود را می‌بینند.\n\n"
        "🏪 <b>بازار:</b>\n"
        "برای خرید و فروش منابع از دکمه «🏪 بازار» در منوی اصلی استفاده کن.\n\n"
        "برای بقیه امکانات از منوی اصلی استفاده کن.",
        reply_markup=main_keyboard(),
    )


# =========================================================
# UNKNOWN TEXT
# =========================================================

@dp.message()
async def unknown_message(
    message: Message
):
    if message.chat.type in {"group", "supergroup"}:
        return
    await message.answer(
        "🏙️ برای مدیریت شهر از منوی زیر استفاده کن:\n\n"
        "<code>/start</code>\n"
        "<code>/menu</code>\n"
        "<code>/city</code>\n"
        "<code>/profile</code>\n"
        "<code>/commands</code>\n\n"
        "یا از دکمه‌های منو استفاده کن.",
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

    app.router.add_get(
        "/",
        health,
    )

    app.router.add_get(
        "/health",
        health,
    )

    runner = web.AppRunner(
        app
    )

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
    web_runner = None
    tick_task = None

    try:
        await init_db()

        logging.info(
            "Database connected."
        )

        web_runner = await start_web_server()

        tick_task = asyncio.create_task(
            game_tick()
        )

        logging.info(
            "Shahr Man bot started."
        )

        await dp.start_polling(
            bot
        )

    except asyncio.CancelledError:
        logging.info(
            "Main task cancelled."
        )
        raise

    except Exception:
        logging.exception(
            "Fatal error in main."
        )
        raise

    finally:
        if tick_task:
            tick_task.cancel()

            try:
                await tick_task
            except asyncio.CancelledError:
                pass

        if web_runner:
            try:
                await web_runner.cleanup()
            except Exception:
                logging.exception(
                    "Error cleaning web server."
                )

        if db_pool:
            try:
                await db_pool.close()
            except Exception:
                logging.exception(
                    "Error closing database pool."
                )

        try:
            await bot.session.close()
        except Exception:
            logging.exception(
                "Error closing bot session."
            )


if __name__ == "__main__":
    asyncio.run(main())
