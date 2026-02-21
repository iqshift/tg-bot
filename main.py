"""
main.py - نقطة الدخول الرئيسية
────────────────────────────────────────
المعمارية:
  - Flask يعمل على 0.0.0.0:8080 (Cloud Run)
  - Flask يستقبل Telegram updates على /webhook
  - Flask يخدم لوحة التحكم على /
  - PTB Application يعمل في خيط خلفي بـ event loop خاص
"""
import asyncio
import threading
import logging
import time
import os

import config
from data import database
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from bot.handlers import start, help_command, handle_message
from web import server as web_server

# ─── تهيئة السجلات ────────────────────────────────────────────────────────────
os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)
logging.basicConfig(
    format="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ─── بناء التطبيق ────────────────────────────────────────────────────────────
def build_application():
    return (
        ApplicationBuilder()
        .token(config.TELEGRAM_TOKEN)
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

    if config.WEBHOOK_URL:
        webhook_url = config.WEBHOOK_URL.rstrip("/") + "/webhook"
        await app.bot.set_webhook(url=webhook_url, allowed_updates=["message"])
        logger.info("✅ Webhook registered: %s", webhook_url)
    else:
        logger.warning("⚠️ WEBHOOK_URL غير موجود - البوت لن يستقبل تحديثات")

    # انتظر إلى الأبد (Flask يعمل في الخيط الرئيسي)
    await asyncio.Event().wait()


def run_bot_in_thread(app):
    """تشغيل event loop الخاص بالبوت في خيط منفصل."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    # مشاركة الـ loop مع Flask لمعالجة التحديثات
    web_server.bot_loop = loop
    loop.run_until_complete(init_bot(app))


# ─── نقطة الدخول ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    database.init_db()

    application = build_application()

    # مشاركة الـ application مع Flask
    web_server.bot_app = application

    # تشغيل البوت في الخلفية
    bot_thread = threading.Thread(
        target=run_bot_in_thread, args=(application,), daemon=True
    )
    bot_thread.start()

    # انتظر تهيئة البوت قبل قبول الطلبات
    time.sleep(3)
    logger.info("🤖 Bot initialized | Starting Flask on 0.0.0.0:%d", config.WEBHOOK_PORT)

    # تشغيل Flask على port 8080 (Cloud Run)
    web_server.app.run(
        host="0.0.0.0",
        port=config.WEBHOOK_PORT,
        debug=False,
        use_reloader=False,
    )
