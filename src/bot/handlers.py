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

        # التحقق من أن النص هو رابط فعلي، وإلا التحقق من كونه اسم مستخدم إنستغرام
        if not url.startswith(("http://", "https://")):
            import re
            username_match = re.match(r"^@?([a-zA-Z0-9._]{1,30})$", url)
            if username_match:
                username = username_match.group(1)
                await handle_instagram_stories(update, context, username)
                return
            else:
                msg = "⚠️ يرجى إرسال رابط فيديو صحيح من Instagram أو Facebook أو TikTok، أو إرسال اسم مستخدم إنستغرام يبدأ بـ @ لتحميل القصص."
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
                    # إرسال ألبوم (Media Group)
                    from telegram import InputMediaPhoto, InputMediaVideo
                    media = []
                    # تليجرام يسمح بـ 10 عناصر بحد أقصى لكل مجموعة
                    # نستخدم قائمة لفتح الملفات لضمان إغلاقها لاحقاً
                    opened_files = []
                    try:
                        for item in results[:10]:
                            f = open(item, 'rb')
                            opened_files.append(f)
                            if item.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                                media.append(InputMediaPhoto(media=f, caption=final_caption if not media else ""))
                            else:
                                media.append(InputMediaVideo(media=f, caption=final_caption if not media else ""))
                        
                        if media:
                            await context.bot.send_media_group(chat_id=chat_id, media=media, reply_to_message_id=update.message.message_id)
                            await context.bot.delete_message(chat_id=chat_id, message_id=status_msg.message_id)
                    finally:
                        for f in opened_files:
                            f.close()
                else:
                    # إرسال ملف واحد (فيديو أو صورة)
                    if results.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                        with open(results, 'rb') as f:
                            await context.bot.send_photo(
                                chat_id=chat_id,
                                photo=f,
                                caption=final_caption,
                                reply_to_message_id=update.message.message_id
                            )
                    else:
                        with open(results, 'rb') as f:
                            await context.bot.send_video(
                                chat_id=chat_id,
                                video=f,
                                caption=final_caption,
                                reply_to_message_id=update.message.message_id
                            )
                    await context.bot.delete_message(chat_id=chat_id, message_id=status_msg.message_id)

            except Exception as e:
                logger.error(f"Download Error: {e}", exc_info=True)
                database.log_error(user_id=user_id, platform=platform, url=url, error_msg=str(e))
                final_error_msg = msg_error.replace("{error}", str(e))
                await context.bot.edit_message_text(chat_id=chat_id, message_id=status_msg.message_id, text=final_error_msg)
            finally:
                # تنظيف الملفات بعد الإرسال أو الفشل
                if results:
                    try:
                        downloader.cleanup(results)
                    except: pass
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


async def handle_instagram_stories(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # فحص الحظر والاشتراك
    db_user = database.get_user(user.id)
    if db_user and db_user["is_banned"]:
        return

    # فحص اشتراك القنوات
    whitelist_entry = database.get_whitelisted(user.id)
    is_whitelisted = whitelist_entry is not None
    if not is_whitelisted:
        if not await _check_subscriptions(update, context, user.id, chat_id):
            return

    status_msg = await update.message.reply_text(f"🔍 جاري البحث عن قصص نشطة للحساب @{username}...")

    try:
        # تشغيل جلب القصص في خيط منفصل لمنع تجميد الخادم
        loop = asyncio.get_running_loop()
        stories = await loop.run_in_executor(
            EXECUTOR, _insta.get_active_stories, username
        )

        if not stories:
            await status_msg.edit_text(f"📭 لا توجد أي قصص (Stories) نشطة للحساب @{username} حالياً، أو أن الحساب خاص.")
            return

        # حفظ قائمة القصص في ذاكرة الـ context.user_data
        context.user_data[f"stories_{username}"] = stories

        # إنشاء الأزرار
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = []
        
        for i, s in enumerate(stories[:15]):
            type_str = "📹 فيديو" if s["is_video"] else "🖼️ صورة"
            time_str = s["date"].split(" ")[1][:5]  # HH:MM
            btn_text = f"القصة {i+1} ({type_str}) - {time_str}"
            keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"st:{username}:{i}")])

        # زر تحميل الكل
        keyboard.append([InlineKeyboardButton(text="📥 تحميل كل القصص", callback_data=f"stall:{username}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await status_msg.edit_text(
            f"📸 تم العثور على {len(stories)} قصة نشطة لحساب @{username}.\nاختر القصة التي تريد تحميلها أو قم تحميل الكل:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error("Error in handle_instagram_stories: %s", e)
        await status_msg.edit_text(f"❌ حدث خطأ أثناء جلب القصص: {str(e)}")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    chat_id = query.message.chat_id
    user_id = query.from_user.id

    # فحص الحظر
    db_user = database.get_user(user_id)
    if db_user and db_user["is_banned"]:
        return

    # التحقق من نوع الحدث
    if data.startswith("st:"):
        # تحميل قصة فردية
        _, username, index_str = data.split(":")
        index = int(index_str)
        
        stories = context.user_data.get(f"stories_{username}")
        if not stories or index >= len(stories):
            await query.edit_message_text("❌ انتهت صلاحية هذه القائمة. يرجى إرسال اسم المستخدم مرة أخرى.")
            return
            
        story = stories[index]
        status_msg = await query.message.reply_text("📥 جاري تحميل القصة...")
        
        try:
            loop = asyncio.get_running_loop()
            file_path = await loop.run_in_executor(
                EXECUTOR, _insta.download_story_url, story["url"], story["is_video"]
            )
            
            await status_msg.edit_text("📤 جاري الرفع إلى تليجرام...")
            
            caption = f"👤 الحساب: @{username}\n📅 التاريخ: {story['date']}"
            if story["is_video"]:
                with open(file_path, "rb") as f:
                    await context.bot.send_video(chat_id=chat_id, video=f, caption=caption, reply_to_message_id=query.message.message_id)
            else:
                with open(file_path, "rb") as f:
                    await context.bot.send_photo(chat_id=chat_id, photo=f, caption=caption, reply_to_message_id=query.message.message_id)
            
            await status_msg.delete()
            # تنظيف
            _insta.cleanup(file_path)
        except Exception as e:
            logger.error("Error downloading story: %s", e)
            await status_msg.edit_text(f"❌ فشل تحميل القصة: {str(e)}")

    elif data.startswith("stall:"):
        # تحميل جميع القصص
        _, username = data.split(":")
        stories = context.user_data.get(f"stories_{username}")
        if not stories:
            await query.edit_message_text("❌ انتهت صلاحية هذه القائمة. يرجى إرسال اسم المستخدم مرة أخرى.")
            return

        status_msg = await query.message.reply_text(f"📥 جاري تحميل {len(stories)} قصة... قد يستغرق هذا بعض الوقت.")
        
        try:
            downloaded_files = []
            loop = asyncio.get_running_loop()
            
            tasks = []
            for s in stories:
                tasks.append(
                    loop.run_in_executor(
                        EXECUTOR, _insta.download_story_url, s["url"], s["is_video"]
                    )
                )
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            await status_msg.edit_text("📤 جاري الرفع إلى تليجرام...")
            
            for s, res in zip(stories, results):
                if isinstance(res, Exception):
                    logger.error("Error downloading one of the stories: %s", res)
                    continue
                
                downloaded_files.append(res)
                caption = f"👤 الحساب: @{username}\n📅 التاريخ: {s['date']}"
                
                if s["is_video"]:
                    with open(res, "rb") as f:
                        await context.bot.send_video(chat_id=chat_id, video=f, caption=caption)
                else:
                    with open(res, "rb") as f:
                        await context.bot.send_photo(chat_id=chat_id, photo=f, caption=caption)
            
            await status_msg.delete()
            # تنظيف
            for f in downloaded_files:
                _insta.cleanup(f)
                
        except Exception as e:
            logger.error("Error downloading all stories: %s", e)
            await status_msg.edit_text(f"❌ فشل تحميل جميع القصص: {str(e)}")
