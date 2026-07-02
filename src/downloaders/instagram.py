"""
downloaders/instagram.py - وحدة تحميل Instagram المطورة
تستخدم Instaloader لدعم الألبومات (Carousel) بدقة عالية.
"""
import os
import time
import logging
import shutil
import instaloader
import requests as _requests
import random

import config
from data import database
from .base import BaseDownloader

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

class InstagramDownloader(BaseDownloader):
    """وحدة تحميل Instagram باستخدام Instaloader."""

    def __init__(self, download_path: str = None):
        super().__init__(download_path)
        # التأكد من أن المسار مطلق لـ Instaloader
        self.abs_download_path = os.path.abspath(self.download_path)
        os.makedirs(self.abs_download_path, exist_ok=True)
        
        self.L = instaloader.Instaloader(
            download_pictures=True,
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            user_agent=_USER_AGENT,
            # سيتم وضع المجلدات داخل المجلد الرئيسي مباشرة
            dirname_pattern=os.path.join(self.abs_download_path, "{target}"),
            filename_pattern="{shortcode}"
        )
        
        # تحميل ملف الكوكيز الخاص بإنستغرام لـ Instaloader إذا وجد
        import http.cookiejar
        if os.path.exists(config.INSTAGRAM_COOKIES):
            try:
                cj = http.cookiejar.MozillaCookieJar(config.INSTAGRAM_COOKIES)
                cj.load(ignore_discard=True, ignore_expires=True)
                self.L.context._session.cookies.update(cj)
                logger.info("✅ Instaloader session loaded with cookies")
            except Exception as e:
                logger.warning("⚠️ Could not load Instagram cookies into Instaloader: %s", e)

    def _set_random_proxy(self):
        try:
            proxies = database.get_proxies()
            if proxies:
                proxy = random.choice(proxies)
                if not proxy.startswith(("http://", "https://", "socks5://", "socks4://")):
                    proxy = f"http://{proxy}"
                self.L.context._session.proxies = {"http": proxy, "https": proxy}
                logger.info("📡 [Instaloader] Set random proxy: %s", proxy)
            else:
                self.L.context._session.proxies = {}
        except Exception as pe:
            logger.warning("⚠️ Failed to set proxy for Instaloader: %s", pe)
            self.L.context._session.proxies = {}

    def download_video(self, url: str) -> dict:
        """تحميل منشور (فيديو، صورة، أو ألبوم)."""
        shortcode = self._get_shortcode(url)
        if not shortcode:
            raise ValueError("رابط Instagram غير صالح أو غير مدعوم")

        # نحاول أولاً استخدام yt-dlp لأنه الأسرع والأكثر استقراراً حالياً للفيديوهات والمنشورات الفردية
        logger.info("📥 [yt-dlp] Attempting download first for: %s", url)
        try:
            opts = {}
            if os.path.exists(config.INSTAGRAM_COOKIES):
                opts["cookiefile"] = config.INSTAGRAM_COOKIES
                logger.info("✅ Using Instagram cookies for yt-dlp")
            
            res = self._download(url, extra_opts=opts)
            if res and os.path.exists(res["results"]) and not res["results"].lower().endswith(".na"):
                logger.info("✅ [yt-dlp] Download success")
                return {"results": res["results"], "description": res["description"]}
        except Exception as yt_err:
            logger.warning("⚠️ [yt-dlp] Failed to download: %s. Trying Instaloader...", yt_err)

        # إذا فشل yt-dlp، نلجأ إلى Instaloader كخيار احتياطي (مثلاً للألبومات المتعددة)
        self._set_random_proxy()
        # اسم المجلد النسبي
        target_name = f"temp_{shortcode}_{int(time.time())}"
        # المسار الفعلي المتوقع
        target_dir = os.path.join(self.abs_download_path, target_name)

        try:
            logger.info("📥 [Instaloader] Fetching post: %s", shortcode)
            post = instaloader.Post.from_shortcode(self.L.context, shortcode)
            description = post.caption or ""
            
            # التحميل الفعلي
            logger.info("📥 [Instaloader] Downloading to folder: %s", target_name)
            self.L.download_post(post, target=target_name)

            # التحقق من وجود المجلد
            if not os.path.exists(target_dir):
                if os.path.exists(target_name):
                    target_dir = os.path.abspath(target_name)

            # جمع الملفات
            media_files = []
            if os.path.exists(target_dir):
                for f in os.listdir(target_dir):
                    if f.lower().endswith(('.jpg', '.jpeg', '.png', '.mp4')):
                        media_files.append(os.path.join(target_dir, f))

            if not media_files:
                raise ValueError("لم يتم العثور على ملفات وسائط بعد تحميل Instaloader")

            media_files.sort()

            # إذا كان ملفاً واحداً
            if len(media_files) == 1:
                final_path = os.path.join(self.abs_download_path, f"insta_{shortcode}_{int(time.time())}{os.path.splitext(media_files[0])[1]}")
                shutil.copy2(media_files[0], final_path)
                shutil.rmtree(target_dir, ignore_errors=True)
                return {"results": final_path, "description": description}
            
            # ألبوم
            logger.info("✅ [Instaloader] Success: %d items", len(media_files))
            return {"results": media_files, "description": description}

        except Exception as e:
            logger.error("❌ [Instaloader] Error: %s", e)
            if os.path.exists(target_dir):
                shutil.rmtree(target_dir, ignore_errors=True)
            raise ValueError(f"⚠️ خطأ في تحميل المنشور: {str(e)}")

    def _get_shortcode(self, url: str) -> str:
        parts = [p for p in url.split("/") if p]
        for i, p in enumerate(parts):
            if p in ("p", "reels", "reel") and i + 1 < len(parts):
                return parts[i+1].split("?")[0]
        return None

    def get_active_stories(self, username: str) -> list[dict]:
        """جلب قائمة القصص النشطة لمستخدم معين."""
        try:
            self._set_random_proxy()
            logger.info("📥 [Instaloader] Fetching profile stories for: %s", username)
            # التأكد من صحة الجلسة عبر محاولة جلب الملف الشخصي
            profile = instaloader.Profile.from_username(self.L.context, username)
            
            stories_items = []
            for story in self.L.get_stories(userids=[profile.userid]):
                for item in story.get_items():
                    stories_items.append({
                        "media_id": item.mediaid,
                        "is_video": item.is_video,
                        "url": item.video_url if item.is_video else item.url,
                        "date": item.date_utc.strftime("%Y-%m-%d %H:%M:%S")
                    })
            # ترتيب من الأقدم للأحدث
            stories_items.sort(key=lambda x: x["date"])
            return stories_items
        except Exception as e:
            logger.error("❌ [Instaloader] Error fetching stories: %s", e)
            raise Exception(f"فشل جلب القصص للحساب {username}. قد يكون الحساب خاصاً أو ملف الكوكيز منتهي الصلاحية.")

    def download_story_url(self, url: str, is_video: bool) -> str:
        """تحميل قصة فردية مباشرة من رابط الـ CDN الخاص بإنستغرام."""
        import uuid
        ext = ".mp4" if is_video else ".jpg"
        filename = f"story_{uuid.uuid4()}{ext}"
        filepath = os.path.join(self.abs_download_path, filename)
        
        try:
            self._set_random_proxy()
            response = self.L.context._session.get(url, stream=True, timeout=15)
            response.raise_for_status()
            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            return filepath
        except Exception as e:
            logger.error("❌ Failed to download story URL: %s", e)
            if os.path.exists(filepath):
                try: os.remove(filepath)
                except: pass
            raise Exception(f"فشل تحميل ملف القصة: {e}")

    def cleanup(self, path_or_list):
        if not path_or_list: return
        if isinstance(path_or_list, list):
            for p in path_or_list:
                if os.path.exists(p): os.remove(p)
            if path_or_list:
                parent = os.path.dirname(path_or_list[0])
                if os.path.basename(parent).startswith("temp_") and os.path.exists(parent):
                    shutil.rmtree(parent, ignore_errors=True)
        else:
            if os.path.exists(path_or_list):
                try: os.remove(path_or_list)
                except: pass
