"""
web/server.py - ط®ط§ط¯ظ… Flask ظ„ظ„ظˆط­ط© ط§ظ„طھط­ظƒظ… ط§ظ„ط¥ط¯ط§ط±ظٹط©
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
    logger.error(f"â‌Œ Failed to import server_utils: {e}")
    server_utils = None

# â”€â”€â”€ طھظ‡ظٹط¦ط© Flask â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
app = Flask(__name__)
app.secret_key = "ar_worm_ai_v3"

# â”€â”€â”€ ظ…طھط؛ظٹط±ط§طھ ظ…ط´طھط±ظƒط© ظ…ط¹ ط§ظ„ط¨ظˆطھ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
bot_app  = None
bot_loop = None


def run_flask() -> None:
    """طھط´ط؛ظٹظ„ ط®ط§ط¯ظ… Flask (ط؛ظٹط± ظ…ط³طھط®ط¯ظ… ظپظٹ Cloud Run)."""
    app.run(host="0.0.0.0", port=8080, debug=False, use_reloader=False)


# â”€â”€â”€ Telegram Webhook â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route("/webhook", methods=["POST"])
def telegram_webhook():
    """ط§ط³طھظ‚ط¨ط§ظ„ ط§ظ„طھط­ط¯ظٹط«ط§طھ ظ…ظ† Telegram ظˆظ…ط¹ط§ظ„ط¬طھظ‡ط§ ظ…ط¹ ظ†ط¸ط§ظ… ظ…ط±ط§ظ‚ط¨ط©."""
    try:
        data = request.get_json(force=True)
        if not data:
            return "Empty", 400
            
        update_id = data.get("update_id", "???")
        logger.info(f"ًں“¥ Incoming Hook: Update ID {update_id}")

        if bot_app is None or bot_loop is None:
            logger.warning(f"âڑ ï¸ڈ Bot not ready for Update {update_id}")
            return "Bot not ready", 503
            
        update = Update.de_json(data, bot_app.bot)
        # ط¥ط±ط³ط§ظ„ ط§ظ„طھط­ط¯ظٹط« ظ„ظ„ظ…ط¹ط§ظ„ط¬ط© ظپظٹ ط®ظٹط· ط§ظ„ط¨ظˆطھ
        asyncio.run_coroutine_threadsafe(bot_app.process_update(update), bot_loop)
        return "OK", 200
    except Exception as e:
        logger.error(f"â‌Œ Webhook Error: {e}")
        return "Error", 500


# â”€â”€â”€ ط§ظ„ظ…ط³ط§ط±ط§طھ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route("/api/user_photo/<file_id>")
def proxy_user_photo(file_id):
    """ط¨ط±ظˆظƒط³ظٹ ظ„ط¬ظ„ط¨ طµظˆط±ط© ط§ظ„ظ…ط³طھط®ط¯ظ… ظ…ظ† طھظ„ظٹط¬ط±ط§ظ… ظˆط­ظ„ ظ…ط´ظƒظ„ط© ط§ظ†طھظ‡ط§ط، ط§ظ„ط±ظˆط§ط¨ط·."""
    try:
        if not bot_app or not bot_app.bot:
            return "Bot not active", 503
        
        # ط¬ظ„ط¨ ط±ط§ط¨ط· ط§ظ„ظ…ظ„ظپ ط§ظ„ظ…طھط¬ط¯ط¯ ط¨ط§ط³طھط®ط¯ط§ظ… ط§ظ„ظ…ط¹ط±ظپ
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        f = loop.run_until_complete(bot_app.bot.get_file(file_id))
        
        # ط¥ط¹ط§ط¯ط© طھظˆط¬ظٹظ‡ ط§ظ„ظ…طھطµظپط­ ظ„ظ„ط±ط§ط¨ط· ط§ظ„ظپط¹ظ„ظٹ ط§ظ„ظ…طھط¬ط¯ط¯
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
    
    # ط¬ظ„ط¨ ط§ظ„طھظˆظƒظ† ظˆط§ظ„ظˆظٹط¨ ظ‡ظˆظƒ ظ…ظ† ط§ظ„ظ…ظ„ظپط§طھ ط§ظ„ظ†طµظٹط© ظƒط£ظˆظ„ظˆظٹط© (ط¨ظ†ط§ط،ظ‹ ط¹ظ„ظ‰ ط·ظ„ط¨ظƒ)
    settings["telegram_token"] = config._read_secret(config.TELEGRAM_TOKEN_FILE, env_key="TELEGRAM_TOKEN")
    settings["webhook_url"]    = config._read_secret(config.WEBHOOK_URL_FILE, env_key="WEBHOOK_URL")

    channels_list = [c.strip() for c in (settings["required_channels"] or "").split(",") if c.strip()]
    whitelist = database.get_all_whitelist()
    
    # ط¬ظ„ط¨ ط§ظ„ط§ط³طھظ‡ظ„ط§ظƒ ط§ظ„ظپط¹ظ„ظٹ ظ„ظ„ظٹظˆظ…
    usage_today = database.get_usage_today()
    
    # طھظپط§طµظٹظ„ ط§ظ„ط®ط·ط© ط§ظ„ظ…ط¬ط§ظ†ظٹط© ظ„ظ€ Firestore (Firebase Free Tier)
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
    flash("طھظ… ظ…ط³ط­ ط³ط¬ظ„ ط§ظ„ط£ط®ط·ط§ط،", "success")
    return redirect(url_for("dashboard") + "#errors-section")


# â”€â”€â”€ ط¯ظˆط§ظ„ ظ…ط³ط§ط¹ط¯ط© ظ„ظ„ط¨ط±ظˆظƒط³ظٹط§طھ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_PROXY_TEST_URL = "https://httpbin.org/ip"
_PROXY_TIMEOUT  = 8


def _check_single_proxy(proxy: str) -> bool:
    """ظپط­طµ ط¨ط±ظˆظƒط³ظٹ ظˆط§ط­ط¯ - ظٹظڈط¹ظٹط¯ True ط¥ط°ط§ ظƒط§ظ† ظٹط¹ظ…ظ„."""
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
    """ظپط­طµ ظ‚ط§ط¦ظ…ط© ظ…ظ† ط§ظ„ط¨ط±ظˆظƒط³ظٹط§طھ ظˆط¥ط¹ط§ط¯ط© ظ†طھط§ط¦ط¬ظ‡ط§."""
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


# â”€â”€â”€ ظ…ط³ط§ط±ط§طھ ط§ظ„ط¨ط±ظˆظƒط³ظٹط§طھ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@app.route("/proxies/list")
def proxies_list():
    """ط¥ط¹ط§ط¯ط© ط§ظ„ظ‚ط§ط¦ظ…ط© ط§ظ„ط­ط§ظ„ظٹط© ظ…ظ† ظ‚ط§ط¹ط¯ط© ط§ظ„ط¨ظٹط§ظ†ط§طھ."""
    proxies = database.get_proxies()
    return jsonify({"proxies": proxies, "count": len(proxies)})


@app.route("/proxies/check_current", methods=["POST"])
def proxies_check_current():
    """ظپط­طµ ط§ظ„ط¨ط±ظˆظƒط³ظٹط§طھ ط§ظ„ط­ط§ظ„ظٹط© ظˆط¥ط²ط§ظ„ط© ط§ظ„ظ…ظٹطھط© ظ…ظ†ظ‡ط§."""
    current = database.get_proxies()
    if not current:
        return jsonify({"ok": False, "msg": "ط§ظ„ظ‚ط§ط¦ظ…ط© ظپط§ط±ط؛ط©"})
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
    """ط§ط³طھظ‚ط¨ط§ظ„ ظ‚ط§ط¦ظ…ط© ط¨ط±ظˆظƒط³ظٹط§طھ ط¬ط¯ظٹط¯ط©طŒ ظپط­طµظ‡ط§طŒ ط«ظ… ط¯ظ…ط¬ ط§ظ„ط´ط§ط؛ظ„ط© ظ…ط¹ ط§ظ„ظ…ظˆط¬ظˆط¯ط©."""
    raw = request.form.get("new_proxies", "").strip()
    if not raw:
        return jsonify({"ok": False, "msg": "ظ„ظ… طھظڈط±ط³ظژظ„ ط£ظٹ ط¨ط±ظˆظƒط³ظٹط§طھ"})

    new_candidates = [l.strip() for l in raw.splitlines() if l.strip() and not l.startswith("#")]
    if not new_candidates:
        return jsonify({"ok": False, "msg": "ظ„ط§ طھظˆط¬ط¯ ط¨ط±ظˆظƒط³ظٹط§طھ طµط§ظ„ط­ط© ظپظٹ ط§ظ„ظ†طµ"})

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
    """ظ…ط³ط­ ظƒظ„ ط§ظ„ط¨ط±ظˆظƒط³ظٹط§طھ."""
    database.set_proxies([])
    return jsonify({"ok": True, "msg": "طھظ… ظ…ط³ط­ ظ‚ط§ط¦ظ…ط© ط§ظ„ط¨ط±ظˆظƒط³ظٹط§طھ"})



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
            logger.error("ظپط´ظ„ ط¥ط±ط³ط§ظ„ ط§ظ„ط±ط³ط§ظ„ط© ط¥ظ„ظ‰ %s: %s", user_id, exc)

    if bot_loop:
        asyncio.run_coroutine_threadsafe(_send(), bot_loop)
    return redirect(url_for("get_chat", user_id=user_id))


@app.route("/send_private", methods=["POST"])
def send_private():
    user_id = request.form.get("user_id")
    message = request.form.get("message", "").strip()
    if not user_id or not message:
        flash("ط§ظ„ظ…ط¹ط±ظپ ط£ظˆ ط§ظ„ط±ط³ط§ظ„ط© ظپط§ط±ط؛ط©", "error")
        return redirect(url_for("dashboard"))

    async def _send():
        try:
            await bot_app.bot.send_message(
                chat_id=user_id,
                text=f"ًں“© <b>ط±ط³ط§ظ„ط© ط®ط§طµط©:</b>\n\n{message}",
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.error("ظپط´ظ„ ط¥ط±ط³ط§ظ„ ط±ط³ط§ظ„ط© ط®ط§طµط© ط¥ظ„ظ‰ %s: %s", user_id, exc)

    if bot_loop:
        asyncio.run_coroutine_threadsafe(_send(), bot_loop)
        flash(f"طھظ… ط¥ط±ط³ط§ظ„ ط§ظ„ط±ط³ط§ظ„ط© ط¥ظ„ظ‰ {user_id}", "success")
    else:
        flash("ط§ظ„ط¨ظˆطھ ط؛ظٹط± ظ…طھطµظ„", "error")
    return redirect(url_for("dashboard"))


@app.route("/ban_user/<int:user_id>", methods=["POST"])
def ban_user(user_id: int):
    database.ban_user(user_id, True)
    flash(f"طھظ… ط­ط¸ط± ط§ظ„ظ…ط³طھط®ط¯ظ… {user_id}", "error")
    return redirect(url_for("dashboard"))


@app.route("/api/save_settings", methods=["POST"])
def api_save_settings():
    """ط­ظپط¸ ط§ظ„ط¥ط¹ط¯ط§ط¯ط§طھ ط§ظ„ط¹ط§ظ…ط© ظ„ظ„ط¨ظˆطھ ظپظٹ ط§ظ„ظ…ظ„ظپط§طھ ط§ظ„ظ†طµظٹط© ظˆ Firestore."""
    try:
        data = request.json
        if not data:
            return jsonify({"success": False, "error": "No data"}), 400

        # ظ‚ط§ط¦ظ…ط© ط§ظ„ظ…ظپط§طھظٹط­ ط§ظ„ظ…ط³ظ…ظˆط­ ط¨طھط­ط¯ظٹط«ظ‡ط§
        allowed_keys = [
            "welcome_msg", "help_msg", "msg_analyzing", "msg_routing",
            "msg_complete", "msg_error", "msg_banned", "msg_caption",
            "required_channels", "share_msg", "share_btn_text", "msg_force_sub",
            "telegram_token", "webhook_url"
        ]

        token_changed = False
        for key, val in data.items():
            if key in allowed_keys:
                # 1. ط§ظ„ط­ظپط¸ ظپظٹ ظ‚ط§ط¹ط¯ط© ط§ظ„ط¨ظٹط§ظ†ط§طھ (ظ„ط¶ظ…ط§ظ† ط§ظ„ظ…ط²ط§ظ…ظ†ط©)
                database.set_setting(key, str(val))
                
                # 2. ط§ظ„ط­ظپط¸ ظپظٹ ظ…ظ„ظپط§طھ ظ†طµظٹط© (ط¨ظ†ط§ط،ظ‹ ط¹ظ„ظ‰ ط·ظ„ط¨ ط§ظ„ظ…ط³طھط®ط¯ظ…)
                if key == "telegram_token":
                    config._write_secret(config.TELEGRAM_TOKEN_FILE, str(val))
                    token_changed = True
                elif key == "webhook_url":
                    config._write_secret(config.WEBHOOK_URL_FILE, str(val))

        # 3. طھظپط¹ظٹظ„ "ط¥ط¹ط§ط¯ط© ط§ظ„طھط´ط؛ظٹظ„ ط§ظ„ط³ط±ظٹط¹" ط¥ط°ط§ طھط؛ظٹط± ط§ظ„طھظˆظƒظ†
        if token_changed and hasattr(app, 'trigger_bot_restart'):
            logger.info("âڑ، Token changed! Signaling hot reload...")
            app.trigger_bot_restart()

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
@app.route("/api/activate_webhook", methods=["POST"])
def api_activate_webhook():
    """طھظپط¹ظٹظ„ ط§ظ„ظˆظٹط¨-ظ‡ظˆظƒ ظ…ظ† طھظ„ظٹط¬ط±ط§ظ… ط¨ط§ط³طھط®ط¯ط§ظ… ط§ظ„طھظˆظƒظ† ظˆط§ظ„ظˆظٹط¨-ظ‡ظˆظƒ ط§ظ„ظ…ط®ط²ظ†."""
    try:
        token = database.get_setting("telegram_token", config.TELEGRAM_TOKEN)
        url   = database.get_setting("webhook_url", config.WEBHOOK_URL)

        if not token or not url:
            return jsonify({"success": False, "error": "Token or Webhook URL missing"}), 400

        # طھظ†ط¸ظٹظپ ط§ظ„ط±ط§ط¨ط· ظ„ط¶ظ…ط§ظ† ط¹ط¯ظ… ط§ظ„طھظƒط±ط§ط± (ظ†ظپط³ ظ…ظ†ط·ظ‚ main.py)
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
    flash(f"طھظ… ط±ظپط¹ ط§ظ„ط­ط¸ط± ط¹ظ† {user_id}", "success")
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
    flash("طھظ… طھط­ط¯ظٹط« ط§ظ„ط¥ط¹ط¯ط§ط¯ط§طھ ط¨ظ†ط¬ط§ط­!", "success")
    return redirect(url_for("dashboard"))


@app.route("/add_channel", methods=["POST"])
def add_channel():
    new_channel = request.form.get("channel_name", "").strip()
    if not new_channel:
        flash("ط§ظ„ط±ط¬ط§ط، ط¥ط¯ط®ط§ظ„ ظ…ط¹ط±ظپ ط§ظ„ظ‚ظ†ط§ط©", "error")
        return redirect(url_for("dashboard"))
    if not new_channel.startswith("@"):
        new_channel = "@" + new_channel
    current_list = [c.strip() for c in database.get_setting("required_channels", "").split(",") if c.strip()]
    if new_channel in current_list:
        flash("ط§ظ„ظ‚ظ†ط§ط© ظ…ظˆط¬ظˆط¯ط© ط¨ط§ظ„ظپط¹ظ„", "error")
    else:
        current_list.append(new_channel)
        database.set_setting("required_channels", ",".join(current_list))
        flash(f"طھظ… ط¥ط¶ط§ظپط© ط§ظ„ظ‚ظ†ط§ط© {new_channel}", "success")
    return redirect(url_for("dashboard"))


@app.route("/delete_channel", methods=["POST"])
def delete_channel():
    channel = request.form.get("channel_name", "").strip()
    current_list = [c.strip() for c in database.get_setting("required_channels", "").split(",") if c.strip()]
    if channel in current_list:
        current_list.remove(channel)
        database.set_setting("required_channels", ",".join(current_list))
        flash(f"طھظ… ط­ط°ظپ ط§ظ„ظ‚ظ†ط§ط© {channel}", "success")
    else:
        flash("ط§ظ„ظ‚ظ†ط§ط© ط؛ظٹط± ظ…ظˆط¬ظˆط¯ط©", "error")
    return redirect(url_for("dashboard"))


@app.route("/broadcast", methods=["POST"])
def broadcast():
    message = request.form.get("message", "").strip()
    title   = request.form.get("title", "").strip()
    if not message:
        flash("ط§ظ„ط±ط³ط§ظ„ط© ظپط§ط±ط؛ط©", "error")
        return redirect(url_for("dashboard"))

    users = database.get_all_users()

    async def _send_all():
        count = 0
        header = f"ًں“¢ <b>{title}</b>\n\n" if title else "ًں“¢ <b>طھظ†ط¨ظٹظ‡ ط¹ط§ظ…:</b>\n\n"
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
        logger.info("طھظ… ط¥ط±ط³ط§ظ„ ط§ظ„ط¨ط« ط¥ظ„ظ‰ %d ظ…ط³طھط®ط¯ظ…", count)

    if bot_loop:
        asyncio.run_coroutine_threadsafe(_send_all(), bot_loop)
        flash("طھظ… ط¬ط¯ظˆظ„ط© ط§ظ„ط¥ط±ط³ط§ظ„ ظ„ظ„ط¬ظ…ظٹط¹", "success")
    else:
        flash("ط§ظ„ط¨ظˆطھ ط؛ظٹط± ظ…طھطµظ„", "error")
    return redirect(url_for("dashboard"))
@app.route("/whitelist/add", methods=["POST"])
def add_to_whitelist():
    user_id      = request.form.get("user_id", "").strip()
    custom_reply = request.form.get("custom_reply", "").strip()
    if not user_id:
        flash("ط§ظ„ط±ط¬ط§ط، ط¥ط¯ط®ط§ظ„ ظ…ط¹ط±ظپ ط§ظ„ظ…ط³طھط®ط¯ظ…", "error")
        return redirect(url_for("dashboard") + "#whitelist-section")
    
    try:
        database.add_to_whitelist(int(user_id), custom_reply)
        flash(f"طھظ… ط¥ط¶ط§ظپط© {user_id} ظ„ظ„ظ‚ط§ط¦ظ…ط© ط§ظ„ط¨ظٹط¶ط§ط،", "success")
    except ValueError:
        flash("ظ…ط¹ط±ظپ ط§ظ„ظ…ط³طھط®ط¯ظ… ظٹط¬ط¨ ط£ظ† ظٹظƒظˆظ† ط±ظ‚ظ…ط§ظ‹", "error")
    
    return redirect(url_for("dashboard") + "#whitelist-section")


@app.route("/api/server_specs")
def api_server_specs():
    """ط¥ط±ط¬ط§ط¹ ظ…ظˆط§طµظپط§طھ ط§ظ„ط®ط§ط¯ظ… (ط±ط§ظ… ظˆطھط®ط²ظٹظ†)."""
    if not server_utils:
        return jsonify({"ram": "N/A", "storage": "N/A"})
    return jsonify(server_utils.get_server_specs())


@app.route("/api/speed_test", methods=["POST"])
def api_speed_test():
    """طھط´ط؛ظٹظ„ ط§ط®طھط¨ط§ط± ط³ط±ط¹ط© ط§ظ„ط¥ظ†طھط±ظ†طھ ظˆط¥ط±ط¬ط§ط¹ ط§ظ„ظ†طھط§ط¦ط¬."""
    if not server_utils:
        return jsonify({"download": "N/A", "upload": "N/A"})
    return jsonify(server_utils.get_internet_speed())


