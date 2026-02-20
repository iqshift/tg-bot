"""
bot/handlers.py - معالجات بوت Telegram
التحسينات:
  - Semaphore لتحديد التحميلات المتزامنة (لحماية الذاكرة)
  - Executor مشترك من main.py
  - حذف فوري للملف بعد الإرسال
  - تقليل استدعاءات DB غير الضرورية
"""
import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from data import database
from downloaders import (
    BaseDownloader,
    InstagramDownloader,
    FacebookDownloader,
    TikTokDownloader,
)

logger = logging.getLogger(__name__)

# ─── وحدات التحميل ───────────────────────────────────────────────────────────
_insta    = InstagramDownloader()
_facebook = FacebookDownloader()
_tiktok   = TikTokDownloader()
_generic  = BaseDownloader()

# ─── Executor مشترك (يُعيّن من main.py) ─────────────────────────────────────
EXECUTOR = None

# ─── حد أقصى للتحميلات المتزامنة (لحماية RAM) ───────────────────────────────
_download_semaphore = asyncio.Semaphore(6)


def _get_downloader(url: str) -> tuple[BaseDownloader, str]:
    if "instagram.com" in url:
        return _insta, "Instagram"
    if "facebook.com" in url or "fb.watch" in url:
        return _facebook, "Facebook"
    if "tiktok.com" in url:
        return _tiktok, "TikTok"
    return _generic, "Generic"


async def _get_user_photo(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str | None:
    try:
        photos = await context.bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count > 0:
            f = await context.bot.get_file(photos.photos[0][0].file_id)
            return f.file_path
    except Exception:
        pass
    return None


# ─── /start ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    # جلب الصورة بشكل غير متزامن لا يعطّل المعالجة
    photo_url = await _get_user_photo(context, user.id)
    database.upsert_user(user.id, user.username, user.first_name, photo_url)
    database.log_message(user.id, "user", "/start")

    db_user = database.get_user(user.id)
    if db_user and db_user["is_banned"]:
        return

    msg = database.get_setting("welcome_msg", "أهلاً! أرسل رابط الفيديو.")
    await update.message.reply_text(msg)
    database.log_message(user.id, "bot", msg)


# ─── /help ───────────────────────────────────────────────────────────────────
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    database.log_message(user.id, "user", "/help")
    db_user = database.get_user(user.id)
    if db_user and db_user["is_banned"]:
        return
    msg = database.get_setting("help_msg", "أرسل رابط Instagram أو Facebook أو TikTok.")
    await update.message.reply_text(msg)
    database.log_message(user.id, "bot", msg)


# ─── معالج الرسائل الرئيسي ───────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user    = update.effective_user
    chat_id = update.effective_chat.id
    url     = update.message.text.strip()

    # تسجيل المستخدم في الخلفية (لا نعطّل معالجة الرابط)
    asyncio.ensure_future(_update_user(context, user))
    database.log_message(user.id, "user", url)

    # فحص الحظر (من الـ cache عادةً)
    db_user = database.get_user(user.id)
    if db_user and db_user["is_banned"]:
        msg = database.get_setting("msg_banned", "⛔ أنت محظور.")
        await update.message.reply_text(msg)
        return

    # فحص اشتراك القنوات
    if not await _check_subscriptions(update, context, user.id, chat_id):
        return

    # ----- التحميل -----
    downloader, platform = _get_downloader(url)

    msg_analyzing = database.get_setting("msg_analyzing", "جاري التحليل... 🔍")
    msg_routing   = database.get_setting("msg_routing",   "توجيه إلى {platform}... 🔄").replace("{platform}", platform)
    msg_complete  = database.get_setting("msg_complete",  "تم التحميل! جاري الرفع... 📤")
    msg_error     = database.get_setting("msg_error",     "فشل التحميل ({platform}) ❌").replace("{platform}", platform)
    msg_caption   = database.get_setting("msg_caption",   "المصدر: {platform}").replace("{platform}", platform)

    status_msg = await update.message.reply_text(msg_analyzing)

    # تحرير الـ event loop أثناء التحميل
    await context.bot.edit_message_text(chat_id=chat_id, message_id=status_msg.message_id, text=msg_routing)

    async with _download_semaphore:   # حد للتحميلات المتزامنة
        try:
            loop      = asyncio.get_running_loop()
            file_path = await loop.run_in_executor(
                EXECUTOR, downloader.download_video, url
            )

            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=status_msg.message_id, text=msg_complete
            )

            with open(file_path, "rb") as video_file:
                await context.bot.send_video(chat_id=chat_id, video=video_file, caption=msg_caption)

            # حذف فوري لتوفير مساحة القرص
            downloader.cleanup(file_path)
            await context.bot.delete_message(chat_id=chat_id, message_id=status_msg.message_id)

        except Exception as exc:
            logger.error("فشل التحميل [%s]: %s", platform, exc)
            error_text = msg_error
            if "{error}" in error_text:
                error_text = error_text.replace("{error}", str(exc))
            else:
                error_text += f"\nDetailed Error: {exc}"
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=status_msg.message_id, text=error_text
                )
            except Exception:
                pass


# ─── دوال مساعدة ─────────────────────────────────────────────────────────────
async def _update_user(context: ContextTypes.DEFAULT_TYPE, user) -> None:
    """تحديث بيانات المستخدم في الخلفية."""
    photo_url = await _get_user_photo(context, user.id)
    database.upsert_user(user.id, user.username, user.first_name, photo_url)


async def _check_subscriptions(update, context, user_id: int, chat_id: int) -> bool:
    """فحص اشتراك القنوات المطلوبة. يُعيد True إذا اجتاز المستخدم الفحص."""
    required_str = database.get_setting("required_channels", "")
    if not required_str.strip():
        return True

    channels   = [c.strip() for c in required_str.split(",") if c.strip()]
    not_joined = []
    # فحص جميع القنوات بالتوازي
    results = await asyncio.gather(
        *[_is_member(context, chat_id=ch, user_id=user_id) for ch in channels],
        return_exceptions=True,
    )
    for ch, joined in zip(channels, results):
        if joined is not True:
            not_joined.append(ch)

    if not_joined:
        channels_list = "\n".join(f"👉 {ch}" for ch in not_joined)
        msg = database.get_setting("msg_force_sub", "يجب الاشتراك في:\n{channels}").replace("{channels}", channels_list)
        await update.message.reply_text(msg)
        return False
    return True


async def _is_member(context, chat_id: str, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status not in ("left", "kicked")
    except Exception:
        return False
