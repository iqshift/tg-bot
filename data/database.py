"""
data/database.py - طبقة قاعدة البيانات (هجين)
  - Google Firestore  → المستخدمون + الإعدادات + البروكسيات + الأخطاء  (دائم)
  - SQLite محلي       → سجل المحادثات فقط                              (مؤقت / سريع)
"""
import datetime
import logging
import sqlite3
import threading

import config
from google.cloud import firestore

logger = logging.getLogger(__name__)

# ─── Firestore Client (Singleton) ────────────────────────────────────────────
_db: firestore.Client | None = None
_db_lock    = threading.Lock()
_cache_lock = threading.Lock()
_settings_cache: dict = {}


def _get_db() -> firestore.Client:
    """إنشاء اتصال Firestore مرة واحدة وإعادة استخدامه."""
    global _db
    if _db is None:
        with _db_lock:
            if _db is None:
                _db = firestore.Client()
                logger.info("🔥 Firestore client created")
    return _db


# ─── اختصارات Collections (Firestore) ───────────────────────────────────────
def _col_users():    return _get_db().collection("users")
def _col_settings(): return _get_db().collection("settings")
def _col_errors():   return _get_db().collection("error_logs")
def _col_whitelist(): return _get_db().collection("whitelist")


# ─── SQLite للمحادثات (مؤقت / سريع) ──────────────────────────────────────────
_sqlite_local = threading.local()
_sqlite_write_lock = threading.Lock()


def _get_sqlite():
    """اتصال SQLite مخصص لكل خيط للمحادثات فقط."""
    import os
    if not hasattr(_sqlite_local, "conn") or _sqlite_local.conn is None:
        os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
        conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER,
                message_type TEXT,
                message_text TEXT,
                timestamp    TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_user ON messages(user_id, timestamp)")
        conn.commit()
        _sqlite_local.conn = conn
    return _sqlite_local.conn


# ─── القيم الافتراضية ─────────────────────────────────────────────────────────
_DEFAULTS = {
    "welcome_msg":       "أهلاً بك في بوت التحميل. أرسل الرابط فقط.",
    "help_msg":          "أرسل رابط الفيديو من انستجرام، فيسبوك، أو تيك توك.",
    "msg_analyzing":     "جاري تحليل الرابط... 🔍",
    "msg_routing":       "تم توجيه الطلب إلى وحدة: {platform}... 🔄",
    "msg_complete":      "تم التحميل بنجاح. جاري الرفع... 📤",
    "msg_error":         "عذراً، فشل التحميل. (الوحدة: {platform}) ❌\nDetailed Error: {error}",
    "msg_banned":        "⛔ عذراً، أنت محظور من استخدام البوت.",
    "msg_caption":       "المصدر: {platform}",
    "required_channels": "",
    "msg_force_sub":     "🚫 يجب الاشتراك في:\n\n{channels}\n\nثم أرسل الرابط مرة أخرى.",
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
    """
    تهيئة Firestore - يضيف الإعدادات الافتراضية إذا لم تكن موجودة.
    (INSERT OR IGNORE behavior)
    """
    settings = _col_settings()
    for key, val in _DEFAULTS.items():
        doc_ref = settings.document(key)
        if not doc_ref.get().exists:
            doc_ref.set({"value": val})
            logger.info("⚙️ تهيئة الإعداد: %s", key)
    logger.info("✅ Firestore جاهز")


# ─── المستخدمون ──────────────────────────────────────────────────────────────
def get_user(user_id: int) -> dict | None:
    doc = _col_users().document(str(user_id)).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["user_id"] = user_id
    return data


def upsert_user(user_id: int, username: str, first_name: str, photo_url: str = "") -> None:
    now     = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    doc_ref = _col_users().document(str(user_id))
    doc     = doc_ref.get()
    if doc.exists:
        doc_ref.update({
            "username":    username,
            "first_name":  first_name,
            "last_active": now,
            "photo_url":   photo_url,
        })
    else:
        doc_ref.set({
            "user_id":     user_id,
            "username":    username,
            "first_name":  first_name,
            "joined_date": now,
            "last_active": now,
            "is_banned":   False,
            "photo_url":   photo_url,
        })


def ban_user(user_id: int, banned: bool) -> None:
    _col_users().document(str(user_id)).update({"is_banned": banned})


def get_all_users() -> list[dict]:
    docs = _col_users().stream()
    result = []
    for d in docs:
        data = d.to_dict()
        data["user_id"] = int(d.id)
        result.append(data)
    return result


# ─── الرسائل (SQLite - مؤقت/سريع) ──────────────────────────────────────────
def log_message(user_id: int, message_type: str, message_text: str) -> None:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _sqlite_write_lock:
        conn = _get_sqlite()
        conn.execute(
            "INSERT INTO messages (user_id, message_type, message_text, timestamp) VALUES (?,?,?,?)",
            (user_id, message_type, message_text, now),
        )
        conn.commit()


def get_user_messages(user_id: int, limit: int = 50) -> list[dict]:
    conn   = _get_sqlite()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM messages WHERE user_id=? ORDER BY timestamp DESC LIMIT ?",
        (user_id, limit),
    )
    return [dict(r) for r in reversed(cursor.fetchall())]


# ─── الإعدادات ───────────────────────────────────────────────────────────────
def get_setting(key: str, default: str = "") -> str:
    with _cache_lock:
        if key in _settings_cache:
            return _settings_cache[key]
    doc = _col_settings().document(key).get()
    val = doc.to_dict().get("value", default) if doc.exists else default
    with _cache_lock:
        _settings_cache[key] = val
    return val


def set_setting(key: str, value: str) -> None:
    _col_settings().document(key).set({"value": value})
    with _cache_lock:
        _settings_cache[key] = value


# ─── الإحصائيات ──────────────────────────────────────────────────────────────
def get_stats() -> dict:
    users   = [d.to_dict() for d in _col_users().stream()]
    total   = len(users)
    banned  = sum(1 for u in users if u.get("is_banned", False))
    threshold = (
        datetime.datetime.now() - datetime.timedelta(hours=24)
    ).strftime("%Y-%m-%d %H:%M:%S")
    active_24h   = sum(1 for u in users if u.get("last_active", "") >= threshold)
    total_errors    = sum(1 for _ in _col_errors().limit(9999).stream())
    whitelist_count = sum(1 for _ in _col_whitelist().limit(9999).stream())
    return {
        "total_users":     total,
        "banned_users":    banned,
        "active_24h":      active_24h,
        "total_errors":    total_errors,
        "whitelist_count": whitelist_count,
    }


# ─── سجل الأخطاء ─────────────────────────────────────────────────────────────
def log_error(user_id: int | None, platform: str, url: str, error_msg: str) -> None:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _col_errors().add({
        "user_id":   user_id,
        "platform":  platform,
        "url":       url,
        "error_msg": error_msg,
        "timestamp": now,
    })


def get_errors(limit: int = 100) -> list[dict]:
    docs = (
        _col_errors()
        .order_by("timestamp", direction=firestore.Query.DESCENDING)
        .limit(limit)
        .stream()
    )
    return [d.to_dict() for d in docs]


def clear_errors() -> None:
    for doc in _col_errors().stream():
        doc.reference.delete()


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
    doc = _col_whitelist().document(str(user_id)).get()
    return doc.to_dict() if doc.exists else None


def add_to_whitelist(user_id: int, custom_reply: str = "") -> None:
    _col_whitelist().document(str(user_id)).set({
        "user_id":      user_id,
        "custom_reply": custom_reply,
        "added_at":     datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


def remove_from_whitelist(user_id: int) -> None:
    _col_whitelist().document(str(user_id)).delete()


def is_whitelisted(user_id: int) -> bool:
    return _col_whitelist().document(str(user_id)).get().exists


def get_all_whitelist() -> list[dict]:
    docs = _col_whitelist().stream()
    return [d.to_dict() for d in docs]
