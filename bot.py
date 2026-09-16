"""
نقطه‌ی ورود ربات «شهر مخفی».
با polling کار می‌کنه (نه webhook) — یعنی نیازی به دامنه یا ست‌کردن webhook نیست؛
کافیه اجراش کنی، خودش مدام از تلگرام می‌پرسه پیام جدید هست یا نه.
بستن خودکار رأی‌گیری‌های تموم‌شده هم با یه job دوره‌ای داخل همین پروسه انجام می‌شه
(معادل cron.php تو نسخه‌ی PHP) — نیازی به هیچ سرویس کرون جدا نیست.
"""
import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import game as game_module
import roles

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")


def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not config.is_admin(user_id):
            await update.effective_message.reply_text("این دستور فقط برای ادمین‌هاست.")
            return
        await func(update, context)
    return wrapper


# ---------------------------------------------------------------
# /start و ثبت‌نام
# ---------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    payload = context.args[0] if context.args else ""

    if payload.startswith("join_"):
        raw_id = payload[len("join_"):]
        game = game_module.get_game_by_id(int(raw_id)) if raw_id.isdigit() else None
        if not game:
            await update.effective_message.reply_text("این بازی دیگه معتبر نیست.")
            return
        await attempt_registration(update, context, game)
        return

    await update.effective_message.reply_text(
        'به ربات بازی «شهر مخفی» خوش اومدی! منتظر شروع دوره‌ی بعدی بازی باش.'
    )


async def attempt_registration(update: Update, context: ContextTypes.DEFAULT_TYPE, game: dict):
    user_id = update.effective_user.id
    res = await game_module.start_registration(context.bot, game, user_id)

    if res["ok"]:
        await update.effective_message.reply_text(res["message"])
        return

    if res["message"] == "membership_required":
        channel_username = str(config.CHANNEL_ID_RAW).lstrip("@")
        rows = [
            [game_module.url_btn("📢 عضویت در کانال", f"https://t.me/{channel_username}")],
            [game_module.btn("✅ عضو شدم، دوباره چک کن", f"join_check_{game['id']}")],
        ]
        await update.effective_message.reply_text(
            "برای ورود به بازی باید عضو کانال و گروه بازی باشی.",
            reply_markup=game_module.kb(rows),
        )
        return

    await update.effective_message.reply_text(res["message"])


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    game = game_module.get_open_game()
    if not game:
        await update.effective_message.reply_text("الان بازی فعالی وجود نداره.")
        return
    player = game_module.find_player(game["id"], user_id)
    if not player or not player["alias"]:
        await update.effective_message.reply_text("شما توی بازی جاری ثبت‌نام نکردی.")
        return
    if game["status"] != "active":
        await update.effective_message.reply_text("ثبت‌نامت کامله. منتظر شروع بازی توسط ادمین باش.")
        return
    await update.effective_message.reply_text("منوی بازی:", reply_markup=game_module.main_menu_keyboard(player))


# ---------------------------------------------------------------
# پیام‌های متنی معمولی (اسم مستعار / رله به کانال)
# ---------------------------------------------------------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = (update.effective_message.text or "").strip()

    game = game_module.get_open_game()
    if not game:
        await update.effective_message.reply_text("الان بازی فعالی وجود نداره.")
        return

    player = game_module.find_player(game["id"], user_id)
    if not player:
        await update.effective_message.reply_text("شما توی بازی جاری ثبت‌نام نکردی.")
        return

    if player["state"] == "awaiting_alias":
        res = game_module.save_alias(player, text)
        if not res["ok"]:
            await update.effective_message.reply_text(res["message"])
        else:
            await update.effective_message.reply_text(
                f"✅ ثبت‌نام کامل شد! اسم مستعارت: «{res['alias']}»\nمنتظر شروع بازی توسط ادمین باش."
            )
        return

    if game["status"] != "active":
        await update.effective_message.reply_text("بازی هنوز شروع نشده.")
        return

    res = await game_module.relay_to_channel(context.bot, player, text)
    if not res["ok"]:
        await update.effective_message.reply_text(res["message"])


async def handle_nontext(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # پیام غیرمتنی (عکس/فایل و ...) رو فعلاً نادیده می‌گیریم تا متادیتا لو نره
    await update.effective_message.reply_text("فعلاً فقط پیام متنی پشتیبانی می‌شه.")


# ---------------------------------------------------------------
# دستورات ادمین
# ---------------------------------------------------------------

@admin_only
async def cmd_newgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    existing = game_module.get_open_game()
    if existing:
        await update.effective_message.reply_text(
            f"یه بازی باز از قبل وجود داره (وضعیت: {existing['status']})."
        )
        return
    game = game_module.create_game()
    link = f"https://t.me/{config.BOT_USERNAME}?start=join_{game['id']}"
    rows = [[game_module.url_btn("🎮 ورود به بازی", link)]]
    await game_module.safe_send(
        context.bot, config.GROUP_ID,
        'یه دور جدید از بازی «شهر مخفی» باز شد! برای پیوستن دکمه‌ی زیر رو بزن.',
        game_module.kb(rows),
    )
    await update.effective_message.reply_text(
        f"بازی جدید ساخته شد (#{game['id']}) و لینک ثبت‌نام توی گروه پست شد."
    )


@admin_only
async def cmd_startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = game_module.get_open_game()
    if not game or game["status"] != "registering":
        await update.effective_message.reply_text("بازی‌ای در حال ثبت‌نام پیدا نشد.")
        return
    res = await game_module.start_game(context.bot, game)
    await update.effective_message.reply_text("بازی شروع شد." if res["ok"] else res["message"])


@admin_only
async def cmd_endgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = game_module.get_open_game()
    if not game:
        await update.effective_message.reply_text("بازی فعالی وجود نداره.")
        return
    await game_module.end_game(context.bot, game, "بازی توسط ادمین به‌صورت دستی پایان یافت.")
    await update.effective_message.reply_text("بازی پایان یافت.")


@admin_only
async def cmd_status_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = game_module.get_open_game()
    if not game:
        await update.effective_message.reply_text("بازی فعالی وجود نداره.")
        return
    alive = len(game_module.alive_players(game["id"]))
    dead = len(game_module.dead_players(game["id"]))
    await update.effective_message.reply_text(
        f"بازی #{game['id']} — وضعیت: {game['status']}\nزنده: {alive} | مرده: {dead}"
    )


# ---------------------------------------------------------------
# دکمه‌های شیشه‌ای
# ---------------------------------------------------------------

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    data = query.data or ""

    if data == "noop":
        await query.answer()
        return

    if data.startswith("join_check_"):
        raw_id = data[len("join_check_"):]
        game = game_module.get_game_by_id(int(raw_id)) if raw_id.isdigit() else None
        await query.answer()
        if game:
            await attempt_registration(update, context, game)
        return

    game = game_module.get_open_game()
    if not game:
        await query.answer("بازی فعالی وجود نداره.", show_alert=True)
        return

    player = game_module.find_player(game["id"], user_id)
    if not player:
        await query.answer("شما توی این بازی نیستی.", show_alert=True)
        return

    if data == "role_info":
        d = roles.role_definitions().get(player["role"])
        msg = f"{d['label']}\n{d['desc']}" if d else "نقشت هنوز مشخص نشده."
        await query.answer()
        await context.bot.send_message(chat_id=user_id, text=msg)
        return

    if data == "status":
        alive = len(game_module.alive_players(game["id"]))
        dead = len(game_module.dead_players(game["id"]))
        status_text = "🟢 زنده" if player["status"] == "alive" else "⚫️ حذف‌شده"
        await query.answer()
        await context.bot.send_message(
            chat_id=user_id, text=f"👥 زنده: {alive}\n💀 مرده: {dead}\nوضعیت خودت: {status_text}"
        )
        return

    if data == "list_alive":
        names = [f"• {p['alias']}" for p in game_module.alive_players(game["id"])]
        await query.answer()
        await context.bot.send_message(chat_id=user_id, text="بازیکنان زنده:\n" + "\n".join(names))
        return

    if data == "list_dead":
        players = game_module.dead_players(game["id"])
        await query.answer()
        if not players:
            await context.bot.send_message(chat_id=user_id, text="هنوز کسی کشته نشده.")
            return
        names = [f"• {p['alias']}" for p in players]
        await context.bot.send_message(chat_id=user_id, text="کشته‌شده‌ها:\n" + "\n".join(names))
        return

    if data == "action_start":
        d = roles.role_definitions().get(player["role"])
        if not d:
            await query.answer("نقشت هنوز مشخص نشده.", show_alert=True)
            return
        if d["action_type"] == "none":
            res = await game_module.perform_action(context.bot, game, player, None)
            await query.answer(res.get("message", ""), show_alert=not res["ok"])
            return
        await query.answer()
        keyboard = game_module.target_list_keyboard(game["id"], int(player["id"]), "action_target")
        await context.bot.send_message(chat_id=user_id, text="کی رو هدف می‌گیری؟", reply_markup=keyboard)
        return

    if data.startswith("action_target_"):
        target_id = int(data[len("action_target_"):])
        res = await game_module.perform_action(context.bot, game, player, target_id)
        await query.answer(res.get("message", ""), show_alert=not res["ok"])
        if res["ok"]:
            await context.bot.send_message(chat_id=user_id, text=res.get("message", "انجام شد."))
        return

    if data.startswith("vote_request_"):
        death_event_id = int(data[len("vote_request_"):])
        res = await game_module.request_vote(context.bot, game, player, death_event_id)
        await query.answer(res.get("message", "ثبت شد."), show_alert=not res["ok"])
        return

    if data.startswith("vote_cast_"):
        rest = data[len("vote_cast_"):]
        session_id_str, target_id_str = rest.split("_")
        res = game_module.cast_vote(game, player, int(session_id_str), int(target_id_str))
        await query.answer(res.get("message", ""), show_alert=not res["ok"])
        return

    if data.startswith("reveal_confirm_"):
        target_player_id = int(data[len("reveal_confirm_"):])
        if target_player_id != int(player["id"]):
            await query.answer("این دکمه مال تو نیست.", show_alert=True)
            return
        await game_module.reveal_identity(context.bot, player)
        await query.answer("هویتت فاش شد.")
        return

    await query.answer()


# ---------------------------------------------------------------
# جاب دوره‌ای — جایگزین cron.php
# ---------------------------------------------------------------

async def cron_job(context: ContextTypes.DEFAULT_TYPE):
    await game_module.resolve_expired_vote_sessions(context.bot)


def main():
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN تنظیم نشده — تو Railway از تب Variables اضافه‌ش کن.")
    if not config.GROUP_ID:
        log.warning("GROUP_ID تنظیم نشده؛ اعلان‌های گروهی ارسال نمی‌شن.")
    if not config.CHANNEL_ID:
        log.warning("CHANNEL_ID تنظیم نشده؛ چک عضویت کانال همیشه رد می‌شه.")

    application = ApplicationBuilder().token(config.BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("menu", cmd_menu, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("newgame", cmd_newgame, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("startgame", cmd_startgame, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("endgame", cmd_endgame, filters=filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("status_admin", cmd_status_admin, filters=filters.ChatType.PRIVATE))

    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND & ~filters.TEXT, handle_nontext)
    )
    application.add_handler(CallbackQueryHandler(handle_callback))

    application.job_queue.run_repeating(cron_job, interval=config.CRON_INTERVAL_SECONDS, first=10)

    log.info("ربات با polling شروع به کار کرد.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
