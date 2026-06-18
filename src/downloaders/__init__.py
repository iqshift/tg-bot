"""
downloaders - حزمة وحدات التحميل
"""
from .base import BaseDownloader
from .instagram import InstagramDownloader
from .facebook import FacebookDownloader
from .tiktok import TikTokDownloader

__all__ = [
    "BaseDownloader",
    "InstagramDownloader",
    "FacebookDownloader",
    "TikTokDownloader",
]
