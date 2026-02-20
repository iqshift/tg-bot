"""
main.py - نقطة الدخول الرئيسية للمشروع
────────────────────────────────────────
التحسينات:
  - concurrent_updates=True → معالجة طلبات متعددة بالتوازي
  - ThreadPoolExecutor مخصص → عدد خيوط أكبر للتحميل
  - connection_pool_size أعلى
"""
import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import config

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

from data import database
from bot.handlers import start, help_command, handle_message
from web import server as web_server

# ─── عدد خيوط التحميل ────────────────────────────────────────────────────────
# قيمة مناسبة لـ 1 Core / 2GB RAM بدون إغراق النظام
DOWNLOAD_WORKERS = 8

# ─── تهيئة نظام السجلات ─────────────────────────────────────────────────────
import os
os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)

logging.basicConfig(
    format="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
    level=logging.ERROR,
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
        # ✅ معالجة طلبات متعددة بالتوازي (الأهم)
        .concurrent_updates(True)
        # ✅ حجم pool اتصالات HTTP أعلى
        .connection_pool_size(16)
        # ✅ timeouts مضبوطة
        .connect_timeout(10)
        .read_timeout(30)
        .write_timeout(30)
    )
    if config.PROXY_URL:
        print(f"🔌 Proxy: {config.PROXY_URL}")
        builder = builder.proxy(config.PROXY_URL).get_updates_proxy(config.PROXY_URL)
    return builder.build()


# ─── نقطة الدخول ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    database.init_db()

    # تهيئة ThreadPoolExecutor المشترك لوحدات التحميل
    executor = ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS, thread_name_prefix="dl")
    # تمريره للـ handlers
    from bot import handlers as _h
    _h.EXECUTOR = executor

    application = build_application()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help",  help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    web_server.bot_app = application

    async def post_init(app):
        web_server.bot_loop = asyncio.get_running_loop()
        print(f"✅ Bot Event Loop جاهز | Workers: {DOWNLOAD_WORKERS}")

    application.post_init = post_init

    flask_thread = threading.Thread(target=web_server.run_flask, daemon=True)
    flask_thread.start()
    print("🌐 Flask Dashboard: http://127.0.0.1:5000")
    print(f"🤖 SHΔDØW BOT يعمل | {DOWNLOAD_WORKERS} Download Workers")

    application.run_polling(
        # ✅ جلب أكبر عدد من التحديثات دفعة واحدة
        poll_interval=0.5,
        allowed_updates=["message"],
    )
