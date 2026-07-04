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
            res = self._download(url, extra_opts=opts)
            if res and os.path.exists(res.get("results", "")) and not res.get("results", "").lower().endswith(".na"):
                return res
            raise ValueError("yt-dlp returned no valid results")
        except Exception as exc:
            logger.warning("⚠️ فشل yt-dlp في تحميل الرابط، محاولة الحل البديل عبر TikWM: %s", exc)
            
            # المحاولة الثانية عبر TikWM API
            tikwm_res = self._fallback_tikwm_download(url)
            if tikwm_res:
                return tikwm_res
                
            logger.warning("⚠️ فشل الحل البديل لـ TikWM، محاولة الحل البديل للصور من الصفحة")
            return self._fallback_photo_download(url)

    def _download_url_to_file(self, url: str, ext: str = ".mp4") -> str:
        filename = f"{uuid.uuid4()}{ext}"
        path = os.path.join(self.download_path, filename)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.tiktok.com/",
        }
        response = requests.get(url, headers=headers, stream=True, timeout=20)
        response.raise_for_status()
        with open(path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return path

    def _resolve_redirect(self, url: str) -> str:
        if not re.search(r"https?://(vt|vm)\.tiktok\.com/", url, re.IGNORECASE):
            return url
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            response = requests.head(url, headers=headers, allow_redirects=True, timeout=10)
            return response.url
        except Exception as e:
            logger.warning("⚠️ فشل في تتبع تحويل الرابط: %s", e)
            return url

    def _fallback_tikwm_download(self, url: str) -> dict | None:
        resolved_url = self._resolve_redirect(url)
        # إزالة معاملات الاستعلام من الرابط المحوّل لتفادي خطأ التحليل في TikWM
        if "?" in resolved_url:
            resolved_url = resolved_url.split("?")[0]
            
        logger.info("🔄 محاولة التحميل عبر TikWM API للرابط: %s (الرابط المحوّل والمُنظّف: %s)", url, resolved_url)
        try:
            res = requests.post("https://www.tikwm.com/api/", data={"url": resolved_url}, timeout=15)
            res.raise_for_status()
            data = res.json()
            if data.get("code") == 0:
                video_data = data.get("data") or {}
                title = video_data.get("title") or ""
                
                # التحقق مما إذا كان المنشور عبارة عن ألبوم صور (Slideshow)
                images = video_data.get("images")
                if images and isinstance(images, list) and len(images) > 0:
                    logger.info("📸 تم اكتشاف ألبوم صور (Slideshow) عبر TikWM")
                    file_paths = []
                    for img_url in images:
                        if img_url:
                            try:
                                path = self._download_url_to_file(img_url, ext=".jpg")
                                file_paths.append(path)
                            except Exception as e:
                                logger.warning("⚠️ فشل تحميل صورة من TikWM: %s", e)
                    if file_paths:
                        return {
                            "results": file_paths,
                            "description": title
                        }
                
                # تحميل مقطع الفيديو
                play_url = video_data.get("play")
                if play_url:
                    logger.info("📹 تم العثور على رابط فيديو عبر TikWM: %s", play_url)
                    path = self._download_url_to_file(play_url, ext=".mp4")
                    return {
                        "results": path,
                        "description": title
                    }
            else:
                logger.warning("⚠️ TikWM API returned error: %s", data.get("msg"))
        except Exception as e:
            logger.error("❌ فشل التحميل عبر TikWM API: %s", e)
        return None

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
            
            # البحث عن بيانات الصفحة (Rehydration Data هو الأساس)
            payload = None
            match = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>', response.text)
            if match:
                payload = json.loads(match.group(1))
            else:
                # محاولة البحث عن SIGI_STATE
                match_sigi = re.search(r'<script id="SIGI_STATE" type="application/json">(.*?)</script>', response.text)
                if match_sigi:
                    payload = json.loads(match_sigi.group(1))
                else:
                    # محاولة البحث عن RENDER_DATA
                    match_render = re.search(r'<script id="RENDER_DATA" type="application/json">(.*?)</script>', response.text)
                    if match_render:
                        from urllib.parse import unquote
                        payload = json.loads(unquote(match_render.group(1)))

            if not payload:
                raise ValueError("لم يتم العثور على بيانات الميتا (JSON) في صفحة TikTok.")
            
            data = payload
            
            # استخراج الـ imagePost
            image_post = self._find_key_recursive(data, "imagePost")
            if not image_post:
                # محاولة البحث عن كائنات الصور مباشرة في حال تغير المسار
                images_list = self._find_key_recursive(data, "images")
                if images_list and isinstance(images_list, list) and len(images_list) > 0:
                     image_post = {"images": images_list}
                else:
                     raise ValueError("هذا الرابط لا يحتوي على صور (أو تعذر العثور على مصفوفة الصور).")
            
            images = image_post.get("images", [])
            if not images and isinstance(image_post, list):
                images = image_post
                
            if not images:
                raise ValueError("لا توجد صور في مصفوفة الصور المستخرجة.")
                
            logger.info("📸 تم العثور على %d صورة في Slideshow", len(images))
            
            file_paths = []
            for img in images:
                if not isinstance(img, dict): continue
                
                # محاولة استخراج الرابط بالتفضيل: urlList ثم displayLink ثم downloadAddr
                img_url = None
                url_list = img.get("imageURL", {}).get("urlList", [])
                if url_list:
                    img_url = url_list[0]
                else:
                    img_url = img.get("displayLink") or img.get("downloadAddr")
                
                if img_url:
                    try:
                        path = self._download_file(img_url)
                        file_paths.append(path)
                    except Exception as e:
                        logger.warning("⚠️ فشل تحميل صورة واحدة: %s", e)
            
            # استخراج الوصف
            desc = self._extract_description_enhanced(data)

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

    def _extract_description_enhanced(self, data):
        """استخراج الوصف بطريقة أكثر مرونة."""
        # محاولة البحث عن desc في أماكن محتملة
        for key in ["desc", "caption", "title"]:
            found = self._find_key_recursive(data, key)
            if found and isinstance(found, str):
                return found
        return ""

    def get_user_videos(self, username: str, limit: int = 10) -> list:
        """جلب أحدث مقاطع فيديو مستخدم تيك توك عبر TikWM API."""
        # المحاولة الأولى: TikWM API
        try:
            r = requests.post(
                "https://www.tikwm.com/api/user/posts",
                data={"unique_id": username, "count": limit, "cursor": 0, "web": 1},
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            if data.get("code") == 0:
                videos = data.get("data", {}).get("videos") or []
                result = []
                for v in videos[:limit]:
                    vid_id = str(v.get("id", ""))
                    # استخدم رابط TikTok المباشر حتى يعمل مع yt-dlp وTikWM fallback بشكل طبيعي
                    result.append({
                        "id":       vid_id,
                        "title":    (v.get("title") or "بدون عنوان")[:50],
                        "is_video": True,
                        "duration": v.get("duration", 0),
                        "play_url": f"https://www.tiktok.com/@{username}/video/{vid_id}",
                    })
                if result:
                    logger.info("✅ TikWM returned %d videos for @%s", len(result), username)
                    return result
            logger.warning("⚠️ TikWM user posts empty/error for @%s: %s", username, data.get("msg"))
        except Exception as e:
            logger.warning("⚠️ TikWM user posts API failed: %s", e)

        # المحاولة الثانية: yt-dlp
        try:
            import yt_dlp
            opts = {
                "quiet":         True,
                "no_warnings":   True,
                "extract_flat":  True,
                "playlistend":   limit,
                "skip_download": True,
            }
            if os.path.exists(config.TIKTOK_COOKIES):
                opts["cookiefile"] = config.TIKTOK_COOKIES

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(
                    f"https://www.tiktok.com/@{username}", download=False
                )

            if info and info.get("entries"):
                result = []
                for entry in info["entries"][:limit]:
                    if not entry:
                        continue
                    vid_id = str(entry.get("id", ""))
                    result.append({
                        "id":       vid_id,
                        "title":    (entry.get("title") or "بدون عنوان")[:50],
                        "is_video": True,
                        "duration": entry.get("duration", 0),
                        "play_url": f"https://www.tiktok.com/@{username}/video/{vid_id}",
                    })
                if result:
                    logger.info("✅ yt-dlp returned %d videos for @%s", len(result), username)
                    return result
        except Exception as e:
            logger.warning("⚠️ yt-dlp user videos failed: %s", e)

        raise ValueError(
            f"لا يمكن الوصول إلى مقاطع فيديو الحساب @{username}. "
            "قد يكون الحساب خاصاً أو غير موجود، يرجى المحاولة لاحقاً."
        )

    def _download_file(self, url: str) -> str:
        """تحميل ملف وحفظه في مجلد التحميلات مع استخدام رؤوس طلبات صحيحة."""
        filename = f"{uuid.uuid4()}.jpg"
        path = os.path.join(self.download_path, filename)
        
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
            "Referer": "https://www.tiktok.com/",
        }
        
        response = requests.get(url, headers=headers, stream=True, timeout=10)
        response.raise_for_status()
        
        with open(path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return path
