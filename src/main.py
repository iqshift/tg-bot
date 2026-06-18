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
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from bot.handlers import start, help_command, handle_message, status_command, handle_callback
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
    # إعادة قراءة الملف للتأكد من الحصول على أحدث توكن مخزن
    token = force_token or config._read_secret(config.TELEGRAM_TOKEN_FILE, env_key="TELEGRAM_TOKEN")
    
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
    if not app: return
    
    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("help",   help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    await app.initialize()
    await app.start()

    # إذا كنا في البيئة المحلية (وليس Cloud Run)، نستخدم Polling بدلاً من Webhook للاختبار
    if not os.environ.get("K_SERVICE"):
        try:
            await app.bot.delete_webhook(drop_pending_updates=True)
            await app.updater.start_polling(allowed_updates=["message"])
            logger.info("⚡ Local Polling started successfully! The bot will respond to messages locally.")
        except Exception as e:
            logger.error(f"❌ Failed to start local polling: {e}")
        return

    # إعادة قراءة رابط الويب هوك من الملف
    # إعادة قراءة رابط الويب هوك من الملف
    webhook_url_config = config._read_secret(config.WEBHOOK_URL_FILE, env_key="WEBHOOK_URL")
    if not webhook_url_config:
        webhook_url_config = database.get_setting("webhook_url", "")

    if webhook_url_config:
        # تنظيف الرابط لضمان عدم التكرار
        base_url = webhook_url_config.strip().rstrip("/")
        if base_url.endswith("/webhook"):
            base_url = base_url[:-8].rstrip("/")
        
        webhook_url = base_url + "/webhook"
        
        # تنظيف الويب هوك القديم وحذف أي رسائل متراكمة قد تسبب تعارضاً (Conflict)
        try:
            await app.bot.delete_webhook(drop_pending_updates=True)
            logger.info("🧹 Old webhook deleted and pending updates dropped.")
        except Exception as e:
            logger.warning(f"⚠️ Could not delete old webhook: {e}")

        await app.bot.set_webhook(url=webhook_url, allowed_updates=["message"])
        logger.info("✅ Webhook registered: %s", webhook_url)
    else:
        logger.warning("⚠️ WEBHOOK_URL غير موجود - البوت لن يستقبل تحديثات")

# خزانة لمشاركة حالة إعادة التشغيل مع الخوادم الأخرى
_restart_request = asyncio.Event()

async def bot_main_loop(initial_app):
    """الحلقة المستمرة للبوت التي تدعم إعادة التشغيل السريع."""
    app = initial_app
    
    while True:
        # إذا لم يكن هناك تطبيق (توكن مفقود مثلاً)، نحاول بناءه
        if app is None:
            while app is None:
                token = config._read_secret(config.TELEGRAM_TOKEN_FILE, env_key="TELEGRAM_TOKEN")
                if token:
                    app = build_application(force_token=token)
                    web_server.bot_app = app
                    if app: break
                logger.warning("🕒 Waiting for TELEGRAM_TOKEN... (Next retry in 30s)")
                await asyncio.sleep(30)

        # تهيئة وتشغيل البوت الحالي
        bot_task = asyncio.create_task(init_bot(app))
        
        # الانتظار حتى يطلب السيرفر إعادة تشغيل (Hot Reload)
        await _restart_request.wait()
        _restart_request.clear()
        
        logger.info("🔄 Hot Reload Triggered: Restarting Bot Application...")
        
        # إيقاف البوت القديم بسلام
        if app:
            try:
                await app.stop()
                await app.shutdown()
            except Exception as e:
                logger.error(f"Error during bot shutdown: {e}")
        
        # بناء البوت من جديد بأحدث الإعدادات
        app = build_application()
        web_server.bot_app = app
        logger.info("🚀 Bot Application Rebuilt.")


def run_bot_in_thread(initial_app):
    """تشغيل event loop الخاص بالبوت في خيط منفصل."""
    try:
        database.init_db()
    except Exception as exc:
        logger.error("❌ DB init failed: %s", exc)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    web_server.bot_loop = loop
    
    # تصحيح: تهيئة الحدث داخل الـ loop
    global _restart_request
    _restart_request = asyncio.Event()

    # تصدير دالة إعادة التشغيل بشكل صحيح للوحة التحكم
    def trigger_restart():
        loop.call_soon_threadsafe(_restart_request.set)
    
    # ربط الدالة بـ Flask app مباشرة لسهولة الوصول
    web_server.app.trigger_bot_restart = trigger_restart

    try:
        loop.run_until_complete(bot_main_loop(initial_app))
    except Exception as exc:
        logger.error("❌ Bot thread failed: %s", exc)


# ─── نقطة الدخول ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    application = build_application()
    web_server.bot_app = application

    bot_thread = threading.Thread(
        target=run_bot_in_thread, args=(application,), daemon=True
    )
    bot_thread.start()
    logger.info("🤖 Bot thread started in background")

    port = config.WEBHOOK_PORT
    logger.info("🌐 Starting Flask on 0.0.0.0:%d", port)
    web_server.app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
