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
import os

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


async def _get_user_photo(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> tuple[str | None, str | None]:
    try:
        photos = await context.bot.get_user_profile_photos(user_id, limit=1)
        if photos.total_count > 0:
            photo_size = photos.photos[0][0]
            f = await context.bot.get_file(photo_size.file_id)
            return f.file_path, photo_size.file_id
    except Exception:
        pass
    return None, None


async def _update_user_db(context: ContextTypes.DEFAULT_TYPE, user) -> None:
    """دالة مساعدة لتحديث بيانات المستخدم شاملة الصورة ومعرف الملف."""
    photo_url, photo_file_id = await _get_user_photo(context, user.id)
    database.upsert_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        photo_url=photo_url,
        photo_file_id=photo_file_id
    )


# ─── /start ──────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        user = update.effective_user
        if not user: return
        
        # جلب الصورة وتحيين المستخدم بشكل موحد
        await _update_user_db(context, user)
        database.log_message(user.id, "user", "/start")

        db_user = database.get_user(user.id)
        if db_user and db_user["is_banned"]:
            return

        msg = database.get_setting("welcome_msg", "أهلاً! أرسل رابط الفيديو.")
        
        # جلب إعدادات المشاركة
        share_msg  = database.get_setting("share_msg", "هذا هو البوت الاحترافي للتحميل! @ir4qibot")
        share_btn  = database.get_setting("share_btn_text", "مشاركة مع الأصدقاء 🔗")
        
        # تجهيز رابط المشاركة
        import urllib.parse
        try:
            bot_meta = await context.bot.get_me()
            bot_username = bot_meta.username
        except:
            bot_username = context.bot.username or "bot"

        encoded_share = urllib.parse.quote_plus(share_msg)
        share_url = f"https://t.me/share/url?url=https://t.me/{bot_username}&text={encoded_share}"
        
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(text=share_btn, url=share_url)]
        ])

        await update.message.reply_text(msg, reply_markup=keyboard)
        database.log_message(user.id, "bot", msg)
    except Exception as e:
        logger.error(f"FATAL error in start: {e}", exc_info=True)
        print(f"DEBUG START ERROR: {e}")


# ─── /help ───────────────────────────────────────────────────────────────────
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        user = update.effective_user
        if not user: return
        database.log_message(user.id, "user", "/help")
        db_user = database.get_user(user.id)
        if db_user and db_user["is_banned"]:
            return
        msg = database.get_setting("help_msg", "أرسل رابط Instagram أو Facebook أو TikTok.")
        await update.message.reply_text(msg)
        database.log_message(user.id, "bot", msg)
    except Exception as e:
        logger.error(f"Error in help: {e}")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """أمر لفحص حالة البوت والاتصال."""
    try:
        user = update.effective_user
        if not user: return
        
        db_status = "✅ متصل" if database._get_db() else "❌ غير متصل (يعمل بالقيم الافتراضية)"
        
        msg = (
            "🤖 **حالة البوت الحالية:**\n\n"
            f"👤 المستخدم: `{user.id}`\n"
            f"🗄️ قاعدة البيانات: {db_status}\n"
            f"🌐 نوع الاتصال: Webhook\n"
            "🛡️ نظام التتبع: نشط"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in status: {e}")


# ─── معالج الرسائل الرئيسي ───────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        user    = update.effective_user
        chat_id = update.effective_chat.id
        if not update.message or not update.message.text: return
        url     = update.message.text.strip()

        # تسجيل المستخدم في الخلفية (لا نعطّل معالجة الرابط)
        asyncio.create_task(_update_user_db(context, user))
        database.log_message(user.id, "user", url)

        # فحص الحظر (من الـ cache عادةً)
        db_user = database.get_user(user.id)
        if db_user and db_user["is_banned"]:
            msg = database.get_setting("msg_banned", "⛔ أنت محظور.")
            await update.message.reply_text(msg)
            return

        # فحص القائمة البيضاء (Exemption)
        whitelist_entry = database.get_whitelisted(user.id)
        is_whitelisted  = whitelist_entry is not None

        # فحص اشتراك القنوات (يتخطى إذا كان في القائمة البيضاء)
        if not is_whitelisted:
            if not await _check_subscriptions(update, context, user.id, chat_id):
                return

        # التحقق من أن النص هو رابط فعلي قبل البدء
        if not url.startswith(("http://", "https://")):
            msg = "⚠️ يرجى إرسال رابط فيديو صحيح من Instagram أو Facebook أو TikTok.\nمثال: https://instagram.com/p/..."
            await update.message.reply_text(msg)
            return

        # ----- التحميل -----
        downloader, platform = _get_downloader(url)

        # تخصيص الرد لمستخدمي القائمة البيضاء
        custom_reply = whitelist_entry.get("custom_reply") if is_whitelisted else None
        
        msg_analyzing = custom_reply if custom_reply else database.get_setting("msg_analyzing", "جاري التحليل... 🔍")
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
                stats_dict = await loop.run_in_executor(
                    EXECUTOR, downloader.download_video, url
                )
                
                # استخراج النتائج والوصف
                results     = stats_dict.get("results")
                description = stats_dict.get("description", "")

                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=status_msg.message_id, text=msg_complete
                )

                # دمج الوصف المستخرج مع الكابشن الافتراضي
                # سنقوم بوضع الوصف في البداية ثم المصدر
                final_caption = f"{description}\n\n{msg_caption}" if description else msg_caption
                # تليجرام لديه حد أقصى للحروف في الكابشن (1024)
                if len(final_caption) > 1024:
                    final_caption = final_caption[:1020] + "..."

                if not results:
                     await context.bot.edit_message_text(chat_id=chat_id, message_id=status_msg.message_id, text=msg_error)
                     return

                if isinstance(results, list):
                    # إرسال ألبوم (Media Group) - تليجرام يسمح بـ 10 عناصر بحد أقصى لكل مجموعة
                    from telegram import InputMediaPhoto, InputMediaVideo
                    media = []
                    for item in results[:10]:
                        if item.endswith((".jpg", ".jpeg", ".png", ".webp")):
                            media.append(InputMediaPhoto(media=item, caption=final_caption if not media else ""))
                        else:
                            media.append(InputMediaVideo(media=item, caption=final_caption if not media else ""))
                    
                    if media:
                        await context.bot.send_media_group(chat_id=chat_id, media=media, reply_to_message_id=update.message.message_id)
                        await context.bot.delete_message(chat_id=chat_id, message_id=status_msg.message_id)
                else:
                    # إرسال فيديو واحد
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=results,
                        caption=final_caption,
                        reply_to_message_id=update.message.message_id
                    )
                    await context.bot.delete_message(chat_id=chat_id, message_id=status_msg.message_id)

            except Exception as e:
                logger.error(f"Download Error: {e}", exc_info=True)
                # تسجيل الخطأ في قاعدة البيانات ليظهر في لوحة التحكم
                database.log_error(user_id=user_id, platform=platform, url=url, error_msg=str(e))
                
                final_error_msg = msg_error.replace("{error}", str(e))
                await context.bot.edit_message_text(chat_id=chat_id, message_id=status_msg.message_id, text=final_error_msg)
    except Exception as e:
        logger.error(f"FATAL error in handle_message: {e}", exc_info=True)
        print(f"DEBUG HANDLE_MSG ERROR: {e}")





# ─── دوال مساعدة ─────────────────────────────────────────────────────────────
async def _update_user(context: ContextTypes.DEFAULT_TYPE, user) -> None:
    """تحديث بيانات المستخدم في الخلفية (نسخة قديمة - يرجى استخدام _update_user_db)."""
    await _update_user_db(context, user)


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
