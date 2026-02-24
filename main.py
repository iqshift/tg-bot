"""
main.py - نقطة الدخول الرئيسية
────────────────────────────────────────
المعمارية:
  - Flask يبدأ أولاً على PORT=8080 (Cloud Run health check)
  - البوت يتهيأ في الخلفية بعد ذلك
  - Flask يستقبل Telegram updates على /webhook
  - Flask يخدم لوحة التحكم على /
"""
import asyncio
import threading
import logging
import os

print(f"🚀 [INIT] Starting application in {os.getcwd()}")
print(f"🚀 [INIT] PORT environment: {os.environ.get('PORT', '8080 (default)')}")

import config
from data import database
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from bot.handlers import start, help_command, handle_message
from web import server as web_server

# ─── تهيئة السجلات ────────────────────────────────────────────────────────────
try:
    os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)
    file_handler = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
except Exception as e:
    print(f"⚠️ Warning: Could not setup FileHandler for logging: {e}")
    file_handler = None

handlers = [logging.StreamHandler()]
if file_handler:
    handlers.append(file_handler)

logging.basicConfig(
    format="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
    level=logging.INFO,
    handlers=handlers,
)
logger = logging.getLogger(__name__)


# ─── بناء التطبيق ────────────────────────────────────────────────────────────
def build_application(force_token=None):
    token = force_token or config.TELEGRAM_TOKEN
    
    # تحذير: لا تحاول جلب التوكن من Firestore هنا!
    # استدعاء Firestore في الخيط الرئيسي قد يعطل بدء Flask إذا كانت القاعدة غير مفعلة.
    # سيتم جلب التوكن في خيط البوت المنفصل لاحقاً.

    if not token:
        logger.error("❌ TELEGRAM_TOKEN is missing! Bot construction delayed.")
        return None
        
    return (
        ApplicationBuilder()
        .token(token)
        .concurrent_updates(True)
        .connection_pool_size(8)
        .connect_timeout(10)
        .read_timeout(30)
        .write_timeout(30)
        .build()
    )


async def init_bot(app):
    """تهيئة البوت وتسجيل الـ Webhook مع Telegram."""
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help",  help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await app.initialize()
    await app.start()

    webhook_url_config = config.WEBHOOK_URL
    if not webhook_url_config:
        webhook_url_config = database.get_setting("webhook_url", "")

    if webhook_url_config:
        webhook_url = webhook_url_config.rstrip("/") + "/webhook"
        await app.bot.set_webhook(url=webhook_url, allowed_updates=["message"])
        logger.info("✅ Webhook registered: %s", webhook_url)
    else:
        logger.warning("⚠️ WEBHOOK_URL غير موجود - البوت لن يستقبل تحديثات")

    # انتظر إلى الأبد (Flask يعمل في الخيط الرئيسي)
    await asyncio.Event().wait()


def run_bot_in_thread(initial_app):
    """تشغيل event loop الخاص بالبوت في خيط منفصل."""
    # ✅ init_db هنا بدلاً من قبل Flask - حتى لا يعطّل بدء الخادم
    try:
        database.init_db()
    except Exception as exc:
        logger.error("❌ DB init failed: %s", exc)

    app = initial_app
    
    # إذا لم يكن التوكن موجوداً، نحاول جلبه من DB كل دقيقة حتى يتوفر
    while app is None:
        token = database.get_setting("telegram_token", "")
        if token:
            logger.info("🔑 Token found in Firestore! Building application...")
            app = build_application(force_token=token)
            web_server.bot_app = app
            if app: break
        
        logger.warning("🕒 Waiting for TELEGRAM_TOKEN... (Next retry in 60s)")
        import time
        time.sleep(60)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    web_server.bot_loop = loop
    try:
        loop.run_until_complete(init_bot(app))
    except Exception as exc:
        logger.error("❌ Bot thread failed: %s", exc)


# ─── نقطة الدخول ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    application = build_application()

    # مشاركة الـ application مع Flask
    web_server.bot_app = application

    # تشغيل البوت في الخلفية (لا ننتظره)
    bot_thread = threading.Thread(
        target=run_bot_in_thread, args=(application,), daemon=True
    )
    bot_thread.start()
    logger.info("🤖 Bot thread started in background")

    # ✅ Flask يبدأ فوراً بدون انتظار البوت
    # Cloud Run يحتاج الـ port مفتوح خلال ثواني قليلة
    port = config.WEBHOOK_PORT
    logger.info("🌐 Starting Flask on 0.0.0.0:%d", port)
    web_server.app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
