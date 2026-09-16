"""
کل منطق بازی «شهر مخفی»: ثبت‌نام، شروع بازی، اقدام‌ها، رأی‌گیری، پایان بازی.
"""
import html
import logging
import time

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

import config
import db
import roles

log = logging.getLogger("game")


# ---------------------------------------------------------------
# ابزارهای کمکی تلگرام
# ---------------------------------------------------------------

async def safe_send(bot: Bot, chat_id, text: str, reply_markup=None):
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=reply_markup,
        )
    except TelegramError as e:
        log.warning("send_message به %s شکست خورد: %s", chat_id, e)
        return None


async def is_member(bot: Bot, chat_id, user_id: int) -> bool:
    if not chat_id:
        return False
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
    except TelegramError as e:
        log.warning("get_chat_member(%s, %s) شکست خورد: %s", chat_id, user_id, e)
        return False
    return member.status in ("member", "administrator", "creator", "restricted")


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


def url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, url=url)


def kb(rows: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------
# بازی‌ها
# ---------------------------------------------------------------

def get_open_game():
    conn = db.get_conn()
    row = conn.execute(
        "SELECT * FROM games WHERE status IN ('registering','active') ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def create_game():
    conn = db.get_conn()
    conn.execute("INSERT INTO games (status, created_at) VALUES ('registering', ?)", (db.now(),))
    conn.commit()
    return get_game_by_id(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])


def get_game_by_id(game_id: int):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------
# بازیکن‌ها
# ---------------------------------------------------------------

def find_player(game_id: int, user_id: int):
    conn = db.get_conn()
    row = conn.execute(
        "SELECT * FROM players WHERE game_id = ? AND user_id = ?", (game_id, user_id)
    ).fetchone()
    return dict(row) if row else None


def get_player_by_id(player_id: int):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
    return dict(row) if row else None


def set_player_state(player_id: int, state):
    conn = db.get_conn()
    conn.execute("UPDATE players SET state = ? WHERE id = ?", (state, player_id))
    conn.commit()


def alive_players(game_id: int) -> list:
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM players WHERE game_id = ? AND status = 'alive'", (game_id,)).fetchall()
    return [dict(r) for r in rows]


def dead_players(game_id: int) -> list:
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM players WHERE game_id = ? AND status = 'dead'", (game_id,)).fetchall()
    return [dict(r) for r in rows]


async def start_registration(bot: Bot, game: dict, user_id: int) -> dict:
    if game["status"] != "registering":
        return {"ok": False, "message": "ثبت‌نام این دوره از بازی بسته شده. منتظر دوره‌ی بعد باش."}

    in_channel = await is_member(bot, config.CHANNEL_ID, user_id)
    in_group = await is_member(bot, config.GROUP_ID, user_id)
    if not in_channel or not in_group:
        return {"ok": False, "message": "membership_required"}

    conn = db.get_conn()
    existing = find_player(game["id"], user_id)
    if existing:
        if existing["alias"]:
            return {"ok": False, "message": f"شما قبلاً با اسم «{existing['alias']}» ثبت‌نام کردی."}
        set_player_state(existing["id"], "awaiting_alias")
        return {"ok": True, "message": "اسم مستعارت رو بنویس (فقط متن، بدون ایموجی عجیب):"}

    conn.execute(
        """INSERT INTO players (game_id, user_id, registered_before_start, state, created_at)
           VALUES (?, ?, 1, 'awaiting_alias', ?)""",
        (game["id"], user_id, db.now()),
    )
    conn.commit()
    return {"ok": True, "message": "اسم مستعارت رو بنویس (فقط متن، بدون ایموجی عجیب):"}


def save_alias(player: dict, alias: str) -> dict:
    alias = alias.strip()[:30].strip()
    if alias == "":
        return {"ok": False, "message": "اسم خالیه، یه اسم دیگه بفرست."}

    conn = db.get_conn()
    dup = conn.execute(
        "SELECT id FROM players WHERE game_id = ? AND alias = ? AND id != ?",
        (player["game_id"], alias, player["id"]),
    ).fetchone()
    if dup:
        return {"ok": False, "message": "این اسم قبلاً گرفته شده، یه اسم دیگه انتخاب کن."}

    conn.execute("UPDATE players SET alias = ?, state = NULL WHERE id = ?", (alias, player["id"]))
    conn.commit()
    return {"ok": True, "alias": alias}


# ---------------------------------------------------------------
# شروع بازی
# ---------------------------------------------------------------

async def start_game(bot: Bot, game: dict) -> dict:
    conn = db.get_conn()
    players = [dict(r) for r in conn.execute(
        "SELECT * FROM players WHERE game_id = ? AND alias IS NOT NULL", (game["id"],)
    ).fetchall()]

    if len(players) < config.MIN_PLAYERS:
        return {
            "ok": False,
            "message": f"حداقل {config.MIN_PLAYERS} بازیکن با اسم ثبت‌شده لازمه (الان: {len(players)} نفر).",
        }

    ids = [p["id"] for p in players]
    assignment = roles.assign_roles(ids)

    for player_id, role in assignment.items():
        conn.execute("UPDATE players SET role = ? WHERE id = ?", (role, player_id))
    conn.execute("UPDATE games SET status = 'active', started_at = ? WHERE id = ?", (db.now(), game["id"]))
    conn.commit()

    defs = roles.role_definitions()
    for p in players:
        role = assignment[p["id"]]
        d = defs[role]
        text = (
            f"🎮 بازی شروع شد!\n\n"
            f"نقش تو: <b>{d['label']}</b>\n{d['desc']}\n\n"
            f"از /menu برای دسترسی به امکانات استفاده کن. هر پیام معمولی که اینجا بفرستی، "
            f"با اسم مستعار «{p['alias']}» توی کانال پست می‌شه."
        )
        p_with_role = dict(p, role=role)
        await safe_send(bot, p["user_id"], text, main_menu_keyboard(p_with_role))

    await safe_send(
        bot, config.GROUP_ID,
        f"🎮 بازی «شهر مخفی» شروع شد!\n👥 {len(players)} بازیکن وارد شهر شدن.\nمراقب باشید، بین‌تون قاتل هست...",
    )
    return {"ok": True}


# ---------------------------------------------------------------
# ارسال پیام به کانال
# ---------------------------------------------------------------

async def relay_to_channel(bot: Bot, player: dict, text: str) -> dict:
    if player["status"] != "alive":
        return {"ok": False, "message": "تو دیگه زنده نیستی و نمی‌تونی توی بازی چت کنی."}
    if not player["registered_before_start"]:
        return {"ok": False, "message": "شما توی این دوره از بازی ثبت‌نام نکردی، پیامت پست نمی‌شه."}
    if not player["alias"]:
        return {"ok": False, "message": "اول باید ثبت‌نامت رو با یه اسم مستعار کامل کنی."}

    in_channel = await is_member(bot, config.CHANNEL_ID, player["user_id"])
    in_group = await is_member(bot, config.GROUP_ID, player["user_id"])
    if not in_channel or not in_group:
        return {"ok": False, "message": "باید عضو کانال و گروه بازی باشی تا بتونی چت کنی."}

    safe_alias = html.escape(player["alias"])
    safe_text = html.escape(text)
    await safe_send(bot, config.CHANNEL_ID, f"<b>{safe_alias}</b> نوشت:\n{safe_text}")
    return {"ok": True}


# ---------------------------------------------------------------
# منوی اصلی و کیبوردها
# ---------------------------------------------------------------

def main_menu_keyboard(player: dict) -> InlineKeyboardMarkup:
    rows = [[btn("🎭 نقش من", "role_info")]]

    defs = roles.role_definitions()
    d = defs.get(player.get("role"))

    if d and d["action_type"] != "none":
        cooldown_left = action_cooldown_remaining(player)
        if d["one_time"] and player.get("journalist_used"):
            rows.append([btn("✅ قابلیتت استفاده شده", "noop")])
        elif cooldown_left > 0:
            rows.append([btn(f"⏳ اقدام ({cooldown_left}s مونده)", "noop")])
        else:
            rows.append([btn("🔪 اقدام", "action_start")])
    elif d and d["action_type"] == "none" and player.get("role") != "citizen":
        cooldown_left = action_cooldown_remaining(player)
        if cooldown_left > 0:
            rows.append([btn(f"⏳ اقدام ({cooldown_left}s مونده)", "noop")])
        else:
            rows.append([btn("⚡ اقدام", "action_start")])

    rows.append([btn("📋 بازیکنان زنده", "list_alive"), btn("⚰️ کشته‌شده‌ها", "list_dead")])
    rows.append([btn("ℹ️ وضعیت بازی", "status")])
    return kb(rows)


def action_cooldown_seconds(role: str):
    return config.COOLDOWNS.get(role)


def action_cooldown_remaining(player: dict) -> int:
    cd = action_cooldown_seconds(player.get("role"))
    if cd is None:
        return 0
    elapsed = db.now() - int(player.get("last_action_time") or 0)
    return max(0, cd - elapsed)


# ---------------------------------------------------------------
# اقدام‌ها (Actions)
# ---------------------------------------------------------------

def target_list_keyboard(game_id: int, exclude_player_id: int, callback_prefix: str) -> InlineKeyboardMarkup:
    players = alive_players(game_id)
    rows = []
    for p in players:
        if int(p["id"]) == exclude_player_id:
            continue
        rows.append([btn(p["alias"], f"{callback_prefix}_{p['id']}")])
    if not rows:
        rows.append([btn("کسی در دسترس نیست", "noop")])
    return kb(rows)


async def perform_action(bot: Bot, game: dict, actor: dict, target_player_id):
    role = actor.get("role")
    defs = roles.role_definitions()
    d = defs.get(role)
    if not d or (d["action_type"] == "none" and role == "citizen"):
        return {"ok": False, "message": "این نقش قابلیت خاصی نداره."}

    if d.get("one_time"):
        if actor.get("journalist_used"):
            return {"ok": False, "message": "قابلیتت رو قبلاً استفاده کردی."}
    else:
        remaining = action_cooldown_remaining(actor)
        if remaining > 0:
            return {"ok": False, "message": f"هنوز {remaining} ثانیه مونده تا بتونی دوباره اقدام کنی."}

    target = get_player_by_id(target_player_id) if target_player_id else None
    if d["action_type"] == "target" and (not target or target["status"] != "alive"):
        return {"ok": False, "message": "این بازیکن در دسترس نیست."}

    if role == "killer":
        return await action_kill(bot, game, actor, target)
    if role == "detective":
        return await action_investigate(bot, game, actor, target)
    if role == "doctor":
        return await action_protect(bot, game, actor, target)
    if role == "guardian":
        return await action_guard(bot, game, actor, target)
    if role == "smuggler":
        return await action_smuggle(bot, game, actor, target)
    if role == "journalist":
        return await action_rumor(bot, game, actor, target)
    if role == "mayor":
        return await action_mayor_emergency_vote(bot, game, actor)
    if role == "spy":
        return await action_spy_report(bot, game, actor)
    return {"ok": False, "message": "این نقش قابلیت خاصی نداره."}


def mark_action_used(actor: dict, action_type: str, target_id):
    conn = db.get_conn()
    conn.execute("UPDATE players SET last_action_time = ? WHERE id = ?", (db.now(), actor["id"]))
    conn.execute(
        """INSERT INTO actions_log (game_id, player_id, action_type, target_player_id, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (actor["game_id"], actor["id"], action_type, target_id, db.now()),
    )
    conn.commit()


async def action_kill(bot: Bot, game: dict, actor: dict, target: dict):
    mark_action_used(actor, "kill", target["id"])
    conn = db.get_conn()
    now = db.now()

    if int(target["protected_until"] or 0) > now:
        await safe_send(bot, config.GROUP_ID, "🛡 یک نفر امشب مورد حمله قرار گرفت ولی نجات پیدا کرد!")
        return {"ok": True, "message": "حمله انجام شد ولی هدف محافظت داشت و نجات پیدا کرد."}

    conn.execute("UPDATE players SET status = 'dead' WHERE id = ?", (target["id"],))
    conn.execute(
        "INSERT INTO death_events (game_id, victim_player_id, created_at) VALUES (?, ?, ?)",
        (game["id"], target["id"], now),
    )
    conn.commit()
    death_event_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

    safe_alias = html.escape(target["alias"])
    keyboard = kb([[btn("🗳 درخواست رأی‌گیری", f"vote_request_{death_event_id}")]])
    await safe_send(bot, config.GROUP_ID, f"💀 <b>{safe_alias}</b> به قتل رسید!", keyboard)
    await safe_send(bot, target["user_id"], "💀 تو کشته شدی. دیگه نمی‌تونی توی کانال چت کنی، ولی می‌تونی وضعیت بازی رو دنبال کنی.")

    await check_win_condition(bot, game["id"])
    return {"ok": True, "message": "قتل انجام شد."}


async def action_investigate(bot: Bot, game: dict, actor: dict, target: dict):
    mark_action_used(actor, "investigate", target["id"])
    if target["role"] == "killer":
        result = "بله، این فرد مشکوکه (قاتله)! 🔪"
    else:
        result = "نه، این فرد قاتل به نظر نمی‌رسه."
    return {"ok": True, "message": f"نتیجه استعلام درباره «{target['alias']}»:\n{result}"}


async def action_protect(bot: Bot, game: dict, actor: dict, target: dict):
    mark_action_used(actor, "protect", target["id"])
    conn = db.get_conn()
    cd = action_cooldown_seconds("doctor")
    conn.execute("UPDATE players SET protected_until = ? WHERE id = ?", (db.now() + cd, target["id"]))
    conn.commit()
    return {"ok": True, "message": f"«{target['alias']}» رو برای مدتی در برابر قتل ایمن کردی."}


async def action_guard(bot: Bot, game: dict, actor: dict, target: dict):
    mark_action_used(actor, "guard", target["id"])
    conn = db.get_conn()
    cd = action_cooldown_seconds("guardian")
    conn.execute("UPDATE players SET vote_immune_until = ? WHERE id = ?", (db.now() + cd, target["id"]))
    conn.commit()
    await safe_send(bot, config.GROUP_ID, "🛡 یک نفر امشب از اخراج در رأی‌گیری مصون شد!")
    return {"ok": True, "message": f"«{target['alias']}» رو برای مدتی در برابر رأی‌گیری مصون کردی."}


async def action_smuggle(bot: Bot, game: dict, actor: dict, target: dict):
    mark_action_used(actor, "smuggle", target["id"])
    conn = db.get_conn()
    cd = action_cooldown_seconds("smuggler")
    conn.execute("UPDATE players SET protected_until = ? WHERE id = ?", (db.now() + cd // 2, target["id"]))
    conn.commit()
    return {"ok": True, "message": f"یه محافظ موقت مخفیانه به «{target['alias']}» رسوندی."}


async def action_rumor(bot: Bot, game: dict, actor: dict, target: dict):
    import random as _random
    conn = db.get_conn()
    conn.execute("UPDATE players SET journalist_used = 1 WHERE id = ?", (actor["id"],))
    conn.commit()
    mark_action_used(actor, "rumor", target["id"])

    is_true = _random.SystemRandom().randint(0, 1) == 1
    if is_true:
        guessed_role = roles.role_label(target["role"])
    else:
        all_roles = list(roles.role_definitions().keys())
        guessed_role = roles.role_label(_random.SystemRandom().choice(all_roles))

    safe_alias = html.escape(target["alias"])
    await safe_send(
        bot, config.GROUP_ID,
        f"📰 خبر فوری: شایعه شده «{safe_alias}» ممکنه نقش «{guessed_role}» داشته باشه... (صحت این خبر تأیید نشده!)",
    )
    return {"ok": True, "message": "شایعه‌ت منتشر شد."}


async def action_mayor_emergency_vote(bot: Bot, game: dict, actor: dict):
    remaining = action_cooldown_remaining(actor)
    if remaining > 0:
        return {"ok": False, "message": f"هنوز {remaining} ثانیه مونده."}
    mark_action_used(actor, "mayor_emergency_vote", None)
    await safe_send(bot, config.GROUP_ID, "📢 شهردار درخواست رأی‌گیری اضطراری داد!")
    await start_vote_session(bot, game, "mayor")
    return {"ok": True, "message": "رأی‌گیری اضطراری شروع شد."}


async def action_spy_report(bot: Bot, game: dict, actor: dict):
    remaining = action_cooldown_remaining(actor)
    if remaining > 0:
        return {"ok": False, "message": f"هنوز {remaining} ثانیه مونده."}
    mark_action_used(actor, "spy_report", None)

    conn = db.get_conn()
    since = int(actor.get("spy_last_check") or 0)
    row = conn.execute(
        "SELECT COUNT(DISTINCT player_id) c FROM actions_log WHERE game_id = ? AND created_at > ?",
        (game["id"], since),
    ).fetchone()
    count = row["c"]

    conn.execute("UPDATE players SET spy_last_check = ? WHERE id = ?", (db.now(), actor["id"]))
    conn.commit()

    await safe_send(bot, config.GROUP_ID, f"🕶 گزارشی درز کرد: به‌تازگی {count} نفر فعالیت مشکوک داشتن.")
    return {"ok": True, "message": f"گزارش منتشر شد ({count} نفر فعال بودن)."}


# ---------------------------------------------------------------
# رأی‌گیری
# ---------------------------------------------------------------

async def request_vote(bot: Bot, game: dict, requester: dict, death_event_id: int) -> dict:
    conn = db.get_conn()
    event = conn.execute(
        "SELECT * FROM death_events WHERE id = ? AND game_id = ?", (death_event_id, game["id"])
    ).fetchone()
    if not event:
        return {"ok": False, "message": "این رویداد دیگه معتبر نیست."}
    if event["vote_session_id"]:
        return {"ok": False, "message": "رأی‌گیری برای این مورد قبلاً شروع شده."}

    try:
        conn.execute(
            "INSERT INTO vote_requests (game_id, death_event_id, requester_player_id) VALUES (?, ?, ?)",
            (game["id"], death_event_id, requester["id"]),
        )
        conn.commit()
    except Exception:
        return {"ok": False, "message": "شما قبلاً درخواست داده بودی."}

    request_count = conn.execute(
        "SELECT COUNT(*) c FROM vote_requests WHERE death_event_id = ?", (death_event_id,)
    ).fetchone()["c"]

    alive_count = len(alive_players(game["id"]))
    threshold = max(config.VOTE_THRESHOLD_MIN, int(-(-alive_count * config.VOTE_THRESHOLD_RATIO // 1)))  # ceil

    safe_alias = html.escape(requester["alias"])
    await safe_send(bot, config.GROUP_ID, f"🗳 «{safe_alias}» درخواست رأی‌گیری داد. ({request_count}/{threshold})")

    if request_count >= threshold:
        session_id = await start_vote_session(bot, game, "community")
        conn.execute("UPDATE death_events SET vote_session_id = ? WHERE id = ?", (session_id, death_event_id))
        conn.commit()

    return {"ok": True}


async def start_vote_session(bot: Bot, game: dict, trigger_type: str) -> int:
    conn = db.get_conn()
    now = db.now()
    ends = now + config.VOTE_DURATION

    conn.execute(
        """INSERT INTO vote_sessions (game_id, status, trigger_type, started_at, ends_at)
           VALUES (?, 'active', ?, ?, ?)""",
        (game["id"], trigger_type, now, ends),
    )
    conn.commit()
    session_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

    players = alive_players(game["id"])
    rows = [[btn(p["alias"], f"vote_cast_{session_id}_{p['id']}")] for p in players]
    keyboard = kb(rows)

    minutes = round(config.VOTE_DURATION / 60, 1)
    await safe_send(
        bot, config.GROUP_ID,
        f"🗳 رأی‌گیری شروع شد! تا {minutes} دقیقه دیگه فرصت دارید رأی بدید.\n"
        f"هر بازیکن زنده باید توی پیوی ربات از منو گزینه‌ی «🗳 رأی‌گیری» رو بزنه.",
    )
    for p in players:
        await safe_send(bot, p["user_id"], "🗳 رأی‌گیری شروع شد! کی به نظرت باید حذف بشه؟", keyboard)

    return session_id


def cast_vote(game: dict, voter: dict, session_id: int, target_player_id: int) -> dict:
    conn = db.get_conn()
    session = conn.execute(
        "SELECT * FROM vote_sessions WHERE id = ? AND game_id = ?", (session_id, game["id"])
    ).fetchone()
    if not session or session["status"] != "active":
        return {"ok": False, "message": "این رأی‌گیری دیگه فعال نیست."}
    if voter["status"] != "alive":
        return {"ok": False, "message": "تو دیگه زنده نیستی و نمی‌تونی رأی بدی."}

    conn.execute(
        """INSERT INTO votes (session_id, voter_player_id, target_player_id) VALUES (?, ?, ?)
           ON CONFLICT(session_id, voter_player_id) DO UPDATE SET target_player_id = excluded.target_player_id""",
        (session_id, voter["id"], target_player_id),
    )
    conn.commit()
    return {"ok": True, "message": "رأیت ثبت شد."}


async def resolve_expired_vote_sessions(bot: Bot) -> None:
    conn = db.get_conn()
    now = db.now()
    sessions = [dict(r) for r in conn.execute(
        "SELECT * FROM vote_sessions WHERE status = 'active' AND ends_at <= ?", (now,)
    ).fetchall()]
    for session in sessions:
        await resolve_vote_session(bot, session)


async def resolve_vote_session(bot: Bot, session: dict) -> None:
    conn = db.get_conn()
    game = get_game_by_id(session["game_id"])

    tally = conn.execute(
        """
        SELECT v.target_player_id, p.alias, p.vote_immune_until,
               SUM(CASE WHEN vp.role = 'mayor' THEN 2 ELSE 1 END) as weight
        FROM votes v
        JOIN players p ON p.id = v.target_player_id
        JOIN players vp ON vp.id = v.voter_player_id
        WHERE v.session_id = ?
        GROUP BY v.target_player_id
        ORDER BY weight DESC
        """,
        (session["id"],),
    ).fetchall()

    eliminated = None
    for row in tally:
        if int(row["vote_immune_until"] or 0) > db.now():
            continue
        eliminated = row
        break

    if not eliminated:
        await safe_send(bot, config.GROUP_ID, "🗳 رأی‌گیری تموم شد و کسی حذف نشد (یا مصون بود یا رأی کافی نبود).")
    else:
        conn.execute("UPDATE players SET status = 'dead' WHERE id = ?", (eliminated["target_player_id"],))
        conn.commit()
        safe_alias = html.escape(eliminated["alias"])
        await safe_send(bot, config.GROUP_ID, f"⚖️ رأی‌گیری تموم شد. «{safe_alias}» با رأی جمع از شهر اخراج شد.")

        victim = get_player_by_id(eliminated["target_player_id"])
        if victim:
            await safe_send(bot, victim["user_id"], "⚖️ با رأی جمع از بازی حذف شدی.")

    conn.execute("UPDATE vote_sessions SET status = 'ended' WHERE id = ?", (session["id"],))
    conn.commit()

    await check_win_condition(bot, session["game_id"])


# ---------------------------------------------------------------
# شرط پایان بازی
# ---------------------------------------------------------------

async def check_win_condition(bot: Bot, game_id: int) -> None:
    game = get_game_by_id(game_id)
    if not game or game["status"] != "active":
        return

    alive = alive_players(game_id)
    killers = [p for p in alive if p["role"] == "killer"]
    others = [p for p in alive if p["role"] != "killer"]

    if len(killers) == 0:
        await end_game(bot, game, "شهروندان با موفقیت همه‌ی قاتل‌ها رو شناسایی و حذف کردن. 🎉 شهر برد!")
        return
    if len(killers) >= len(others):
        await end_game(bot, game, "قاتل‌ها به تعداد کافی از شهروندان رسیدن. 🔪 قاتل‌ها بردن!")
        return


async def end_game(bot: Bot, game: dict, result_text: str) -> None:
    conn = db.get_conn()
    conn.execute("UPDATE games SET status = 'ended', ended_at = ? WHERE id = ?", (db.now(), game["id"]))
    conn.commit()

    players = [dict(r) for r in conn.execute(
        "SELECT * FROM players WHERE game_id = ? ORDER BY id", (game["id"],)
    ).fetchall()]

    lines = [f"🏁 بازی تموم شد!\n{result_text}\n\nنقش‌ها:"]
    for p in players:
        if not p["alias"]:
            continue
        status = "🟢 زنده" if p["status"] == "alive" else "⚫️ حذف‌شده"
        safe_alias = html.escape(p["alias"])
        lines.append(f"• {safe_alias} — {roles.role_label(p['role'])} ({status})")
    await safe_send(bot, config.GROUP_ID, "\n".join(lines))

    for p in players:
        if not p["alias"]:
            continue
        keyboard = kb([[btn("🎭 خودم رو لو می‌دم", f"reveal_confirm_{p['id']}")]])
        await safe_send(
            bot, p["user_id"],
            f"بازی تموم شد! اگه دوست داری هویت واقعیت پشت اسم «{p['alias']}» رو به بقیه نشون بدی، "
            f"دکمه‌ی زیر رو بزن. کاملاً اختیاریه.",
            keyboard,
        )


async def reveal_identity(bot: Bot, player: dict) -> None:
    if player.get("revealed"):
        return
    conn = db.get_conn()
    conn.execute("UPDATE players SET revealed = 1 WHERE id = ?", (player["id"],))
    conn.commit()

    safe_alias = html.escape(player["alias"])
    mention = f'<a href="tg://user?id={int(player["user_id"])}">لینک پروفایل</a>'
    await safe_send(bot, config.GROUP_ID, f"🎭 پرده برداشته شد: «{safe_alias}» در واقع {mention} بود!")
