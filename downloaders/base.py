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
    "quiet":            True,          # لا خروج للـ console (أسرع)
    "noprogress":       True,          # لا progress bar (يوفر I/O)
    "no_warnings":      True,
    "restrictfilenames": True,
    "socket_timeout":   15,            # timeout أسرع بدلاً من الانتظار
    "retries":          2,             # محاولتان فقط
    "fragment_retries": 2,
    "skip_unavailable_fragments": True,
    "writethumbnail":   False,         # لا صورة مصغرة
    "writesubtitles":   False,         # لا ترجمات
    "writeinfojson":    False,         # لا ملف معلومات
}


class BaseDownloader:
    """الفئة الأساسية لجميع وحدات التحميل."""

    def __init__(self, download_path: str = None):
        self.download_path = download_path or config.DOWNLOADS_DIR
        os.makedirs(self.download_path, exist_ok=True)

    def _download(self, url: str, extra_opts: dict = None) -> str:
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
                return ydl.prepare_filename(info)
        except Exception as exc:
            logger.error("خطأ في التحميل: %s", exc)
            raise

    def download_video(self, url: str) -> str:
        return self._download(url)

    def cleanup(self, file_path: str) -> None:
        """حذف الملف فوراً بعد الإرسال."""
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError as e:
                logger.warning("تعذّر حذف الملف %s: %s", file_path, e)
