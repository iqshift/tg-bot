"""
main.py - نقطة الدخول الرئيسية للمشروع
────────────────────────────────────────
Cloud Run: يشغل Webhook على port 8080
VPS/محلي: يشغل Polling
"""
import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

import config

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

from data import database
from bot.handlers import start, help_command, handle_message

# ─── عدد خيوط التحميل ────────────────────────────────────────────────────────
DOWNLOAD_WORKERS = 4

# ─── تهيئة نظام السجلات ─────────────────────────────────────────────────────
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
    builder = (
        ApplicationBuilder()
        .token(config.TELEGRAM_TOKEN)
        .concurrent_updates(True)
        .connection_pool_size(8)
        .connect_timeout(10)
        .read_timeout(30)
        .write_timeout(30)
    )
    if config.PROXY_URL:
        builder = builder.proxy(config.PROXY_URL).get_updates_proxy(config.PROXY_URL)
    return builder.build()


# ─── نقطة الدخول ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    database.init_db()

    executor = ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS, thread_name_prefix="dl")
    from bot import handlers as _h
    _h.EXECUTOR = executor

    application = build_application()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help",  help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    PORT = config.WEBHOOK_PORT  # 8080 من env var PORT

    if config.WEBHOOK_URL:
        # ─── وضع Webhook (Cloud Run) ─────────────────────────────────────
        logger.info("🌐 Webhook mode: %s | Port: %d", config.WEBHOOK_URL, PORT)
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=config.WEBHOOK_URL,
            url_path="/webhook",
            allowed_updates=["message"],
        )
    else:
        # ─── وضع Polling (محلي / VPS) ────────────────────────────────────
        logger.info("🔄 Polling mode | Workers: %d", DOWNLOAD_WORKERS)
        application.run_polling(
            poll_interval=0.5,
            allowed_updates=["message"],
        )
