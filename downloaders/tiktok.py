"""
downloaders/tiktok.py - وحدة تحميل TikTok
تستخدم ملف الكوكيز في data/cookies/tiktok_cookies.txt (إذا وُجد)
وتدعم تحميل الصور (Slideshow) في حال فشل yt-dlp.
"""
import os
import re
import json
import uuid
import logging
import requests

import config
from .base import BaseDownloader

logger = logging.getLogger(__name__)


class TikTokDownloader(BaseDownloader):
    """وحدة تحميل مقاطع وصور TikTok."""

    def download_video(self, url: str) -> dict:
        opts = {}

        if os.path.exists(config.TIKTOK_COOKIES):
            logger.info("✅ تم العثور على ملف كوكيز TikTok")
            opts["cookiefile"] = config.TIKTOK_COOKIES
        else:
            logger.info("ℹ️ ملف كوكيز TikTok غير موجود - سيتم المحاولة بدونه")

        try:
            # المحاولة الأولى باستخدام yt-dlp
            return self._download(url, extra_opts=opts)
        except Exception as exc:
            logger.warning("⚠️ فشل yt-dlp في تحميل الرابط، محاولة الحل البديل للصور: %s", exc)
            return self._fallback_photo_download(url)

    def _fallback_photo_download(self, url: str) -> dict:
        """حل بديل لتحميل صور تيك توك (Slideshow) عند فشل yt-dlp."""
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            
            # البحث عن بيانات الصفحة
            match = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>', response.text)
            if not match:
                raise ValueError("لم يتم العثور على بيانات Rehydration في الصفحة.")
            
            data = json.loads(match.group(1))
            
            # استخراج الـ imagePost
            image_post = self._find_key_recursive(data, "imagePost")
            if not image_post:
                raise ValueError("هذا الرابط لا يحتوي على صور (Photo Post).")
            
            images = image_post.get("images", [])
            if not images:
                raise ValueError("لا توجد صور في مصفوفة الصور.")
                
            logger.info("📸 تم العثور على %d صورة في Slideshow", len(images))
            
            file_paths = []
            for img in images:
                img_url = img.get("displayLink") or img.get("imageURL", {}).get("urlList", [None])[0]
                if img_url:
                    path = self._download_file(img_url)
                    file_paths.append(path)
            
            # استخراج الوصف
            desc = ""
            try:
                # محاولة استخراج الوصف من الهيكل المكتشف
                default_scope = data.get("__DEFAULT_SCOPE__", {})
                webapp_content = default_scope.get("webapp.video-detail", {})
                item_info = webapp_content.get("itemInfo", {}).get("itemStruct", {})
                desc = item_info.get("desc", "")
            except:
                pass

            return {
                "results": file_paths,
                "description": desc
            }
            
        except Exception as e:
            logger.error("❌ فشل الحل البديل لتحميل صور تيك توك: %s", e)
            raise Exception(f"عذراً، لم نتمكن من معالجة هذا الرابط: {e}")

    def _find_key_recursive(self, obj, target_key):
        """بحث عميق عن مفتاح معين في قاموس متداخل."""
        if isinstance(obj, dict):
            if target_key in obj:
                return obj[target_key]
            for v in obj.values():
                res = self._find_key_recursive(v, target_key)
                if res: return res
        elif isinstance(obj, list):
            for item in obj:
                res = self._find_key_recursive(item, target_key)
                if res: return res
        return None

    def _download_file(self, url: str) -> str:
        """تحميل ملف وحفظه في مجلد التحميلات."""
        filename = f"{uuid.uuid4()}.jpg"
        path = os.path.join(self.download_path, filename)
        
        response = requests.get(url, stream=True, timeout=10)
        response.raise_for_status()
        
        with open(path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return path
