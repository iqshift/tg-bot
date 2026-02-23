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

    def download_video(self, url: str) -> dict:
        """تحميل منشور (فيديو، صورة، أو ألبوم)."""
        shortcode = self._get_shortcode(url)
        if not shortcode:
            raise ValueError("رابط Instagram غير صالح أو غير مدعوم")

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
                raise ValueError("فشل التحميل: لم يتم العثور على ملفات وسائط")

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
            
            # Fallback
            logger.info("🔄 Falling back to yt-dlp...")
            try:
                res = super().download_video(url)
                if os.path.exists(res["file_path"]) and not res["file_path"].lower().endswith(".na"):
                    return {"results": res["file_path"], "description": res["description"]}
            except: pass
            
            raise ValueError(f"⚠️ خطأ في تحميل المنشور: {str(e)}")

    def _get_shortcode(self, url: str) -> str:
        parts = [p for p in url.split("/") if p]
        for i, p in enumerate(parts):
            if p in ("p", "reels", "reel") and i + 1 < len(parts):
                return parts[i+1].split("?")[0]
        return None

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
