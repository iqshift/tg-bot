"""
downloaders/instagram.py - وحدة تحميل Instagram
يدعم: فيديوهات + صور + Carousel
الميزات:
  - كوكيز للمصادقة
  - Proxy Rotation تلقائي عند rate-limit
"""
import os
import random
import logging
import requests as _requests

import config
from .base import BaseDownloader

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# كلمات مفتاحية تشير لحظر Instagram
_RATE_LIMIT_KEYWORDS = (
    "rate-limit",
    "rate limit",
    "login required",
    "Requested content is not available",
    "Please wait a few minutes",
)


def _is_rate_limited(error_msg: str) -> bool:
    """هل الخطأ بسبب rate-limit أو حظر Instagram؟"""
    msg = error_msg.lower()
    return any(kw.lower() in msg for kw in _RATE_LIMIT_KEYWORDS)


def _load_proxies() -> list[str]:
    """تحميل قائمة البروكسيات العاملة من الملف."""
    path = config.PROXY_LIST_FILE
    if not os.path.exists(path):
        logger.warning("⚠️ ملف البروكسيات غير موجود: %s", path)
        return []
    proxies = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                proxies.append(line)
    logger.info("📡 تم تحميل %d بروكسي من %s", len(proxies), path)
    return proxies


class InstagramDownloader(BaseDownloader):
    """وحدة تحميل مقاطع وصور Instagram مع Proxy Rotation."""

    def download_video(self, url: str) -> str:
        opts = {"user_agent": _USER_AGENT}

        if os.path.exists(config.INSTAGRAM_COOKIES):
            logger.info("✅ كوكيز Instagram موجودة")
            opts["cookiefile"] = config.INSTAGRAM_COOKIES
        else:
            logger.warning("⚠️ كوكيز Instagram غير موجودة: %s", config.INSTAGRAM_COOKIES)

        # ─── محاولة 1: بدون بروكسي ────────────────────────────────────────────
        try:
            return self._try_download(url, opts)
        except Exception as exc:
            err = str(exc)

            # إذا كانت صورة → حمّلها مباشرة (بدون بروكسي)
            if "No video formats found" in err:
                logger.info("📷 منشور صورة - جاري التحميل المباشر...")
                return self._download_image(url, opts)

            # إذا كان rate-limit → جرّب البروكسيات
            if _is_rate_limited(err):
                logger.warning("🚫 Instagram rate-limit! جاري تجربة البروكسيات...")
                return self._download_with_proxy_rotation(url, opts)

            raise

    def _try_download(self, url: str, opts: dict) -> str:
        """محاولة تحميل بالخيارات المعطاة."""
        return self._download(url, extra_opts=opts)

    def _download_with_proxy_rotation(self, url: str, opts: dict) -> str:
        """تدوير البروكسيات حتى ينجح التحميل."""
        proxies = _load_proxies()
        if not proxies:
            raise ValueError(
                "🚫 Instagram محجوب مؤقتاً ولا توجد بروكسيات - "
                "حدّث working_socks5.txt أو انتظر قليلاً"
            )

        # خلط العشوائي لتوزيع الحِمل
        random.shuffle(proxies)

        last_error = None
        for i, proxy in enumerate(proxies, 1):
            proxy_opts = {**opts, "proxy": proxy}
            logger.info("🔄 [%d/%d] تجربة: %s", i, len(proxies), proxy)
            try:
                result = self._try_download(url, proxy_opts)
                logger.info("✅ نجح مع البروكسي: %s", proxy)
                return result
            except Exception as exc:
                err = str(exc)
                # إذا كانت صورة عبر البروكسي
                if "No video formats found" in err:
                    return self._download_image(url, proxy_opts)
                last_error = exc
                logger.debug("❌ فشل البروكسي %s: %s", proxy, exc)
                continue

        raise ValueError(
            f"🚫 فشل جميع البروكسيات ({len(proxies)}) - "
            f"قد تكون القائمة قديمة، شغّل check_proxies.py مجدداً.\n"
            f"آخر خطأ: {last_error}"
        )

    def _download_image(self, url: str, opts: dict) -> str:
        """تحميل صورة Instagram باستخدام yt-dlp لاستخراج الرابط."""
        import yt_dlp

        ydl_opts = {**opts, "quiet": True, "no_warnings": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        # أعلى جودة للصورة
        image_url = None
        thumbnails = sorted(
            info.get("thumbnails") or [],
            key=lambda x: x.get("width") or 0,
            reverse=True,
        )
        if thumbnails:
            image_url = thumbnails[0].get("url")
        if not image_url:
            image_url = info.get("thumbnail")
        if not image_url:
            raise ValueError("لم يتم العثور على محتوى قابل للتحميل")

        os.makedirs(config.DOWNLOADS_DIR, exist_ok=True)
        shortcode = url.rstrip("/").split("/")[-2] if "/" in url else "instagram"
        file_path = os.path.join(config.DOWNLOADS_DIR, f"{shortcode}.jpg")

        response = _requests.get(
            image_url, headers={"User-Agent": _USER_AGENT}, timeout=30
        )
        response.raise_for_status()

        with open(file_path, "wb") as f:
            f.write(response.content)

        logger.info("✅ تم تحميل الصورة: %s", file_path)
        return file_path
