"""
downloaders/facebook.py - وحدة تحميل Facebook
"""
import logging

from .base import BaseDownloader

logger = logging.getLogger(__name__)

# User-Agent يحاكي متصفح iPhone للتوافق مع Facebook
_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.6 Mobile/15E148 Safari/604.1"
)


class FacebookDownloader(BaseDownloader):
    """وحدة تحميل مقاطع Facebook."""

    def download_video(self, url: str) -> dict:
        opts = {"user_agent": _USER_AGENT}
        return self._download(url, extra_opts=opts)
