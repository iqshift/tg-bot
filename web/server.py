"""
web/server.py - خادم Flask للوحة التحكم الإدارية
"""
import os
import asyncio
import threading
import logging

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from telegram import Update

import config
from data import database

logger = logging.getLogger(__name__)

# ─── تهيئة Flask ─────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
app.secret_key = "ar_worm_ai_v3"

# ─── متغيرات مشتركة مع البوت ─────────────────────────────────────────────────
bot_app  = None
bot_loop = None


def run_flask() -> None:
    """تشغيل خادم Flask (غير مستخدم في Cloud Run)."""
    app.run(host="0.0.0.0", port=8080, debug=False, use_reloader=False)


# ─── Telegram Webhook ────────────────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    """استقبال التحديثات من Telegram ومعالجتها."""
    if bot_app is None or bot_loop is None:
        logger.warning("⚠️ Bot not ready yet")
        return "Bot not ready", 503
    update = Update.de_json(request.get_json(force=True), bot_app.bot)
    asyncio.run_coroutine_threadsafe(bot_app.process_update(update), bot_loop)
    return "OK", 200


# ─── المسارات ────────────────────────────────────────────────────────────────
@app.route("/")
def dashboard():
    stats = database.get_stats()
    users = database.get_all_users()
    settings_keys = [
        "welcome_msg", "help_msg", "msg_analyzing", "msg_routing",
        "msg_complete", "msg_error", "msg_banned", "msg_caption",
        "required_channels", "msg_force_sub",
    ]
    settings      = {k: database.get_setting(k) for k in settings_keys}
    channels_list = [c.strip() for c in (settings["required_channels"] or "").split(",") if c.strip()]
    return render_template(
        "dashboard.html",
        stats=stats,
        users=users,
        settings=settings,
        channels_list=channels_list,
        bot_token=config.TELEGRAM_TOKEN,
    )


@app.route("/chat/<int:user_id>")
def get_chat(user_id: int):
    user     = database.get_user(user_id)
    messages = database.get_user_messages(user_id)
    if not user:
        return "User not found", 404
    return render_template("chat.html", messages=messages, user=user, bot_token=config.TELEGRAM_TOKEN)


@app.route("/send_message/<int:user_id>", methods=["POST"])
def send_message(user_id: int):
    message = request.form.get("message", "").strip()
    if not message:
        return redirect(url_for("get_chat", user_id=user_id))

    async def _send():
        try:
            await bot_app.bot.send_message(chat_id=user_id, text=message)
            database.log_message(user_id, "bot", message)
        except Exception as exc:
            logger.error("فشل إرسال الرسالة إلى %s: %s", user_id, exc)

    if bot_loop:
        asyncio.run_coroutine_threadsafe(_send(), bot_loop)
    return redirect(url_for("get_chat", user_id=user_id))


@app.route("/send_private", methods=["POST"])
def send_private():
    user_id = request.form.get("user_id")
    message = request.form.get("message", "").strip()
    if not user_id or not message:
        flash("المعرف أو الرسالة فارغة", "error")
        return redirect(url_for("dashboard"))

    async def _send():
        try:
            await bot_app.bot.send_message(
                chat_id=user_id,
                text=f"📩 <b>رسالة خاصة:</b>\n\n{message}",
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.error("فشل إرسال رسالة خاصة إلى %s: %s", user_id, exc)

    if bot_loop:
        asyncio.run_coroutine_threadsafe(_send(), bot_loop)
        flash(f"تم إرسال الرسالة إلى {user_id}", "success")
    else:
        flash("البوت غير متصل", "error")
    return redirect(url_for("dashboard"))


@app.route("/ban_user/<int:user_id>", methods=["POST"])
def ban_user(user_id: int):
    database.set_ban_status(user_id, True)
    flash(f"تم حظر المستخدم {user_id}", "error")
    return redirect(url_for("dashboard"))


@app.route("/unban_user/<int:user_id>", methods=["POST"])
def unban_user(user_id: int):
    database.set_ban_status(user_id, False)
    flash(f"تم رفع الحظر عن {user_id}", "success")
    return redirect(url_for("dashboard"))


@app.route("/update_settings", methods=["POST"])
def update_settings():
    for key in [
        "welcome_msg", "help_msg", "msg_analyzing", "msg_routing",
        "msg_complete", "msg_error", "msg_banned", "msg_caption",
        "required_channels", "msg_force_sub",
    ]:
        value = request.form.get(key)
        if value is not None:
            database.set_setting(key, value)
    flash("تم تحديث الإعدادات بنجاح!", "success")
    return redirect(url_for("dashboard"))


@app.route("/add_channel", methods=["POST"])
def add_channel():
    new_channel = request.form.get("channel_name", "").strip()
    if not new_channel:
        flash("الرجاء إدخال معرف القناة", "error")
        return redirect(url_for("dashboard"))
    if not new_channel.startswith("@"):
        new_channel = "@" + new_channel
    current_list = [c.strip() for c in database.get_setting("required_channels", "").split(",") if c.strip()]
    if new_channel in current_list:
        flash("القناة موجودة بالفعل", "error")
    else:
        current_list.append(new_channel)
        database.set_setting("required_channels", ",".join(current_list))
        flash(f"تم إضافة القناة {new_channel}", "success")
    return redirect(url_for("dashboard"))


@app.route("/delete_channel", methods=["POST"])
def delete_channel():
    channel = request.form.get("channel_name", "").strip()
    current_list = [c.strip() for c in database.get_setting("required_channels", "").split(",") if c.strip()]
    if channel in current_list:
        current_list.remove(channel)
        database.set_setting("required_channels", ",".join(current_list))
        flash(f"تم حذف القناة {channel}", "success")
    else:
        flash("القناة غير موجودة", "error")
    return redirect(url_for("dashboard"))


@app.route("/broadcast", methods=["POST"])
def broadcast():
    message = request.form.get("message", "").strip()
    title   = request.form.get("title", "").strip()
    if not message:
        flash("الرسالة فارغة", "error")
        return redirect(url_for("dashboard"))

    users = database.get_all_users()

    async def _send_all():
        count = 0
        header = f"📢 <b>{title}</b>\n\n" if title else "📢 <b>تنبيه عام:</b>\n\n"
        for user in users:
            try:
                await bot_app.bot.send_message(
                    chat_id=user["user_id"],
                    text=header + message,
                    parse_mode="HTML",
                )
                count += 1
            except Exception:
                pass
        logger.info("تم إرسال البث إلى %d مستخدم", count)

    if bot_loop:
        asyncio.run_coroutine_threadsafe(_send_all(), bot_loop)
        flash("تم جدولة الإرسال للجميع", "success")
    else:
        flash("البوت غير متصل", "error")
    return redirect(url_for("dashboard"))
