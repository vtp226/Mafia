"""
تنظیمات ربات — همه چیز از environment variables خونده می‌شه.
تو Railway از تب Variables ست‌شون می‌کنی. برای اجرای لوکال یه فایل .env
از روی .env.example بساز (پکیج python-dotenv خودکار لودش می‌کنه).
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _env(key: str, default=None):
    v = os.environ.get(key)
    return v if v not in (None, "") else default


def _env_int(key: str, default: int = 0) -> int:
    v = _env(key)
    return int(v) if v not in (None, "") else default


def _env_float(key: str, default: float = 0.0) -> float:
    v = _env(key)
    return float(v) if v not in (None, "") else default


def _env_list_int(key: str) -> list:
    v = _env(key, "") or ""
    return [int(x.strip()) for x in v.split(",") if x.strip()]


def _parse_chat_id(raw):
    """یوزرنیم ('@channel') رو همون‌جوری نگه می‌داره، آیدی عددی رو به int تبدیل می‌کنه."""
    if raw is None or raw == "":
        return None
    raw = str(raw)
    if raw.lstrip("-").isdigit():
        return int(raw)
    return raw


BOT_TOKEN = _env("BOT_TOKEN", "")
BOT_USERNAME = _env("BOT_USERNAME", "")

CHANNEL_ID_RAW = _env("CHANNEL_ID", "")
CHANNEL_ID = _parse_chat_id(CHANNEL_ID_RAW)

GROUP_ID = _env_int("GROUP_ID", 0)

ADMIN_IDS = _env_list_int("ADMIN_IDS")

DB_PATH = _env("DB_PATH", os.path.join(os.path.dirname(__file__), "data", "bot.sqlite"))

MIN_PLAYERS = _env_int("MIN_PLAYERS", 5)
VOTE_THRESHOLD_RATIO = _env_float("VOTE_THRESHOLD_RATIO", 0.34)
VOTE_THRESHOLD_MIN = _env_int("VOTE_THRESHOLD_MIN", 3)
VOTE_DURATION = _env_int("VOTE_DURATION", 120)  # ثانیه
CRON_INTERVAL_SECONDS = _env_int("CRON_INTERVAL_SECONDS", 30)  # هر چند وقت رأی‌گیری‌های تموم‌شده چک بشن

COOLDOWNS = {
    "killer": 180,
    "detective": 300,
    "doctor": 240,
    "mayor": 600,
    "spy": 300,
    "smuggler": 360,
    "guardian": 300,
}

ROLE_RATIOS = {
    "killer":     {"ratio": 0.15, "min": 1, "max": None},
    "detective":  {"ratio": 0.10, "min": 1, "max": None},
    "doctor":     {"ratio": 0.10, "min": 1, "max": None},
    "mayor":      {"ratio": 0.00, "min": 1, "max": 1},
    "spy":        {"ratio": 0.08, "min": 0, "max": None},
    "smuggler":   {"ratio": 0.08, "min": 0, "max": None},
    "journalist": {"ratio": 0.05, "min": 0, "max": 1},
    "guardian":   {"ratio": 0.07, "min": 0, "max": None},
}


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS
