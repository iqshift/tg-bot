"""
downloaders/facebook.py - وحدة تحميل Facebook
"""
import logging

import os
import config

from .base import BaseDownloader

logger = logging.getLogger(__name__)

# User-Agent يحاكي متصفح iPhone للتوافق مع Facebook
_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.6 Mobile/15E148 Safari/604.1"
)


class FacebookDownloader(BaseDownloader):
    """وحدة تحميل مقاطع وقصص Facebook."""

    def download_video(self, url: str) -> dict:
        opts = {"user_agent": _USER_AGENT}

        if os.path.exists(config.FACEBOOK_COOKIES):
            logger.info("✅ تم العثور على ملف كوكيز Facebook")
            opts["cookiefile"] = config.FACEBOOK_COOKIES
        else:
            logger.info("ℹ️ ملف كوكيز Facebook غير موجود - سيتم المحاولة بدونه")

        try:
            return self._download(url, extra_opts=opts)
        except Exception as exc:
            err_msg = str(exc)
            if "stories" in url.lower():
                raise Exception("عذراً، فشل تحميل القصة. قد يكون هذا الحساب خاصاً ويقيد من يمكنهم مشاهدة القصة 🔒")
            raise Exception(err_msg)
