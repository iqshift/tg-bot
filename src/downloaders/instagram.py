"""
downloaders/instagram.py - وحدة تحميل Instagram باستخدام SnapReels API.
تعتمد على جلب رابط التحميل وفك تشفير JWT Token للحصول على رابط Instagram CDN المباشر والتحميل منه.
"""
import os
import re
import json
import base64
import logging
import requests
import random
import uuid
from urllib.parse import urlparse, parse_qs

import config
from data import database
from .base import BaseDownloader

logger = logging.getLogger(__name__)

class InstagramDownloader(BaseDownloader):
    """وحدة تحميل مقاطع Instagram باستخدام SnapReels."""

    def get_download_link(self, video_url: str, session: requests.Session) -> str:
        """
        يجلب رابط تحميل الفيديو من snapreels.net باستخدام requests.
        """
        # الخطوة 1: احصل على JWT Token
        logger.info("[1/3] Getting JWT Token from /api/userverify...")
        verify_resp = session.post(
            "https://snapreels.net/api/userverify",
            data={"url": video_url},
            timeout=15
        )
        verify_resp.raise_for_status()
        verify_data = verify_resp.json()

        if not verify_data.get("success"):
            raise Exception(f"userverify failed: {verify_data}")

        jwt_token = verify_data["token"]
        logger.info("JWT Token obtained successfully.")

        # الخطوة 2: جلب رابط التحميل
        logger.info("[2/3] Fetching download link from /api/ajaxSearch...")
        search_resp = session.post(
            "https://snapreels.net/api/ajaxSearch",
            data={
                "q": video_url,
                "w": "",
                "lang": "en",
                "v": "v2",
                "cftoken": jwt_token,
            },
            timeout=20
        )
        search_resp.raise_for_status()
        search_data = search_resp.json()

        if search_data.get("status") != "ok":
            raise Exception(f"ajaxSearch failed: {search_data}")

        # استخرج أول رابط dl.snapcdn.app من الـ HTML المرجع
        html = search_data.get("data", "")
        links = re.findall(r'href="(https://dl\.snapcdn\.app/get\?token=[^"]+)"', html)
        if not links:
            # محاولة أخرى للبحث عن أي رابط تحميل بديل
            alt_links = re.findall(r'href="([^"]+)"', html)
            for link in alt_links:
                if "snapcdn.app" in link or "snapreels" in link:
                    return link
            raise Exception("No download link found in ajaxSearch response")

        return links[0]

    def decode_jwt_url(self, download_url: str) -> str:
        """
        يفك تشفير JWT Token من رابط snapcdn ويستخرج رابط Instagram CDN الحقيقي.
        """
        parsed = urlparse(download_url)
        token = parse_qs(parsed.query).get("token", [None])[0]
        if not token:
            raise Exception("No token found in download URL")

        parts = token.split(".")
        if len(parts) < 2:
            raise Exception("Invalid JWT format")

        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding

        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        real_url = payload.get("url")
        if not real_url:
            raise Exception("No 'url' field found in JWT payload")

        return real_url

    def download_video(self, url: str) -> dict:
        """
        يجلب رابط التحميل ويفك التشفير ويحمل الفيديو من Instagram CDN مباشرة.
        """
        # استخراج معرف المنشور/الريل كاسم للملف
        parts = [p for p in url.split("/") if p]
        shortcode = "video"
        for i, p in enumerate(parts):
            if p in ("p", "reels", "reel") and i + 1 < len(parts):
                shortcode = parts[i+1].split("?")[0]
                break

        filename = f"insta_{shortcode}_{uuid.uuid4().hex[:8]}.mp4"
        filepath = os.path.join(self.download_path, filename)

        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://snapreels.net/en",
            "Origin": "https://snapreels.net",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
        })

        # جلب البروكسيات للاستخدام في حال الفشل
        proxies = []
        try:
            proxies = database.get_proxies()
        except:
            pass

        attempts = [None]
        if proxies:
            attempts = [random.choice(proxies), None]

        last_error = None
        for proxy in attempts:
            if proxy:
                if not proxy.startswith(("http://", "https://", "socks5://", "socks4://")):
                    p_str = f"http://{proxy}"
                else:
                    p_str = proxy
                session.proxies = {"http": p_str, "https": p_str}
                logger.info(f"📡 Using proxy: {p_str}")
            else:
                session.proxies = {}
                logger.info("📡 Using direct connection")

            try:
                # 1. الحصول على رابط التحميل
                dl_link = self.get_download_link(url, session)
                
                # 2. فك التشفير والتحميل
                logger.info("[3/3] Decoding JWT to extract real Instagram CDN URL...")
                real_url = self.decode_jwt_url(dl_link)
                logger.info(f"Instagram CDN URL extracted: {real_url[:80]}...")

                # 3. تحميل الفيديو
                with requests.get(
                    real_url,
                    stream=True,
                    timeout=60,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept": "*/*",
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept-Encoding": "identity",
                        "Referer": "https://www.instagram.com/",
                        "sec-fetch-dest": "video",
                        "sec-fetch-mode": "no-cors",
                        "sec-fetch-site": "cross-site",
                        "Range": "bytes=0-",
                    }
                ) as resp:
                    resp.raise_for_status()
                    with open(filepath, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)

                # التأكد من صحة الملف وحجمه
                if os.path.exists(filepath) and os.path.getsize(filepath) > 1024:
                    logger.info("✅ Instagram video downloaded successfully via SnapReels API.")
                    return {"results": filepath, "description": ""}
                else:
                    if os.path.exists(filepath):
                        os.remove(filepath)
                    raise Exception("Downloaded file is too small or corrupted.")

            except Exception as e:
                last_error = e
                logger.warning(f"Attempt failed: {e}")
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except:
                        pass

        raise Exception(f"فشل تحميل الفيديو بعد المحاولات: {last_error}")

    def cleanup(self, path):
        if path and os.path.exists(path):
            try:
                os.remove(path)
                logger.info(f"Cleaned up file: {path}")
            except Exception as e:
                logger.error(f"Error cleaning up file {path}: {e}")
