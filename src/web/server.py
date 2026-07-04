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

logger = logging.getLogger(__name__)

try:
    from utils import server_utils
except ImportError as e:
    logger.error(f"❌ Failed to import server_utils: {e}")
    server_utils = None

# ─── تهيئة Flask ─────────────────────────────────────────────────────────────
app = Flask(__name__)
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
    """استقبال التحديثات من Telegram ومعالجتها مع نظام مراقبة."""
    try:
        data = request.get_json(force=True)
        if not data:
            return "Empty", 400
            
        update_id = data.get("update_id", "???")
        logger.info(f"📥 Incoming Hook: Update ID {update_id}")

        if bot_app is None or bot_loop is None:
            logger.warning(f"⚠️ Bot not ready for Update {update_id}")
            return "Bot not ready", 503
            
        update = Update.de_json(data, bot_app.bot)
        # إرسال التحديث للمعالجة في خيط البوت
        asyncio.run_coroutine_threadsafe(bot_app.process_update(update), bot_loop)
        return "OK", 200
    except Exception as e:
        logger.error(f"❌ Webhook Error: {e}")
        return "Error", 500


# ─── المسارات ────────────────────────────────────────────────────────────────
@app.route("/api/user_photo/<file_id>")
def proxy_user_photo(file_id):
    """بروكسي لجلب صورة المستخدم من تليجرام وحل مشكلة انتهاء الروابط."""
    try:
        if not bot_app or not bot_app.bot:
            return "Bot not active", 503
        
        # جلب رابط الملف المتجدد باستخدام المعرف
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        f = loop.run_until_complete(bot_app.bot.get_file(file_id))
        
        # إعادة توجيه المتصفح للرابط الفعلي المتجدد
        return redirect(f.file_path)
    except Exception as e:
        logger.error(f"Error proxying photo {file_id}: {e}")
        return "Not found", 404


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
    settings = {k: database.get_setting(k) for k in settings_keys}
    
    # جلب التوكن والويب هوك من الملفات النصية كأولوية (بناءً على طلبك)
    settings["telegram_token"] = config._read_secret(config.TELEGRAM_TOKEN_FILE, env_key="TELEGRAM_TOKEN")
    settings["webhook_url"]    = config._read_secret(config.WEBHOOK_URL_FILE, env_key="WEBHOOK_URL")

    channels_list = [c.strip() for c in (settings["required_channels"] or "").split(",") if c.strip()]
    whitelist = database.get_all_whitelist()
    
    # جلب الاستهلاك الفعلي لليوم
    usage_today = database.get_usage_today()
    
    # تفاصيل الخطة المجانية لـ Firestore (Firebase Free Tier)
    cloud_limits = {
        "reads_daily": "50,000",
        "writes_daily": "20,000",
        "deletes_daily": "20,000",
        "storage_free": "1 GiB",
        "network_free": "10 GiB/month",
        "reads_used": usage_today.get("reads", 0),
        "writes_used": usage_today.get("writes", 0),
        "deletes_used": usage_today.get("deletes", 0),
    }

    return render_template(
        "dashboard.html",
        stats=stats,
        users=users,
        errors=errors,
        settings=settings,
        channels_list=channels_list,
        whitelist=whitelist,
        cloud_limits=cloud_limits
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
    """حفظ الإعدادات العامة للبوت في الملفات النصية و Firestore."""
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

        token_changed = False
        for key, val in data.items():
            if key in allowed_keys:
                # 1. الحفظ في قاعدة البيانات (لضمان المزامنة)
                database.set_setting(key, str(val))
                
                # 2. الحفظ في ملفات نصية (بناءً على طلب المستخدم)
                if key == "telegram_token":
                    config._write_secret(config.TELEGRAM_TOKEN_FILE, str(val))
                    token_changed = True
                elif key == "webhook_url":
                    config._write_secret(config.WEBHOOK_URL_FILE, str(val))

        # 3. تفعيل "إعادة التشغيل السريع" إذا تغير التوكن
        if token_changed and hasattr(app, 'trigger_bot_restart'):
            logger.info("⚡ Token changed! Signaling hot reload...")
            app.trigger_bot_restart()

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
@app.route("/api/activate_webhook", methods=["POST"])
def api_activate_webhook():
    """تفعيل الويب-هوك من تليجرام باستخدام التوكن والويب-هوك المخزن."""
    try:
        token = database.get_setting("telegram_token", config.TELEGRAM_TOKEN)
        url   = database.get_setting("webhook_url", config.WEBHOOK_URL)

        if not token or not url:
            return jsonify({"success": False, "error": "Token or Webhook URL missing"}), 400

        # تنظيف الرابط لضمان عدم التكرار (نفس منطق main.py)
        base_url = url.strip().rstrip("/")
        if base_url.endswith("/webhook"):
            base_url = base_url[:-8].rstrip("/")
            
        clean_url = base_url + "/webhook"
        tg_api_url = f"https://api.telegram.org/bot{token}/setWebhook?url={clean_url}"
        
        response = http_requests.get(tg_api_url, timeout=10)
        data = response.json()
        
        if data.get("ok"):
            return jsonify({"success": True, "data": data})
        else:
            return jsonify({"success": False, "error": data.get("description", "Unknown error"), "data": data})
            
    except Exception as e:
        logger.error(f"Error activating webhook: {e}")
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


# ─── مسارات إدارة كوكيز إنستغرام ──────────────────────────────────────────────

def _write_cookie_file(cookies_list: list) -> None:
    """كتابة الكوكيز النشطة بتنسيق Netscape في ملفات الإعدادات للبوت."""
    import urllib.parse
    lines = ["# Netscape HTTP Cookie File", "# Generated from dashboard active account", ""]
    for c in cookies_list:
        domain = c.get("domain", ".instagram.com")
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        path   = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        expiry = int(c.get("expirationDate", 0))
        name   = c["name"]
        value  = urllib.parse.unquote(c["value"])
        
        line = f"{domain}\t{include_subdomains}\t{path}\t{secure}\t{expiry}\t{name}\t{value}"
        lines.append(line)
        
    content = "\n".join(lines) + "\n"
    
    # 1. الكتابة في مسار config الرئيسي
    os.makedirs(os.path.dirname(config.INSTAGRAM_COOKIES), exist_ok=True)
    with open(config.INSTAGRAM_COOKIES, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
        
    # 2. الكتابة في مسار secrets كاحتياط
    secrets_path = os.path.join(config.SECRETS_DIR, "instagram_cookies.txt")
    os.makedirs(os.path.dirname(secrets_path), exist_ok=True)
    with open(secrets_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    logger.info("🍪 Netscape cookies file updated successfully.")


def _verify_single_ig_cookie(cookies_list: list) -> tuple[str, str]:
    """فحص صلاحية الكوكيز عبر استدعاء API إنستغرام. يُرجع (username, status)."""
    try:
        cookies_dict = {}
        for c in cookies_list:
            cookies_dict[c["name"]] = urllib.parse.unquote(c["value"])
            
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "X-IG-App-ID": "936619743392459",
            "X-Requested-With": "XMLHttpRequest",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        url_check = "https://www.instagram.com/api/v1/accounts/edit/web_current_user/"
        r = http_requests.get(url_check, cookies=cookies_dict, headers=headers, timeout=10)
        
        if r.status_code == 200:
            data = r.json()
            username = data.get("form_data", {}).get("username")
            if not username:
                username = cookies_dict.get("ds_user_id", "unknown_user")
            return username, "working"
        else:
            username = cookies_dict.get("ds_user_id", "unknown_user")
            return username, "expired"
    except Exception as e:
        logger.error(f"Error verifying IG cookie: {e}")
        # إذا تعذر الاتصال، نستخدم ds_user_id أو اسم افتراضي مع حفظ الحالة كـ expired
        return "unknown", "expired"


@app.route("/ig_cookies/list")
def ig_cookies_list():
    """إرجاع قائمة حسابات الكوكيز المضافة."""
    cookies = database.get_ig_cookies()
    # تنظيف مخرج الـ JSON لعدم إرسال الكوكيز الكاملة للمتصفح لدواعي الأمن (نرسل فقط معلومات الحساب)
    cleaned = []
    for c in cookies:
        cleaned.append({
            "username": c.get("username", "unknown"),
            "status": c.get("status", "expired"),
            "is_active": c.get("is_active", False),
            "last_checked": c.get("last_checked", "")
        })
    return jsonify({"cookies": cleaned, "count": len(cleaned)})


@app.route("/ig_cookies/add", methods=["POST"])
def ig_cookies_add():
    """إضافة كوكيز حساب جديد وفحصه."""
    import json
    raw_json = request.form.get("cookies_json", "").strip()
    if not raw_json:
        return jsonify({"ok": False, "msg": "الرجاء لصق كود الكوكيز (JSON)"})
        
    try:
        cookies_list = json.loads(raw_json)
        if not isinstance(cookies_list, list):
             return jsonify({"ok": False, "msg": "تنسيق JSON غير صالح. يجب أن يكون قائمة من الكوكيز."})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"خطأ في تحليل JSON: {e}"})
        
    # فحص الكوكيز
    username, status = _verify_single_ig_cookie(cookies_list)
    
    # إذا كانت القائمة فارغة حالياً، نجعل هذا الحساب نشطاً تلقائياً
    current = database.get_ig_cookies()
    make_active = (len(current) == 0 or status == "working")
    
    # حفظ في قاعدة البيانات
    database.add_ig_cookie(username, cookies_list, status=status, is_active=make_active)
    
    # إذا تم تنشيطه، حدّث الملف الفعلي
    if make_active:
        _write_cookie_file(cookies_list)
        
    return jsonify({
        "ok": True,
        "username": username,
        "status": status,
        "is_active": make_active,
        "msg": f"تمت إضافة الحساب @{username} بنجاح. حالة الحساب: {status}"
    })


@app.route("/ig_cookies/activate", methods=["POST"])
def ig_cookies_activate():
    """تفعيل حساب كوكيز معين."""
    username = request.form.get("username", "").strip()
    if not username:
        return jsonify({"ok": False, "msg": "اسم المستخدم مطلوب"})
        
    cookies = database.get_ig_cookies()
    target = None
    for c in cookies:
        if c.get("username") == username:
            target = c
            break
            
    if not target:
        return jsonify({"ok": False, "msg": "الحساب غير موجود"})
        
    # تعيين كنشط في قاعدة البيانات
    database.set_active_ig_cookie(username)
    
    # كتابة الملف
    _write_cookie_file(target["cookies"])
    
    return jsonify({"ok": True, "msg": f"تم تفعيل الحساب @{username} كحساب رئيسي للبوت"})


@app.route("/ig_cookies/delete", methods=["POST"])
def ig_cookies_delete():
    """حذف حساب كوكيز."""
    username = request.form.get("username", "").strip()
    if not username:
        return jsonify({"ok": False, "msg": "اسم المستخدم مطلوب"})
        
    database.delete_ig_cookie(username)
    return jsonify({"ok": True, "msg": f"تم حذف الحساب @{username} بنجاح"})


@app.route("/ig_cookies/check_all", methods=["POST"])
def ig_cookies_check_all():
    """فحص وتحديث حالة جميع حسابات الكوكيز المضافة."""
    cookies = database.get_ig_cookies()
    if not cookies:
        return jsonify({"ok": False, "msg": "لا توجد حسابات لفحصها"})
        
    checked = 0
    working = 0
    expired = 0
    
    for c in cookies:
        username = c.get("username")
        cookies_list = c.get("cookies", [])
        if username and cookies_list:
            _, status = _verify_single_ig_cookie(cookies_list)
            database.update_ig_cookie_status(username, status)
            checked += 1
            if status == "working":
                working += 1
            else:
                expired += 1
                
    return jsonify({
        "ok": True,
        "checked": checked,
        "working": working,
        "expired": expired,
        "msg": f"تم فحص {checked} حساب. النشطة: {working}، المنتهية: {expired}"
    })

