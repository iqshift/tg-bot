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

        # التحقق من أن النص هو رابط فعلي، وإلا التحقق من كونه اسم مستخدم (مع دعم النقطة والشرطة السفلية)
        if not url.startswith(("http://", "https://")):
            import re
            # يدعم الأسماء التي تحتوي على حروف وأرقام ونقطة وشرطة سفلية (كـ user.name)
            username_match = re.match(r"^@?([a-zA-Z0-9._]{1,30})$", url)
            if username_match:
                username = username_match.group(1)
                # عرض اختيار المنصة (إنستغرام أو تيك توك)
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                ig_cb = f"plat:ig:{username}"[:64]
                tt_cb = f"plat:tt:{username}"[:64]
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton(text="📸 إنستغرام", callback_data=ig_cb),
                    InlineKeyboardButton(text="🎵 تيك توك",  callback_data=tt_cb),
                ]])
                await update.message.reply_text(
                    f"👤 اختر المنصة لعرض قصص @{username}:",
                    reply_markup=keyboard,
                )
                return
            else:
                msg = "⚠️ يرجى إرسال رابط فيديو صحيح من Instagram أو Facebook أو TikTok، أو إرسال اسم مستخدم (يبدأ بـ @) لتحميل القصص."
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
                results = None
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
                      error_msg_replaced = msg_error.replace("{error}", "No downloadable media found")
                      await context.bot.edit_message_text(chat_id=chat_id, message_id=status_msg.message_id, text=error_msg_replaced)
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
                database.log_error(user_id=user.id, platform=platform, url=url, error_msg=str(e))
                error_msg_replaced = msg_error.replace("{error}", str(e))
                await context.bot.edit_message_text(chat_id=chat_id, message_id=status_msg.message_id, text=error_msg_replaced)
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
    except ValueError as ve:
        # إظهار أخطاء إدخال المستخدم (مثل الحساب خاص أو غير موجود) بشكل مباشر لتنبيهه
        await status_msg.edit_text(f"⚠️ {str(ve)}")
    except Exception as e:
        logger.error("Error in handle_instagram_stories: %s", e)
        database.log_error(user_id=user.id, platform="Instagram Stories", url=f"@{username}", error_msg=str(e))
        msg_stories_err = database.get_setting("msg_stories_error", "عذراً، حدث خطأ بسبب زخم المستخدمين. يرجى المحاولة لاحقاً ❌")
        await status_msg.edit_text(msg_stories_err)


# ─── دوال مساعدة لعرض القصص/المقاطع من Callback ──────────────────────────────
async def _handle_ig_stories_from_callback(
    query, context: ContextTypes.DEFAULT_TYPE,
    username: str, chat_id: int, user_id: int
) -> None:
    """عرض قصص إنستغرام النشطة بعد اختيار المنصة من Callback."""
    status_msg = await query.message.reply_text(
        f"🔍 جاري البحث عن قصص نشطة للحساب @{username}..."
    )
    try:
        loop = asyncio.get_running_loop()
        stories = await loop.run_in_executor(EXECUTOR, _insta.get_active_stories, username)

        if not stories:
            await status_msg.edit_text(
                f"📭 لا توجد قصص نشطة للحساب @{username} حالياً، أو أن الحساب خاص."
            )
            return

        context.user_data[f"stories_{username}"] = stories

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = []
        for i, s in enumerate(stories[:15]):
            type_str = "📹 فيديو" if s["is_video"] else "🖼️ صورة"
            time_str = s["date"].split(" ")[1][:5]
            btn_text  = f"القصة {i+1} ({type_str}) - {time_str}"
            keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"st:{username}:{i}")])
        keyboard.append([InlineKeyboardButton(text="📥 تحميل كل القصص", callback_data=f"stall:{username}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await status_msg.edit_text(
            f"📸 تم العثور على {len(stories)} قصة نشطة لحساب @{username}.\n"
            "اختر القصة التي تريد تحميلها أو قم بتحميل الكل:",
            reply_markup=reply_markup,
        )
    except ValueError as ve:
        await status_msg.edit_text(f"⚠️ {str(ve)}")
    except Exception as e:
        logger.error("Error in _handle_ig_stories_from_callback: %s", e)
        database.log_error(user_id=user_id, platform="Instagram Stories", url=f"@{username}", error_msg=str(e))
        msg_err = database.get_setting(
            "msg_stories_error", "عذراً، حدث خطأ بسبب زخم المستخدمين. يرجى المحاولة لاحقاً ❌"
        )
        await status_msg.edit_text(msg_err)


async def _handle_tt_videos_from_callback(
    query, context: ContextTypes.DEFAULT_TYPE,
    username: str, chat_id: int, user_id: int
) -> None:
    """عرض أحدث مقاطع فيديو مستخدم تيك توك بعد اختيار المنصة."""
    status_msg = await query.message.reply_text(
        f"🔍 جاري جلب أحدث مقاطع الحساب @{username} على تيك توك..."
    )
    try:
        loop = asyncio.get_running_loop()
        videos = await loop.run_in_executor(EXECUTOR, _tiktok.get_user_videos, username)

        if not videos:
            await status_msg.edit_text(
                f"📭 لا توجد مقاطع متاحة للحساب @{username} حالياً."
            )
            return

        context.user_data[f"tt_videos_{username}"] = videos

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = []
        for i, v in enumerate(videos[:10]):
            title    = (v.get("title") or "بدون عنوان")[:22]
            duration = v.get("duration", 0)
            dur_str  = f" ({duration}s)" if duration else ""
            btn_text = f"🎵 {i+1}. {title}{dur_str}"[:40]
            cb_data  = f"ttv:{username}:{i}"[:64]   # callback_data max 64 bytes
            keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])
        keyboard.append([InlineKeyboardButton(
            text="📥 تحميل الكل", callback_data=f"ttvall:{username}"[:64]
        )])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await status_msg.edit_text(
            f"🎵 تم العثور على {len(videos)} مقطع للحساب @{username}.\n"
            "اختر المقطع الذي تريد تحميله أو حمّل الكل:",
            reply_markup=reply_markup,
        )
    except ValueError as ve:
        await status_msg.edit_text(f"⚠️ {str(ve)}")
    except Exception as e:
        logger.error("Error in _handle_tt_videos_from_callback: %s", e)
        database.log_error(user_id=user_id, platform="TikTok User Videos", url=f"@{username}", error_msg=str(e))
        msg_err = database.get_setting(
            "msg_stories_error", "عذراً، حدث خطأ بسبب زخم المستخدمين. يرجى المحاولة لاحقاً ❌"
        )
        await status_msg.edit_text(msg_err)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query   = update.callback_query
    await query.answer()

    data    = query.data
    chat_id = query.message.chat_id
    user_id = query.from_user.id

    # فحص الحظر
    db_user = database.get_user(user_id)
    if db_user and db_user["is_banned"]:
        return

    # ── اختيار المنصة (إنستغرام / تيك توك) ─────────────────────────────────
    if data.startswith("plat:"):
        parts    = data.split(":", 2)
        platform = parts[1] if len(parts) > 1 else ""
        username = parts[2] if len(parts) > 2 else ""
        if not username:
            return
        if platform == "ig":
            await _handle_ig_stories_from_callback(query, context, username, chat_id, user_id)
        elif platform == "tt":
            await _handle_tt_videos_from_callback(query, context, username, chat_id, user_id)

    # ── تحميل قصة إنستغرام فردية ────────────────────────────────────────────
    elif data.startswith("st:"):
        parts    = data.split(":")
        username = parts[1]
        index    = int(parts[2])

        stories = context.user_data.get(f"stories_{username}")
        if not stories or index >= len(stories):
            await query.edit_message_text("❌ انتهت صلاحية القائمة. يرجى إرسال اسم المستخدم مجدداً.")
            return

        story      = stories[index]
        status_msg = await query.message.reply_text("📥 جاري تحميل القصة...")
        try:
            loop      = asyncio.get_running_loop()
            file_path = await loop.run_in_executor(
                EXECUTOR, _insta.download_story_url, story["url"], story["is_video"]
            )
            await status_msg.edit_text("📤 جاري الرفع إلى تليجرام...")
            caption = f"👤 الحساب: @{username}\n📅 التاريخ: {story['date']}"
            if story["is_video"]:
                with open(file_path, "rb") as f:
                    await context.bot.send_video(
                        chat_id=chat_id, video=f, caption=caption,
                        reply_to_message_id=query.message.message_id
                    )
            else:
                with open(file_path, "rb") as f:
                    await context.bot.send_photo(
                        chat_id=chat_id, photo=f, caption=caption,
                        reply_to_message_id=query.message.message_id
                    )
            await status_msg.delete()
            _insta.cleanup(file_path)
        except Exception as e:
            logger.error("Error downloading story: %s", e)
            database.log_error(user_id=user_id, platform="Instagram Stories",
                               url=f"@{username} (single)", error_msg=str(e))
            msg_err = database.get_setting(
                "msg_stories_error", "عذراً، حدث خطأ بسبب زخم المستخدمين. يرجى المحاولة لاحقاً ❌"
            )
            await status_msg.edit_text(msg_err)

    # ── تحميل جميع قصص إنستغرام ─────────────────────────────────────────────
    elif data.startswith("stall:"):
        _, username = data.split(":", 1)
        stories     = context.user_data.get(f"stories_{username}")
        if not stories:
            await query.edit_message_text("❌ انتهت صلاحية القائمة. يرجى إرسال اسم المستخدم مجدداً.")
            return

        status_msg = await query.message.reply_text(
            f"📥 جاري تحميل {len(stories)} قصة... قد يستغرق هذا بعض الوقت."
        )
        try:
            downloaded_files = []
            loop             = asyncio.get_running_loop()
            tasks            = [
                loop.run_in_executor(EXECUTOR, _insta.download_story_url, s["url"], s["is_video"])
                for s in stories
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            await status_msg.edit_text("📤 جاري الرفع إلى تليجرام...")
            for s, res in zip(stories, results):
                if isinstance(res, Exception):
                    logger.error("Error downloading one story: %s", res)
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
            for fp in downloaded_files:
                _insta.cleanup(fp)
        except Exception as e:
            logger.error("Error downloading all stories: %s", e)
            database.log_error(user_id=user_id, platform="Instagram Stories",
                               url=f"@{username} (all)", error_msg=str(e))
            msg_err = database.get_setting(
                "msg_stories_error", "عذراً، حدث خطأ بسبب زخم المستخدمين. يرجى المحاولة لاحقاً ❌"
            )
            await status_msg.edit_text(msg_err)

    # ── تحميل مقطع تيك توك فردي ─────────────────────────────────────────────
    elif data.startswith("ttv:"):
        parts    = data.split(":")
        username = parts[1]
        index    = int(parts[2])

        videos = context.user_data.get(f"tt_videos_{username}")
        if not videos or index >= len(videos):
            await query.edit_message_text("❌ انتهت صلاحية القائمة. يرجى إرسال اسم المستخدم مجدداً.")
            return

        video      = videos[index]
        status_msg = await query.message.reply_text("📥 جاري تحميل المقطع...")
        try:
            loop        = asyncio.get_running_loop()
            result_dict = await loop.run_in_executor(
                EXECUTOR, _tiktok.download_video, video["play_url"]
            )
            file_path = result_dict.get("results")
            if not file_path:
                raise ValueError("لم يتم التحميل بنجاح")

            await status_msg.edit_text("📤 جاري الرفع إلى تليجرام...")
            caption = f"👤 @{username}\n📝 {video.get('title', '')}"

            if isinstance(file_path, list):
                from telegram import InputMediaPhoto, InputMediaVideo
                media        = []
                opened_files = []
                try:
                    for item in file_path[:10]:
                        fh = open(item, "rb")
                        opened_files.append(fh)
                        if item.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                            media.append(InputMediaPhoto(media=fh, caption=caption if not media else ""))
                        else:
                            media.append(InputMediaVideo(media=fh, caption=caption if not media else ""))
                    if media:
                        await context.bot.send_media_group(chat_id=chat_id, media=media)
                finally:
                    for fh in opened_files:
                        fh.close()
            else:
                with open(file_path, "rb") as fh:
                    await context.bot.send_video(chat_id=chat_id, video=fh, caption=caption)

            await status_msg.delete()
            _tiktok.cleanup(file_path)
        except Exception as e:
            logger.error("Error downloading TikTok video: %s", e)
            database.log_error(user_id=user_id, platform="TikTok User Videos",
                               url=f"@{username}", error_msg=str(e))
            msg_err = database.get_setting(
                "msg_stories_error", "عذراً، حدث خطأ بسبب زخم المستخدمين. يرجى المحاولة لاحقاً ❌"
            )
            await status_msg.edit_text(msg_err)

    # ── تحميل جميع مقاطع تيك توك ────────────────────────────────────────────
    elif data.startswith("ttvall:"):
        _, username = data.split(":", 1)
        videos      = context.user_data.get(f"tt_videos_{username}")
        if not videos:
            await query.edit_message_text("❌ انتهت صلاحية القائمة. يرجى إرسال اسم المستخدم مجدداً.")
            return

        status_msg = await query.message.reply_text(
            f"📥 جاري تحميل {len(videos)} مقطع... قد يستغرق هذا بعض الوقت."
        )
        downloaded = []
        for i, video in enumerate(videos):
            try:
                await status_msg.edit_text(f"📥 تحميل {i+1}/{len(videos)}...")
                loop        = asyncio.get_running_loop()
                result_dict = await loop.run_in_executor(
                    EXECUTOR, _tiktok.download_video, video["play_url"]
                )
                file_path = result_dict.get("results")
                if not file_path:
                    continue
                caption = f"👤 @{username}\n📝 {video.get('title', '')}"
                if isinstance(file_path, list):
                    for item in file_path:
                        if item.lower().endswith((".mp4",)):
                            with open(item, "rb") as fh:
                                await context.bot.send_video(chat_id=chat_id, video=fh, caption=caption)
                        else:
                            with open(item, "rb") as fh:
                                await context.bot.send_photo(chat_id=chat_id, photo=fh, caption=caption)
                    _tiktok.cleanup(file_path)
                else:
                    with open(file_path, "rb") as fh:
                        await context.bot.send_video(chat_id=chat_id, video=fh, caption=caption)
                    _tiktok.cleanup(file_path)
                downloaded.append(video)
            except Exception as e:
                logger.error("Error downloading TikTok video %d for @%s: %s", i, username, e)

        if downloaded:
            await status_msg.delete()
        else:
            msg_err = database.get_setting(
                "msg_stories_error", "عذراً، حدث خطأ بسبب زخم المستخدمين. يرجى المحاولة لاحقاً ❌"
            )
            await status_msg.edit_text(msg_err)
