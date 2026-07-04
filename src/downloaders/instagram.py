"""
downloaders/instagram.py - وحدة تحميل Instagram المطورة
تستخدم Instaloader لدعم الألبومات (Carousel) بدقة عالية.
"""
import os
import time
import logging
import shutil
import instaloader
import requests as _requests
import random

import config
from data import database
from .base import BaseDownloader

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

class InstagramDownloader(BaseDownloader):
    """وحدة تحميل Instagram باستخدام Instaloader."""

    def __init__(self, download_path: str = None):
        super().__init__(download_path)
        # التأكد من أن المسار مطلق لـ Instaloader
        self.abs_download_path = os.path.abspath(self.download_path)
        os.makedirs(self.abs_download_path, exist_ok=True)
        
        self.L = instaloader.Instaloader(
            download_pictures=True,
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            user_agent=_USER_AGENT,
            # سيتم وضع المجلدات داخل المجلد الرئيسي مباشرة
            dirname_pattern=os.path.join(self.abs_download_path, "{target}"),
            filename_pattern="{shortcode}"
        )
        
        # تحميل الكوكيز النشطة الحالية
        self._load_active_cookie()

    def _write_cookie_file(self, cookies_list: list) -> None:
        """تحويل الكوكيز النشطة وحفظها بتنسيق Netscape لـ yt-dlp و Instaloader."""
        import urllib.parse
        lines = ["# Netscape HTTP Cookie File", "# Generated dynamically during rotation", ""]
        for c in cookies_list:
            domain = c.get("domain", ".instagram.com")
            include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
            path   = c.get("path", "/")
            secure = "TRUE" if c.get("secure") else "FALSE"
            expiry = int(c.get("expirationDate", 0))
            name   = c["name"]
            value  = urllib.parse.unquote(c["value"])
            
            line = f"{domain}\t{include_subdomains}\t{path}\t{secure}\t{expiry}\t{name}\t{value}"
            lines.append(line)
            
        content = "\n".join(lines) + "\n"
        
        os.makedirs(os.path.dirname(config.INSTAGRAM_COOKIES), exist_ok=True)
        with open(config.INSTAGRAM_COOKIES, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            
        secrets_path = os.path.join(config.SECRETS_DIR, "instagram_cookies.txt")
        os.makedirs(os.path.dirname(secrets_path), exist_ok=True)
        with open(secrets_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)

    def _load_active_cookie(self) -> bool:
        """جلب الكوكيز النشطة من قاعدة البيانات وتحديث الجلسة الحالية لـ Instaloader."""
        try:
            cookies_list = database.get_ig_cookies()
            if not cookies_list:
                logger.warning("⚠️ No Instagram cookies found in database. Checking for local text file to import...")
                import urllib.parse
                cookie_file = None
                for path in [config.INSTAGRAM_COOKIES, os.path.join(config.SECRETS_DIR, "instagram_cookies.txt")]:
                    if os.path.exists(path) and os.path.getsize(path) > 100:
                        cookie_file = path
                        break
                
                if cookie_file:
                    logger.info("📥 Found existing cookie file: %s. Importing to database...", cookie_file)
                    parsed_cookies = []
                    ds_user_id = "imported_account"
                    with open(cookie_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith("#"):
                                continue
                            parts = line.split("\t")
                            if len(parts) >= 7:
                                name = parts[5]
                                value = parts[6]
                                if name == "ds_user_id":
                                    ds_user_id = value
                                parsed_cookies.append({
                                    "domain": parts[0],
                                    "hostOnly": parts[1].lower() == "true",
                                    "path": parts[2],
                                    "secure": parts[3].lower() == "true",
                                    "expirationDate": float(parts[4]) if parts[4].replace('.','',1).isdigit() else 0.0,
                                    "name": name,
                                    "value": value
                                })
                    if parsed_cookies:
                        username = ds_user_id
                        status = "working"
                        try:
                            cookies_dict = {c["name"]: urllib.parse.unquote(c["value"]) for c in parsed_cookies}
                            headers = {
                                "User-Agent": _USER_AGENT,
                                "Accept": "*/*",
                                "X-IG-App-ID": "936619743392459",
                                "X-Requested-With": "XMLHttpRequest",
                            }
                            url_check = "https://www.instagram.com/api/v1/accounts/edit/web_current_user/"
                            r = _requests.get(url_check, cookies=cookies_dict, headers=headers, timeout=10)
                            if r.status_code == 200:
                                username = r.json().get("form_data", {}).get("username", ds_user_id)
                            else:
                                status = "expired"
                        except Exception as check_err:
                            logger.warning("Could not verify imported cookies username: %s", check_err)
                        
                        database.add_ig_cookie(username, parsed_cookies, status=status, is_active=True)
                        logger.info("✅ Imported cookies for @%s to database with status: %s", username, status)
                        cookies_list = database.get_ig_cookies()

            if not cookies_list:
                logger.warning("⚠️ No Instagram cookies found in database after check.")
                return False
            
            # البحث عن الكوكيز النشطة، أو أول كوكيز شغال
            active_cookie = None
            for c in cookies_list:
                if c.get("is_active"):
                    active_cookie = c
                    break
            
            if not active_cookie:
                for c in cookies_list:
                    if c.get("status") == "working":
                        active_cookie = c
                        break
            
            if not active_cookie and cookies_list:
                active_cookie = cookies_list[0]
            
            if not active_cookie:
                logger.warning("⚠️ No working or active Instagram cookies found in DB.")
                return False
            
            # كتابة الكوكيز النشطة في الملفات
            self._write_cookie_file(active_cookie["cookies"])
            
            # تحديث جلسة Instaloader
            import http.cookiejar
            cj = http.cookiejar.MozillaCookieJar(config.INSTAGRAM_COOKIES)
            cj.load(ignore_discard=True, ignore_expires=True)
            
            self.L.context._session.cookies.clear()
            self.L.context._session.cookies.update(cj)
            
            # استخراج ds_user_id وتعيينه كاسم مستخدم السياق لـ Instaloader لإثبات تسجيل الدخول
            ds_user_id = None
            for cookie in cj:
                if cookie.name == "ds_user_id":
                    ds_user_id = cookie.value
                    break
            if ds_user_id:
                self.L.context.username = ds_user_id
            
            logger.info("✅ Successfully loaded Instagram cookies for account: @%s", active_cookie.get("username"))
            return True
        except Exception as e:
            logger.error("⚠️ Error loading active cookie: %s", e)
            return False

    def _set_random_proxy(self):
        try:
            proxies = database.get_proxies()
            if proxies:
                proxy = random.choice(proxies)
                if not proxy.startswith(("http://", "https://", "socks5://", "socks4://")):
                    proxy = f"http://{proxy}"
                self.L.context._session.proxies = {"http": proxy, "https": proxy}
                logger.info("📡 [Instaloader] Set random proxy: %s", proxy)
            else:
                self.L.context._session.proxies = {}
        except Exception as pe:
            logger.warning("⚠️ Failed to set proxy for Instaloader: %s", pe)
            self.L.context._session.proxies = {}

    def download_video(self, url: str) -> dict:
        """تحميل منشور (فيديو، صورة، أو ألبوم) مع تدوير تلقائي للكوكيز المتعددة عند الفشل."""
        shortcode = self._get_shortcode(url)
        if not shortcode:
            raise ValueError("رابط Instagram غير صالح أو غير مدعوم")

        # جلب جميع الكوكيز المتاحة للتدوير في حال الفشل
        all_cookies = database.get_ig_cookies()
        working_cookies = [c for c in all_cookies if c.get("status") == "working"]
        if not working_cookies and all_cookies:
            # استخدام الحساب النشط أو أي حساب كخيار أخير
            working_cookies = [c for c in all_cookies if c.get("is_active")]
            if not working_cookies:
                working_cookies = all_cookies
        
        # ترتيب الكوكيز النشط في البداية
        working_cookies.sort(key=lambda x: 1 if x.get("is_active") else 0, reverse=True)
        
        cookie_attempts = working_cookies if working_cookies else [None]
        last_error = None
        
        for attempt_idx, cookie_data in enumerate(cookie_attempts):
            if cookie_data:
                logger.info("🔄 Instagram Download: Attempt %d using account @%s (status: %s)", attempt_idx + 1, cookie_data["username"], cookie_data.get("status"))
                self._write_cookie_file(cookie_data["cookies"])
                
                # تحديث جلسة Instaloader الحالية
                import http.cookiejar
                cj = http.cookiejar.MozillaCookieJar(config.INSTAGRAM_COOKIES)
                cj.load(ignore_discard=True, ignore_expires=True)
                self.L.context._session.cookies.clear()
                self.L.context._session.cookies.update(cj)
                for cookie in cj:
                    if cookie.name == "ds_user_id":
                        self.L.context.username = cookie.value
                        break
            else:
                logger.info("Direct download attempt without cookies")

            # ── 1. محاولة التحميل عبر yt-dlp (الأسرع والأفضل) ──
            try:
                opts = {}
                if os.path.exists(config.INSTAGRAM_COOKIES) and cookie_data:
                    opts["cookiefile"] = config.INSTAGRAM_COOKIES
                    
                res = self._download(url, extra_opts=opts)
                if res and os.path.exists(res["results"]) and not res["results"].lower().endswith(".na"):
                    logger.info("✅ [yt-dlp] Download success via @%s", cookie_data["username"] if cookie_data else "direct")
                    return {"results": res["results"], "description": res["description"]}
            except Exception as yt_err:
                err_str = str(yt_err).lower()
                logger.warning("⚠️ [yt-dlp] Attempt failed: %s", yt_err)
                
                # الكوكيز غير صالحة أو تم تقييدها
                if cookie_data and any(kw in err_str for kw in ["login required", "empty media response", "400: bad request", "rate limit"]):
                    logger.warning("⚠️ Cookie @%s is invalid/expired! Updating status in DB.", cookie_data["username"])
                    database.update_ig_cookie_status(cookie_data["username"], "expired")
                last_error = yt_err

            # ── 2. محاولة التحميل الاحتياطية عبر Instaloader ──
            try:
                self._set_random_proxy()
                target_name = f"temp_{shortcode}_{int(time.time())}_{attempt_idx}"
                target_dir = os.path.join(self.abs_download_path, target_name)
                
                logger.info("📥 [Instaloader] Fetching post: %s", shortcode)
                post = instaloader.Post.from_shortcode(self.L.context, shortcode)
                description = post.caption or ""
                
                logger.info("📥 [Instaloader] Downloading to folder: %s", target_name)
                self.L.download_post(post, target=target_name)
                
                if not os.path.exists(target_dir) and os.path.exists(target_name):
                    target_dir = os.path.abspath(target_name)
                    
                media_files = []
                if os.path.exists(target_dir):
                    for f in os.listdir(target_dir):
                        if f.lower().endswith(('.jpg', '.jpeg', '.png', '.mp4')):
                            media_files.append(os.path.join(target_dir, f))
                            
                if media_files:
                    media_files.sort()
                    if len(media_files) == 1:
                        final_path = os.path.join(self.abs_download_path, f"insta_{shortcode}_{int(time.time())}{os.path.splitext(media_files[0])[1]}")
                        shutil.copy2(media_files[0], final_path)
                        shutil.rmtree(target_dir, ignore_errors=True)
                        return {"results": final_path, "description": description}
                    
                    logger.info("✅ [Instaloader] Success: %d items", len(media_files))
                    return {"results": media_files, "description": description}
            except Exception as inst_err:
                logger.warning("⚠️ [Instaloader] Attempt failed: %s", inst_err)
                if cookie_data and "login" in str(inst_err).lower():
                    database.update_ig_cookie_status(cookie_data["username"], "expired")
                last_error = inst_err
                if 'target_dir' in locals() and os.path.exists(target_dir):
                    shutil.rmtree(target_dir, ignore_errors=True)

        raise ValueError(f"⚠️ تعذّر تحميل هذا المنشور. قد يكون مقيداً أو تم حظر الكوكيز حالياً. يرجى مراجعة لوحة التحكم.")

    def _get_shortcode(self, url: str) -> str:
        parts = [p for p in url.split("/") if p]
        for i, p in enumerate(parts):
            if p in ("p", "reels", "reel") and i + 1 < len(parts):
                return parts[i+1].split("?")[0]
        return None

    def get_active_stories(self, username: str) -> list[dict]:
        """جلب قائمة القصص النشطة لمستخدم معين."""
        self._load_active_cookie()
        proxies = []
        try:
            proxies = database.get_proxies()
        except Exception as pe:
            logger.warning("⚠️ Error fetching proxies from database: %s", pe)

        attempts = []
        if proxies:
            sampled = random.sample(proxies, min(len(proxies), 3))
            for p in sampled:
                p_str = p.strip()
                if p_str:
                    if not p_str.startswith(("http://", "https://", "socks5://", "socks4://")):
                        p_str = f"http://{p_str}"
                    attempts.append(p_str)
        attempts.append(None) # محاولة بالاتصال المباشر

        from instaloader.exceptions import ProfileNotExistsException, PrivateProfileNotFollowedException

        last_error = None
        profile_not_found_count = 0  # عدد مرات خطأ "البروفايل غير موجود" (قد يكون بسبب rate limit)
        for i, proxy in enumerate(attempts):
            try:
                if proxy:
                    self.L.context._session.proxies = {"http": proxy, "https": proxy}
                    logger.info("📡 [Instaloader] Stories fetch attempt %d: Using proxy: %s", i + 1, proxy)
                else:
                    self.L.context._session.proxies = {}
                    logger.info("📡 [Instaloader] Stories fetch attempt %d: Using direct connection", i + 1)
                
                logger.info("📥 [Instaloader] Fetching profile stories for: %s", username)
                profile = instaloader.Profile.from_username(self.L.context, username)
                
                stories_items = []
                for story in self.L.get_stories(userids=[profile.userid]):
                    for item in story.get_items():
                        stories_items.append({
                            "media_id": item.mediaid,
                            "is_video": item.is_video,
                            "url": item.video_url if item.is_video else item.url,
                            "date": item.date_utc.strftime("%Y-%m-%d %H:%M:%S")
                        })
                # ترتيب من الأقدم للأحدث
                stories_items.sort(key=lambda x: x["date"])
                return stories_items
            except PrivateProfileNotFollowedException:
                # حساب خاص - خطأ نهائي لا يستفيد من إعادة المحاولة
                logger.warning("⚠️ Profile %s is private", username)
                raise ValueError("هذا الحساب خاص (Private)، لا يمكن للبوت جلب قصصه.")
            except ProfileNotExistsException:
                # قد يكون بسبب rate limit وليس لأن الحساب غير موجود - نستمر بالمحاولة
                profile_not_found_count += 1
                logger.warning("⚠️ [Instaloader] Attempt %d: Profile %s not found (may be rate limit)", i + 1, username)
                last_error = Exception(f"Profile {username} not found")
            except Exception as e:
                last_error = e
                logger.warning("⚠️ [Instaloader] Stories fetch attempt %d failed for user %s: %s", i + 1, username, e)

        # إذا كانت جميع المحاولات فشلت بـ "Profile not found" → الحساب لا يملك قصصاً أو خاص
        if profile_not_found_count == len(attempts):
            raise ValueError("لا توجد قصص نشطة لهذا الحساب حالياً، أو أن الحساب خاص.")

        raise Exception(f"فشل جلب القصص للحساب {username} بعد تجربة البروكسيات والاتصال المباشر. قد يكون الحساب خاصاً أو ملف الكوكيز منتهي الصلاحية. التفاصيل: {last_error}")


    def download_story_url(self, url: str, is_video: bool) -> str:
        """تحميل قصة فردية مباشرة من رابط الـ CDN الخاص بإنستغرام."""
        self._load_active_cookie()
        import uuid
        ext = ".mp4" if is_video else ".jpg"
        filename = f"story_{uuid.uuid4()}{ext}"
        filepath = os.path.join(self.abs_download_path, filename)
        
        proxies = []
        try:
            proxies = database.get_proxies()
        except:
            pass

        attempts = []
        if proxies:
            sampled = random.sample(proxies, min(len(proxies), 3))
            for p in sampled:
                p_str = p.strip()
                if p_str:
                    if not p_str.startswith(("http://", "https://", "socks5://", "socks4://")):
                        p_str = f"http://{p_str}"
                    attempts.append(p_str)
        attempts.append(None)

        last_error = None
        for i, proxy in enumerate(attempts):
            try:
                if proxy:
                    self.L.context._session.proxies = {"http": proxy, "https": proxy}
                    logger.info("📡 [Instaloader] Story download attempt %d: Using proxy: %s", i + 1, proxy)
                else:
                    self.L.context._session.proxies = {}
                    logger.info("📡 [Instaloader] Story download attempt %d: Using direct connection", i + 1)

                response = self.L.context._session.get(url, stream=True, timeout=15)
                response.raise_for_status()
                with open(filepath, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                return filepath
            except Exception as e:
                last_error = e
                logger.warning("⚠️ [Instaloader] Story download attempt %d failed: %s", i + 1, e)
                if os.path.exists(filepath):
                    try: os.remove(filepath)
                    except: pass

        raise Exception(f"فشل تحميل ملف القصة بعد تجربة البروكسيات والاتصال المباشر: {last_error}")

    def cleanup(self, path_or_list):
        if not path_or_list: return
        if isinstance(path_or_list, list):
            for p in path_or_list:
                if os.path.exists(p): os.remove(p)
            if path_or_list:
                parent = os.path.dirname(path_or_list[0])
                if os.path.basename(parent).startswith("temp_") and os.path.exists(parent):
                    shutil.rmtree(parent, ignore_errors=True)
        else:
            if os.path.exists(path_or_list):
                try: os.remove(path_or_list)
                except: pass
