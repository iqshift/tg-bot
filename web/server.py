"""
web/server.py - خادم Flask للوحة التحكم الإدارية
"""
import os
import asyncio
import threading
import logging
import requests as http_requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from telegram import Update

import config
from data import database

try:
    from utils import server_utils
except ImportError as e:
    logger.error(f"❌ Failed to import server_utils: {e}")
    server_utils = None

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
    errors = database.get_errors(limit=100)
    settings_keys = [
        "welcome_msg", "help_msg", "msg_analyzing", "msg_routing",
        "msg_complete", "msg_error", "msg_banned", "msg_caption",
        "required_channels", "msg_force_sub", "share_msg", "share_btn_text",
    ]
    settings      = {k: database.get_setting(k) for k in settings_keys}
    channels_list = [c.strip() for c in (settings["required_channels"] or "").split(",") if c.strip()]
    whitelist = database.get_all_whitelist()
    return render_template(
        "dashboard.html",
        stats=stats,
        users=users,
        errors=errors,
        settings=settings,
        channels_list=channels_list,
        whitelist=whitelist,
        bot_token=config.TELEGRAM_TOKEN,
    )


@app.route("/errors/clear", methods=["POST"])
def clear_errors():
    database.clear_errors()
    flash("تم مسح سجل الأخطاء", "success")
    return redirect(url_for("dashboard") + "#errors-section")


# ─── دوال مساعدة للبروكسيات ──────────────────────────────────────────────────
_PROXY_TEST_URL = "https://httpbin.org/ip"
_PROXY_TIMEOUT  = 8


def _check_single_proxy(proxy: str) -> bool:
    """فحص بروكسي واحد - يُعيد True إذا كان يعمل."""
    p = proxy.strip()
    if not p.startswith(("http://", "https://", "socks4://", "socks5://")):
        p = "http://" + p
    try:
        r = http_requests.get(
            _PROXY_TEST_URL,
            proxies={"http": p, "https": p},
            timeout=_PROXY_TIMEOUT,
        )
        return r.status_code == 200
    except Exception:
        return False


def _check_proxies_list(proxies: list[str], max_workers: int = 50) -> dict:
    """فحص قائمة من البروكسيات وإعادة نتائجها."""
    working, dead = [], []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(proxies) or 1)) as pool:
        future_to_proxy = {pool.submit(_check_single_proxy, p): p for p in proxies}
        for fut in as_completed(future_to_proxy):
            proxy = future_to_proxy[fut]
            if fut.result():
                working.append(proxy)
            else:
                dead.append(proxy)
    return {"working": working, "dead": dead}


# ─── مسارات البروكسيات ───────────────────────────────────────────────────────
@app.route("/proxies/list")
def proxies_list():
    """إعادة القائمة الحالية من قاعدة البيانات."""
    proxies = database.get_proxies()
    return jsonify({"proxies": proxies, "count": len(proxies)})


@app.route("/proxies/check_current", methods=["POST"])
def proxies_check_current():
    """فحص البروكسيات الحالية وإزالة الميتة منها."""
    current = database.get_proxies()
    if not current:
        return jsonify({"ok": False, "msg": "القائمة فارغة"})
    results = _check_proxies_list(current)
    database.set_proxies(results["working"])
    return jsonify({
        "ok": True,
        "total":   len(current),
        "working": len(results["working"]),
        "dead":    len(results["dead"]),
        "working_list": results["working"],
    })


@app.route("/proxies/add_and_check", methods=["POST"])
def proxies_add_and_check():
    """استقبال قائمة بروكسيات جديدة، فحصها، ثم دمج الشاغلة مع الموجودة."""
    raw = request.form.get("new_proxies", "").strip()
    if not raw:
        return jsonify({"ok": False, "msg": "لم تُرسَل أي بروكسيات"})

    new_candidates = [l.strip() for l in raw.splitlines() if l.strip() and not l.startswith("#")]
    if not new_candidates:
        return jsonify({"ok": False, "msg": "لا توجد بروكسيات صالحة في النص"})

    results  = _check_proxies_list(new_candidates)
    current  = database.get_proxies()
    merged   = current + results["working"]
    database.set_proxies(merged)
    total    = len(database.get_proxies())

    return jsonify({
        "ok":          True,
        "checked":     len(new_candidates),
        "working":     len(results["working"]),
        "dead":        len(results["dead"]),
        "total_after": total,
        "working_list": results["working"],
    })


@app.route("/proxies/clear", methods=["POST"])
def proxies_clear():
    """مسح كل البروكسيات."""
    database.set_proxies([])
    return jsonify({"ok": True, "msg": "تم مسح قائمة البروكسيات"})



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
    database.ban_user(user_id, True)
    flash(f"تم حظر المستخدم {user_id}", "error")
    return redirect(url_for("dashboard"))


@app.route("/api/save_settings", methods=["POST"])
def api_save_settings():
    """حفظ الإعدادات العامة للبوت."""
    try:
        data = request.json
        if not data:
            return jsonify({"success": False, "error": "No data"}), 400

        # قائمة المفاتيح المسموح بتحديثها
        allowed_keys = [
            "welcome_msg", "help_msg", "msg_analyzing", "msg_routing",
            "msg_complete", "msg_error", "msg_banned", "msg_caption",
            "required_channels", "share_msg", "share_btn_text", "msg_force_sub",
            "telegram_token", "webhook_url"
        ]

        for key, val in data.items():
            if key in allowed_keys:
                database.set_setting(key, str(val))

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/unban_user/<int:user_id>", methods=["POST"])
def unban_user(user_id: int):
    database.ban_user(user_id, False)
    flash(f"تم رفع الحظر عن {user_id}", "success")
    return redirect(url_for("dashboard"))


@app.route("/update_settings", methods=["POST"])
def update_settings():
    for key in [
        "welcome_msg", "help_msg", "msg_analyzing", "msg_routing",
        "msg_complete", "msg_error", "msg_banned", "msg_caption",
        "required_channels", "msg_force_sub", "share_msg", "share_btn_text",
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
@app.route("/whitelist/add", methods=["POST"])
def add_to_whitelist():
    user_id      = request.form.get("user_id", "").strip()
    custom_reply = request.form.get("custom_reply", "").strip()
    if not user_id:
        flash("الرجاء إدخال معرف المستخدم", "error")
        return redirect(url_for("dashboard") + "#whitelist-section")
    
    try:
        database.add_to_whitelist(int(user_id), custom_reply)
        flash(f"تم إضافة {user_id} للقائمة البيضاء", "success")
    except ValueError:
        flash("معرف المستخدم يجب أن يكون رقماً", "error")
    
    return redirect(url_for("dashboard") + "#whitelist-section")


@app.route("/api/server_specs")
def api_server_specs():
    """إرجاع مواصفات الخادم (رام وتخزين)."""
    if not server_utils:
        return jsonify({"ram": "N/A", "storage": "N/A"})
    return jsonify(server_utils.get_server_specs())


@app.route("/api/speed_test", methods=["POST"])
def api_speed_test():
    """تشغيل اختبار سرعة الإنترنت وإرجاع النتائج."""
    if not server_utils:
        return jsonify({"download": "N/A", "upload": "N/A"})
    return jsonify(server_utils.get_internet_speed())
