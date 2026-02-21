"""
downloaders/instagram.py - وحدة تحميل Instagram
يدعم: فيديوهات + صور + Carousel (مجموعات مختلطة)
"""
import os
import logging
import requests

import config
from .base import BaseDownloader

logger = logging.getLogger(__name__)

# User-Agent يحاكي متصفح Chrome على Windows
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class InstagramDownloader(BaseDownloader):
    """وحدة تحميل مقاطع وصور Instagram."""

    def download_video(self, url: str) -> str:
        opts = {"user_agent": _USER_AGENT}

        if os.path.exists(config.INSTAGRAM_COOKIES):
            logger.info("✅ تم العثور على ملف كوكيز Instagram")
            opts["cookiefile"] = config.INSTAGRAM_COOKIES
        else:
            logger.warning(
                "⚠️ ملف كوكيز Instagram غير موجود في: %s", config.INSTAGRAM_COOKIES
            )

        try:
            return self._download(url, extra_opts=opts)
        except Exception as exc:
            # إذا كان المنشور صورة → نحمّل الصورة مباشرة
            if "No video formats found" in str(exc):
                logger.info("📷 لا يوجد فيديو - محاولة تحميل الصورة...")
                return self._download_image(url, opts)
            raise

    def _download_image(self, url: str, opts: dict) -> str:
        """تحميل صورة Instagram باستخدام yt-dlp لاستخراج الرابط ثم تحميله."""
        import yt_dlp

        # استخراج المعلومات بدون تحميل
        ydl_opts = {**opts, "quiet": True, "no_warnings": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        # البحث عن رابط الصورة بأعلى جودة
        image_url = None
        thumbnails = info.get("thumbnails") or []
        if thumbnails:
            # ترتيب حسب العرض تنازلياً لأخذ أعلى جودة
            thumbnails_sorted = sorted(
                thumbnails, key=lambda x: x.get("width") or 0, reverse=True
            )
            image_url = thumbnails_sorted[0].get("url")

        if not image_url:
            image_url = info.get("thumbnail")

        if not image_url:
            raise ValueError("لم يتم العثور على محتوى قابل للتحميل في هذا الرابط")

        # تحميل الصورة
        os.makedirs(config.DOWNLOADS_DIR, exist_ok=True)
        shortcode = url.rstrip("/").split("/")[-2] if "/" in url else "instagram"
        file_path = os.path.join(config.DOWNLOADS_DIR, f"{shortcode}.jpg")

        response = requests.get(
            image_url,
            headers={"User-Agent": _USER_AGENT},
            timeout=30,
        )
        response.raise_for_status()

        with open(file_path, "wb") as f:
            f.write(response.content)

        logger.info("✅ تم تحميل الصورة: %s", file_path)
        return file_path
