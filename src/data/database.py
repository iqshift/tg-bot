import datetime
import logging
import threading
import os

import config
from google.cloud import firestore

logger = logging.getLogger(__name__)

# ─── Firestore Client (Singleton) ────────────────────────────────────────────
_db: firestore.Client | None = None
_db_lock    = threading.Lock()
_cache_lock = threading.Lock()
_settings_cache: dict = {}


def _get_db() -> firestore.Client:
    """إنشاء اتصال Firestore مرة واحدة وإعادة استخدامه، مع دعم ملف الاعتمادات."""
    global _db
    if _db is None:
        with _db_lock:
            if _db is None:
                try:
                    # محاولة استخدام ملف الاعتمادات إذا وجد في secrets/
                    cred_path = os.path.join(config.SECRETS_DIR, "service_account.json")
                    if os.path.exists(cred_path):
                        _db = firestore.Client.from_service_account_json(cred_path)
                        logger.info("🔥 Firestore client created using service_account.json")
                    else:
                        # التحقق مما إذا كنا في بيئة التطوير المحلية بدون ملف اعتمادات لمنع التعليق (Hanging)
                        if not os.environ.get("K_SERVICE") and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
                            logger.warning("⚠️ Running locally without credentials. Skipping Firestore to prevent hanging.")
                            return None
                        _db = firestore.Client()
                        logger.info("🔥 Firestore client created successfully (ADC)")
                except Exception as e:
                    logger.error(f"❌ Firestore Initialization Failed: {e}")
                    logger.warning("⚠️ Application will continue without persistent database storage.")
                    return None
    return _db


# ─── اختصارات Collections (Firestore) ───────────────────────────────────────
def _get_col(name):
    db = _get_db()
    return db.collection(name) if db else None

def _col_users():    return _get_col("users")
def _col_settings(): return _get_col("settings")
def _col_errors():   return _get_col("error_logs")
def _col_whitelist(): return _get_col("whitelist")
def _col_usage():     return _get_col("usage_stats")


# ─── عداد الاستهلاك (Quota Tracking) ──────────────────────────────────────────
def _track_usage(reads: int = 0, writes: int = 0, deletes: int = 0):
    """تتبع استهلاك العمليات في Firestore لليوم الحالي بشكل محصن."""
    try:
        col = _col_usage()
        if not col: return
        
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        doc_ref = col.document(today)
        
        data = {}
        if reads > 0:   data["reads"]   = firestore.Increment(reads)
        if writes > 0:  data["writes"]  = firestore.Increment(writes)
        if deletes > 0: data["deletes"] = firestore.Increment(deletes)
        
        if data:
            data["last_update"] = firestore.SERVER_TIMESTAMP
            doc_ref.set(data, merge=True)
    except Exception as e:
        logger.debug(f"Usage tracking skipped: {e}")

def get_usage_today() -> dict:
    """جلب إحصائيات الاستهلاك لليوم الحالي."""
    col = _col_usage()
    if not col: return {"reads": 0, "writes": 0, "deletes": 0}
    
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        doc = col.document(today).get()
        if doc.exists:
            return doc.to_dict()
    except:
        pass
    return {"reads": 0, "writes": 0, "deletes": 0}


# ─── SQLite (تم استبداله بـ JSON) ──────────────────────────────────────────


# ─── القيم الافتراضية ─────────────────────────────────────────────────────────
_DEFAULTS = {
    "welcome_msg":       "أهلاً بك في بوت التحميل. أرسل الرابط فقط.",
    "help_msg":          "أرسل رابط الفيديو من انستجرام، فيسبوك، أو تيك توك.",
    "msg_analyzing":     "جاري تحليل الرابط... 🔍",
    "msg_routing":       "تم توجيه الطلب إلى وحدة: {platform}... 🔄",
    "msg_complete":      "تم التحميل بنجاح. جاري الرفع... 📤",
    "msg_error":         "عذراً، حدث خطأ بسبب زخم المستخدمين. يرجى المحاولة لاحقاً ❌",
    "msg_stories_error": "عذراً، حدث خطأ بسبب زخم المستخدمين. يرجى المحاولة لاحقاً ❌",
    "msg_banned":        "⛔ عذراً، أنت محظور من استخدام البوت.",
    "msg_caption":       "المصدر: {platform}",
    "required_channels": "",
    "msg_force_sub":     "🚫 يجب الاشتراك في:\n\n{channels}\n\nثم أرسل الرابط مرة أخرى.",
    "share_msg":          "هذا هو البوت الاحترافي للتحميل من منصات التواصل الاجتماعي! استعمله الآن مجاناً 🚀\n\n@ir4qibot",
    "share_btn_text":     "مشاركة البوت مع الأصدقاء 🔗",
    "telegram_token":     "",
    "webhook_url":        "",
    # ─── بروكسيات افتراضية (HTTP) ───────────────────────────────────────────
    "proxy_list": "\n".join([
        "217.217.254.94:8080",
        "104.238.30.40:59741",
        "188.130.160.209:80",
        "104.238.30.86:63900",
        "45.65.138.48:999",
        "104.238.30.63:63744",
        "91.238.104.172:2024",
        "104.238.30.68:63744",
        "211.230.49.122:3128",
        "185.41.152.110:3128",
        "104.238.30.37:59741",
        "104.238.30.45:59741",
        "116.80.77.99:7777",
        "104.238.30.38:59741",
        "185.145.124.173:8080",
        "90.84.188.97:8000",
        "81.177.48.54:2080",
        "72.56.59.23:61937",
        "211.171.114.154:3128",
        "72.56.59.62:63133",
        "20.210.113.32:8123",
        "150.230.249.50:1080",
        "165.227.5.10:8888",
        "178.130.47.129:1082",
        "104.248.198.6:8080",
        "190.242.157.215:8080",
        "178.253.22.108:65431",
        "72.56.50.17:59787",
        "216.229.112.25:8080",
        "157.230.220.25:4857",
        "91.238.104.171:2023",
        "91.200.163.190:8088",
        "102.207.191.68:8080",
        "195.158.8.123:3128",
        "172.86.92.68:31337",
        "104.238.30.91:63900",
        "36.95.61.186:8080",
        "178.252.165.122:8080",
        "103.55.22.236:8080",
        "85.133.227.150:80",
        "46.173.211.221:12880",
        "202.152.44.19:8081",
        "179.61.98.3:999",
        "43.161.214.161:1081",
        "72.56.59.17:61931",
        "104.238.30.50:59741",
        "217.28.18.4:8104",
        "45.127.56.194:83",
        "104.238.30.39:59741",
        "109.120.135.230:2030",
        "138.117.85.217:999",
        "136.49.32.180:8888",
        "72.56.59.56:63127",
    ]),
}


# ─── تهيئة قاعدة البيانات ────────────────────────────────────────────────────
def init_db() -> None:
    """تهيئة Firestore - يضيف الإعدادات الافتراضية بشكل محسّن وقليل الاستهلاك."""
    col = _col_settings()
    if col is None: return

    try:
        # جلب الإعدادات الموجودة دفعة واحدة لتقليل القراءات (عملية واحدة بدلاً من 20)
        existing_docs = {d.id for d in col.stream()}
        _track_usage(reads=1) # قراءة واحدة للـ stream
        
        writes = 0
        for key, val in _DEFAULTS.items():
            if key not in existing_docs:
                col.document(key).set({"value": val})
                writes += 1
        
        if writes > 0:
            _track_usage(writes=writes)
        logger.info("✅ Database initialized (Firestore)")
    except Exception as e:
        logger.error(f"Error during init_db: {e}")
    logger.info("✅ Firestore جاهز")


# ─── المستخدمون ──────────────────────────────────────────────────────────────
def get_user(user_id: int) -> dict | None:
    col = _col_users()
    if col is None: return None
    _track_usage(reads=1)
    doc = col.document(str(user_id)).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["user_id"] = user_id
    return data


def upsert_user(user_id: int, username: str, first_name: str, photo_url: str = "", photo_file_id: str = "") -> None:
    col = _col_users()
    if col is None: return

    now_dt = datetime.datetime.now()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    doc_ref = col.document(str(user_id))
    try:
        _track_usage(reads=1)
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            # تحديث فوري إذا كان هناك تغيير في الاسم أو الصورة أو مر وقت كافٍ
            needs_update = (
                data.get("username") != username or 
                data.get("first_name") != first_name or 
                data.get("photo_url") != photo_url or
                data.get("photo_file_id") != photo_file_id
            )
            
            # إذا لم يتغير الاسم، نحدث تاريخ آخر ظهور فقط إذا مر أكثر من ساعة واحدة (بدلاً من 12) لزيادة الدقة
            if not needs_update:
                last_active_str = data.get("last_active", "")
                if last_active_str:
                    try:
                        last_dt = datetime.datetime.strptime(last_active_str, "%Y-%m-%d %H:%M:%S")
                        if (now_dt - last_dt).total_seconds() > 3600: # تحديث كل ساعة بدقة أعلى
                            needs_update = True
                    except:
                        needs_update = True
                else:
                    needs_update = True

            if needs_update:
                _track_usage(writes=1)
                doc_ref.update({
                    "username":      username,
                    "first_name":    first_name,
                    "last_active":   now_str,
                    "photo_url":     photo_url,
                    "photo_file_id": photo_file_id,
                })
        else:
            # مستخدم جديد (يظهر فوراً في لوحة التحكم)
            _track_usage(writes=1)
            doc_ref.set({
                "user_id":       user_id,
                "username":      username,
                "first_name":    first_name,
                "joined_date":   now_str,
                "last_active":   now_str,
                "is_banned":     False,
                "photo_url":     photo_url,
                "photo_file_id": photo_file_id,
            })
            logger.info(f"🆕 New user registered: {first_name} ({user_id})")
    except Exception as e:
        logger.error(f"Error in upsert_user: {e}")


def ban_user(user_id: int, banned: bool) -> None:
    _track_usage(writes=1)
    col = _col_users()
    if col: col.document(str(user_id)).update({"is_banned": banned})


def get_all_users() -> list[dict]:
    col = _col_users()
    if col is None: return []
    try:
        docs = col.stream()
        result = []
        for d in docs:
            data = d.to_dict()
            data["user_id"] = int(d.id)
            result.append(data)
        
        _track_usage(reads=len(result))
        return result
    except Exception as e:
        logger.error(f"Error fetching users: {e}")
        return []


# ─── الرسائل (JSON - محلي / مؤقت) ──────────────────────────────────────────
_messages_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "messages.json")
_messages_lock = threading.Lock()

def log_message(user_id: int, message_type: str, message_text: str) -> None:
    """حفظ رسالة في ملف JSON محلي (مؤقت)."""
    import json
    import os
    
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_msg = {
        "user_id": user_id,
        "type": message_type,
        "text": message_text,
        "timestamp": now_str
    }
    
    with _messages_lock:
        try:
            os.makedirs(os.path.dirname(_messages_file), exist_ok=True)
            msgs = []
            if os.path.exists(_messages_file):
                with open(_messages_file, "r", encoding="utf-8") as f:
                    try:
                        msgs = json.load(f)
                    except:
                        msgs = []
            
            msgs.append(new_msg)
            # الاحتفاظ بآخر 1000 رسالة فقط لضمان الخفة
            if len(msgs) > 1000:
                msgs = msgs[-1000:]
                
            with open(_messages_file, "w", encoding="utf-8") as f:
                json.dump(msgs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error logging to JSON: {e}")


def get_user_messages(user_id: int, limit: int = 50) -> list[dict]:
    """جلب رسائل مستخدم معين من ملف JSON."""
    import json
    import os
    
    with _messages_lock:
        if not os.path.exists(_messages_file):
            return []
        try:
            with open(_messages_file, "r", encoding="utf-8") as f:
                msgs = json.load(f)
                user_msgs = [m for m in msgs if m["user_id"] == user_id]
                # إرجاع النتائج بتنسيق SQLiterow المتوقع في لوحة التحكم
                return [
                    {
                        "user_id": m["user_id"],
                        "message_type": m["type"],
                        "message_text": m["text"],
                        "timestamp": m["timestamp"]
                    }
                    for m in user_msgs[-limit:]
                ]
        except:
            return []


# ─── الإعدادات ───────────────────────────────────────────────────────────────
def get_setting(key: str, default: str = "") -> str:
    # التحقق من الكاش أولاً
    with _cache_lock:
        if key in _settings_cache:
            return _settings_cache[key]
    
    # محاولة الجلب من Firestore
    col = _col_settings()
    val = default
    if col:
        try:
            _track_usage(reads=1)
            doc = col.document(key).get()
            if doc.exists:
                val = doc.to_dict().get("value", default)
        except Exception as e:
            logger.error(f"Firestore get_setting error: {e}")
    else:
        # إذا لم يتوفر Firestore، نستخدم القيم الافتراضية من الكود
        val = _DEFAULTS.get(key, default)

    with _cache_lock:
        _settings_cache[key] = val
    return val


def set_setting(key: str, value: str) -> bool:
    col = _col_settings()
    if col:
        try:
            _track_usage(writes=1)
            col.document(key).set({"value": value})
            with _cache_lock:
                _settings_cache[key] = value
            return True
        except Exception as e:
            logger.error(f"Firestore set_setting error: {e}")
    return False


# ─── الإحصائيات ──────────────────────────────────────────────────────────────
# ─── تخزين مؤقت للإحصائيات (Stats Caching) ──────────────────────────────────
_stats_cache: dict | None = None
_stats_last_fetch: datetime.datetime | None = None

def get_stats() -> dict:
    """إرجاع الإحصائيات مع استخدام ذاكرة مؤقتة لتقليل تكاليف القراءة."""
    global _stats_cache, _stats_last_fetch
    
    now = datetime.datetime.now()
    if _stats_cache and _stats_last_fetch:
        if (now - _stats_last_fetch).total_seconds() < 1800:
            return _stats_cache

    col_u = _col_users()
    if not col_u:
        return {"total_users": 0, "banned_users": 0, "active_24h": 0, "total_errors": 0, "whitelist_count": 0, "db_status": "OFFLINE"}

    try:
        users_stream = col_u.stream()
        users_list = []
        for d in users_stream:
            users_list.append(d.to_dict())
        
        _track_usage(reads=len(users_list))
        
        total   = len(users_list)
        banned  = sum(1 for u in users_list if u.get("is_banned", False))
        
        threshold = (now - datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        active_24h = sum(1 for u in users_list if u.get("last_active", "") >= threshold)
        
        err_list = list(_col_errors().limit(1000).stream()) if _col_errors() else []
        whitelist_list = list(_col_whitelist().limit(1000).stream()) if _col_whitelist() else []
        _track_usage(reads=len(err_list) + len(whitelist_list))
        
        total_errors    = len(err_list)
        whitelist_count = len(whitelist_list)
        
        _stats_cache = {
            "total_users":     total,
            "banned_users":    banned,
            "active_24h":      active_24h,
            "total_errors":    total_errors,
            "whitelist_count": whitelist_count,
            "cached_at":       now.strftime("%H:%M:%S"),
            "db_status":       "ONLINE"
        }
        _stats_last_fetch = now
        return _stats_cache
        
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        return _stats_cache or {"total_users": 0, "banned_users": 0, "active_24h": 0, "total_errors": 0, "whitelist_count": 0, "db_status": "ERROR"}


# ─── سجل الأخطاء ─────────────────────────────────────────────────────────────
def log_error(user_id: int | None, platform: str, url: str, error_msg: str) -> None:
    col = _col_errors()
    if col is None: return
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        _track_usage(writes=1)
        col.add({
            "user_id":   user_id,
            "platform":  platform,
            "url":       url,
            "error_msg": error_msg,
            "timestamp": now,
        })
    except: pass


def get_errors(limit: int = 100) -> list[dict]:
    col = _col_errors()
    if col is None: return []
    try:
        docs_stream = (
            col
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        results = [d.to_dict() for d in docs_stream]
        _track_usage(reads=len(results))
        return results
    except: return []


def clear_errors() -> None:
    col = _col_errors()
    if col:
        count = 0
        for doc in col.stream():
            doc.reference.delete()
            count += 1
        _track_usage(reads=count, deletes=count)


# ─── إدارة البروكسيات ────────────────────────────────────────────────────────
_PROXY_KEY = "proxy_list"


def get_proxies() -> list[str]:
    raw = get_setting(_PROXY_KEY, "")
    return [p.strip() for p in raw.splitlines() if p.strip()] if raw else []


def set_proxies(proxies: list[str]) -> None:
    unique = list(dict.fromkeys(p.strip() for p in proxies if p.strip()))
    with _cache_lock:
        _settings_cache.pop(_PROXY_KEY, None)
    set_setting(_PROXY_KEY, "\n".join(unique))


def remove_proxy(proxy: str) -> None:
    proxies = get_proxies()
    updated = [p for p in proxies if p != proxy.strip()]
    if len(updated) < len(proxies):
        set_proxies(updated)
# ─── القائمة البيضاء ──────────────────────────────────────────────────────────
def get_whitelisted(user_id: int) -> dict | None:
    col = _col_whitelist()
    if col:
        _track_usage(reads=1)
        doc = col.document(str(user_id)).get()
        return doc.to_dict() if doc.exists else None
    return None


def add_to_whitelist(user_id: int, custom_reply: str = "") -> None:
    col = _col_whitelist()
    if col:
        _track_usage(writes=1)
        col.document(str(user_id)).set({
            "user_id":      user_id,
            "custom_reply": custom_reply,
            "added_at":     datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })


def remove_from_whitelist(user_id: int) -> None:
    col = _col_whitelist()
    if col:
        _track_usage(deletes=1)
        col.document(str(user_id)).delete()


def is_whitelisted(user_id: int) -> bool:
    col = _col_whitelist()
    if col:
        _track_usage(reads=1)
        return col.document(str(user_id)).get().exists
    return False


def get_all_whitelist() -> list[dict]:
    col = _col_whitelist()
    if col:
        docs_stream = col.stream()
        results = [d.to_dict() for d in docs_stream]
        _track_usage(reads=len(results))
        return results
    return []


# ─── إدارة كوكيز إنستغرام المتعددة (Instagram Cookies Management) ───────────────
_IG_COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ig_cookies.json")
_ig_cookies_lock = threading.Lock()

def _get_local_ig_cookies() -> list[dict]:
    import json
    with _ig_cookies_lock:
        if not os.path.exists(_IG_COOKIES_FILE):
            return []
        try:
            with open(_IG_COOKIES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

def _save_local_ig_cookies(cookies: list[dict]) -> None:
    import json
    with _ig_cookies_lock:
        try:
            os.makedirs(os.path.dirname(_IG_COOKIES_FILE), exist_ok=True)
            with open(_IG_COOKIES_FILE, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving local IG cookies: {e}")

def get_ig_cookies() -> list[dict]:
    """جلب كل حسابات الكوكيز المضافة لإنستغرام."""
    db = _get_db()
    if db:
        try:
            col = db.collection("ig_cookies")
            docs = col.stream()
            results = []
            for d in docs:
                data = d.to_dict()
                data["username"] = d.id
                results.append(data)
            _track_usage(reads=max(1, len(results)))
            # مزامنة مع المحلي للاحتياط
            _save_local_ig_cookies(results)
            return results
        except Exception as e:
            logger.error(f"Firestore get_ig_cookies error: {e}")
    
    # fallback للملف المحلي
    return _get_local_ig_cookies()

def add_ig_cookie(username: str, cookies_list: list, status: str = "working", is_active: bool = False) -> bool:
    """إضافة كوكيز لحساب إنستغرام أو تحديثه."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = {
        "cookies": cookies_list,
        "status": status,
        "is_active": is_active,
        "last_checked": now_str
    }
    
    # إذا كان هذا الحساب نشطاً، يجب إلغاء نشاط بقية الحسابات
    if is_active:
        # إلغاء نشاط الباقين في المحلي أولاً
        local_items = _get_local_ig_cookies()
        for item in local_items:
            item["is_active"] = False
        _save_local_ig_cookies(local_items)
        
        # إلغاء في Firestore
        db = _get_db()
        if db:
            try:
                col = db.collection("ig_cookies")
                for d in col.where("is_active", "==", True).stream():
                    d.reference.update({"is_active": False})
                _track_usage(writes=1)
            except Exception as e:
                logger.error(f"Firestore deactivate others error: {e}")

    # إضافة/تحديث الحساب الحالي
    db = _get_db()
    if db:
        try:
            col = db.collection("ig_cookies")
            col.document(username).set(entry)
            _track_usage(writes=1)
        except Exception as e:
            logger.error(f"Firestore add_ig_cookie error: {e}")
            
    # تحديث الملف المحلي
    local_items = _get_local_ig_cookies()
    # حذف النسخة القديمة إن وجدت
    local_items = [item for item in local_items if item.get("username") != username]
    entry_local = entry.copy()
    entry_local["username"] = username
    local_items.append(entry_local)
    _save_local_ig_cookies(local_items)
    return True

def delete_ig_cookie(username: str) -> bool:
    """حذف حساب كوكيز معين."""
    db = _get_db()
    if db:
        try:
            col = db.collection("ig_cookies")
            col.document(username).delete()
            _track_usage(deletes=1)
        except Exception as e:
            logger.error(f"Firestore delete_ig_cookie error: {e}")
            
    # تحديث المحلي
    local_items = _get_local_ig_cookies()
    local_items = [item for item in local_items if item.get("username") != username]
    _save_local_ig_cookies(local_items)
    return True

def update_ig_cookie_status(username: str, status: str) -> bool:
    """تحديث حالة كوكيز معينة."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db = _get_db()
    if db:
        try:
            col = db.collection("ig_cookies")
            col.document(username).update({
                "status": status,
                "last_checked": now_str
            })
            _track_usage(writes=1)
        except Exception as e:
            logger.error(f"Firestore update_ig_cookie_status error: {e}")
            
    # تحديث المحلي
    local_items = _get_local_ig_cookies()
    for item in local_items:
        if item.get("username") == username:
            item["status"] = status
            item["last_checked"] = now_str
            break
    _save_local_ig_cookies(local_items)
    return True

def set_active_ig_cookie(username: str) -> bool:
    """تفعيل حساب كوكيز معين لإلغاء نشاط البقية واستخدامه كحساب رئيسي."""
    # تعيين الكل كـ False وتفعيل هذا فقط
    local_items = _get_local_ig_cookies()
    for item in local_items:
        item["is_active"] = (item.get("username") == username)
    _save_local_ig_cookies(local_items)
    
    db = _get_db()
    if db:
        try:
            col = db.collection("ig_cookies")
            # تعيين غير نشط للبقية
            for d in col.where("is_active", "==", True).stream():
                d.reference.update({"is_active": False})
            # تفعيل هذا
            col.document(username).update({"is_active": True})
            _track_usage(writes=2)
            return True
        except Exception as e:
            logger.error(f"Firestore set_active_ig_cookie error: {e}")
    return True

