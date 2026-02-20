"""
downloaders/instagram.py - وحدة تحميل Instagram
تستخدم ملف الكوكيز في data/cookies/instagram_cookies.txt
"""
import os
import logging

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
    """وحدة تحميل مقاطع Instagram."""

    def download_video(self, url: str) -> str:
        opts = {"user_agent": _USER_AGENT}

        if os.path.exists(config.INSTAGRAM_COOKIES):
            logger.info("✅ تم العثور على ملف كوكيز Instagram")
            opts["cookiefile"] = config.INSTAGRAM_COOKIES
        else:
            logger.warning(
                "⚠️ ملف كوكيز Instagram غير موجود في: %s", config.INSTAGRAM_COOKIES
            )

        return self._download(url, extra_opts=opts)
