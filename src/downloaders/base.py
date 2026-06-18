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

import config

logger = logging.getLogger(__name__)

# ─── خيارات yt-dlp الأساسية المحسّنة للسرعة ─────────────────────────────────
_BASE_OPTS = {
    "format":           "best[ext=mp4]/best",
    "noplaylist":       True,
    "quiet":            True,
    "no_warnings":      True,
    "restrictfilenames": True,
    "socket_timeout":   15,
    "retries":          3,
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
        opts = {
            **_BASE_OPTS,
            "outtmpl": f"{self.download_path}/{filename}.%(ext)s",
        }
        if extra_opts:
            opts.update(extra_opts)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                file_path = ydl.prepare_filename(info)
                # استخراج الوصف أو العنوان
                description = info.get("description") or info.get("title") or ""
                return {
                    "results": file_path,
                    "description": description
                }
        except Exception as exc:
            err_msg = str(exc)
            if "HTTP Error 403" in err_msg:
                err_msg = "فشل الوصول (403): قد يكون الموقع حظر السيرفر مؤقتاً."
            elif "HTTP Error 429" in err_msg:
                err_msg = "طلب مكثف (429): تم تقييد السيرفر، يرجى الانتظار قليلاً."
            logger.error("خطأ في التحميل: %s", err_msg)
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
