"""
downloaders/base.py - الفئة الأساسية لوحدات التحميل
التحسينات:
  - socket_timeout و retries لتقليل الانتظار
  - حذف البيانات الوصفية غير الضرورية
  - noprogress لتقليل الـ I/O
"""
import yt_dlp
import os
import uuid
import logging
import random

import config
from data import database

logger = logging.getLogger(__name__)

# ─── خيارات yt-dlp الأساسية المحسّنة للسرعة ─────────────────────────────────
_BASE_OPTS = {
    "format":           "best[ext=mp4]/best",
    "noplaylist":       True,
    "quiet":            True,
    "no_warnings":      True,
    "restrictfilenames": True,
    "socket_timeout":   15,
    "retries":          2,
    "noprogress":       True,
    "user_agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "check_formats":    False,
}


class BaseDownloader:
    """الفئة الأساسية لجميع وحدات التحميل."""

    def __init__(self, download_path: str = None):
        self.download_path = download_path or config.DOWNLOADS_DIR
        os.makedirs(self.download_path, exist_ok=True)

    def _download(self, url: str, extra_opts: dict = None) -> dict:
        filename = str(uuid.uuid4())
        base_opts = {
            **_BASE_OPTS,
            "outtmpl": f"{self.download_path}/{filename}.%(ext)s",
        }
        if extra_opts:
            base_opts.update(extra_opts)

        # جلب قائمة البروكسيات من قاعدة البيانات
        proxies = []
        try:
            proxies = database.get_proxies()
        except Exception as pe:
            logger.warning("⚠️ Error fetching proxies from database: %s", pe)

        # تجهيز محاولات الاتصال بالترتيب
        # محاولتين ببروكسيات عشوائية + محاولة أخيرة بدون بروكسي (اتصال مباشر)
        attempts = []
        if proxies:
            sampled = random.sample(proxies, min(len(proxies), 2))
            for p in sampled:
                p_str = p.strip()
                if p_str:
                    if not p_str.startswith(("http://", "https://", "socks5://", "socks4://")):
                        p_str = f"http://{p_str}"
                    attempts.append(p_str)
        attempts.append(None) # الاتصال المباشر

        last_error = None
        for i, proxy in enumerate(attempts):
            opts = base_opts.copy()
            if proxy:
                opts["proxy"] = proxy
                logger.info("📡 [yt-dlp] Attempt %d: Using proxy: %s", i + 1, proxy)
            else:
                logger.info("📡 [yt-dlp] Attempt %d: Using direct connection (no proxy)", i + 1)

            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    file_path = ydl.prepare_filename(info)
                    description = info.get("description") or info.get("title") or ""
                    return {
                        "results": file_path,
                        "description": description
                    }
            except Exception as exc:
                last_error = exc
                logger.warning("⚠️ [yt-dlp] Attempt %d failed: %s", i + 1, exc)

        # إذا فشلت جميع المحاولات
        err_msg = str(last_error)
        if "HTTP Error 403" in err_msg:
            err_msg = "فشل الوصول (403): قد يكون الموقع حظر السيرفر مؤقتاً."
        elif "HTTP Error 429" in err_msg:
            err_msg = "طلب مكثف (429): تم تقييد السيرفر، يرجى الانتظار قليلاً."
        logger.error("خطأ في التحميل بعد جميع المحاولات: %s", err_msg)
        raise Exception(err_msg)

    def download_video(self, url: str) -> dict:
        return self._download(url)

    def cleanup(self, file_path: str) -> None:
        """حذف الملف فوراً بعد الإرسال."""
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError as e:
                logger.warning("تعذّر حذف الملف %s: %s", file_path, e)
