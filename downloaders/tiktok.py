"""
downloaders/tiktok.py - وحدة تحميل TikTok
تستخدم ملف الكوكيز في data/cookies/tiktok_cookies.txt (إذا وُجد)
"""
import os
import logging

import config
from .base import BaseDownloader

logger = logging.getLogger(__name__)


class TikTokDownloader(BaseDownloader):
    """وحدة تحميل مقاطع TikTok."""

    def download_video(self, url: str) -> str:
        opts = {}

        if os.path.exists(config.TIKTOK_COOKIES):
            logger.info("✅ تم العثور على ملف كوكيز TikTok")
            opts["cookiefile"] = config.TIKTOK_COOKIES
        else:
            logger.info("ℹ️ ملف كوكيز TikTok غير موجود - سيتم المحاولة بدونه")

        return self._download(url, extra_opts=opts)
