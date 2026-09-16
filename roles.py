"""
تعریف نقش‌ها و منطق تخصیص رندوم بر اساس درصد
"""
import random
import config


def role_definitions() -> dict:
    return {
        "killer": {
            "label": "🔪 قاتل",
            "desc": "هر ۳ دقیقه می‌تونی یکی رو بکشی.",
            "action_type": "target",
            "one_time": False,
        },
        "detective": {
            "label": "🕵️ کاراگاه",
            "desc": "هر ۵ دقیقه می‌تونی یه نفر رو استعلام کنی (نتیجه فقط پیش خودت می‌مونه).",
            "action_type": "target",
            "one_time": False,
        },
        "doctor": {
            "label": "💊 دکتر",
            "desc": "هر ۴ دقیقه می‌تونی یه نفر (یا خودت) رو در برابر قتل ایمن کنی.",
            "action_type": "target",
            "one_time": False,
        },
        "mayor": {
            "label": "🎖 شهردار",
            "desc": "هر ۱۰ دقیقه می‌تونی رأی‌گیری اضطراری راه بندازی. رأیت وزن دوبرابر داره.",
            "action_type": "none",
            "one_time": False,
        },
        "spy": {
            "label": "🕶 جاسوس دولت",
            "desc": "هر ۵ دقیقه می‌تونی گزارش بگیری چند نفر اخیراً فعالیت مشکوک داشتن.",
            "action_type": "none",
            "one_time": False,
        },
        "smuggler": {
            "label": "📦 قاچاقچی",
            "desc": "هر ۶ دقیقه می‌تونی به یه نفر یه محافظ موقت بدی.",
            "action_type": "target",
            "one_time": False,
        },
        "journalist": {
            "label": "📰 روزنامه‌نگار",
            "desc": "فقط یک بار در طول بازی می‌تونی یه شایعه درباره یکی منتشر کنی.",
            "action_type": "target",
            "one_time": True,
        },
        "guardian": {
            "label": "🛡 محافظ",
            "desc": "هر ۵ دقیقه می‌تونی یه نفر رو در برابر اخراج (رأی‌گیری) مصون کنی.",
            "action_type": "target",
            "one_time": False,
        },
        "citizen": {
            "label": "👤 شهروند عادی",
            "desc": "قابلیت ویژه‌ای نداری؛ فقط چت کن، رأی بده و دقت کن.",
            "action_type": "none",
            "one_time": False,
        },
    }


def role_label(role) -> str:
    if role is None:
        return "نامشخص"
    return role_definitions().get(role, {}).get("label", role)


def assign_roles(player_ids: list) -> dict:
    """
    تخصیص رندوم نقش‌ها بر اساس فرمول درصدی تعریف‌شده در config
    ورودی: لیستی از player_id ها
    خروجی: {player_id: role}
    """
    ratios = config.ROLE_RATIOS
    pool = list(player_ids)
    random.SystemRandom().shuffle(pool)

    n = len(pool)
    assignment = {}

    order = ["mayor", "killer", "detective", "doctor", "guardian", "spy", "smuggler", "journalist"]

    for role in order:
        if not pool:
            break
        cfg = ratios[role]
        count = round(n * cfg["ratio"])
        if cfg["min"] is not None:
            count = max(count, cfg["min"])
        if cfg["max"] is not None:
            count = min(count, cfg["max"])
        count = min(count, len(pool))

        for _ in range(count):
            pid = pool.pop()
            assignment[pid] = role

    for pid in pool:
        assignment[pid] = "citizen"

    return assignment
