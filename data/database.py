"""
data/database.py - طبقة قاعدة البيانات SQLite
التحسينات:
  - WAL mode → قراءات متزامنة بدون blocking
  - Connection pool بسيط مع threading.local
  - Pragmas للسرعة القصوى
"""
import sqlite3
import datetime
import threading
import logging

import config

logger = logging.getLogger(__name__)

# ─── Local Connection per Thread (أفضل من قفل واحد) ─────────────────────────
_local = threading.local()
_write_lock = threading.Lock()  # قفل للكتابة فقط


def _get_conn() -> sqlite3.Connection:
    """اتصال مخصص لكل خيط مع تفعيل WAL وPragmas للسرعة."""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(
            config.DB_PATH,
            check_same_thread=False,
            timeout=10,
        )
        conn.row_factory = sqlite3.Row
        # ─── WAL: يسمح بالقراءة أثناء الكتابة ───────────────────────────────
        conn.execute("PRAGMA journal_mode=WAL")
        # ─── سرعة أعلى (أمان مقبول) ─────────────────────────────────────────
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-8000")   # 8 MB cache
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=67108864") # 64 MB mmap
        _local.conn = conn
    return _local.conn


# ─── تهيئة قاعدة البيانات ───────────────────────────────────────────────────
def init_db() -> None:
    import os
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)

    with _write_lock:
        conn   = _get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                first_name  TEXT,
                joined_date TEXT,
                last_active TEXT,
                is_banned   INTEGER DEFAULT 0,
                photo_url   TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER,
                message_type TEXT,
                message_text TEXT,
                timestamp    TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # ─── Index للسرعة ───────────────────────────────────────────────────
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_active ON users(last_active)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, timestamp)")

        # ─── جدول سجل الأخطاء ────────────────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS error_logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                platform   TEXT,
                url        TEXT,
                error_msg  TEXT,
                timestamp  TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_errors_ts ON error_logs(timestamp)")

        defaults = {
            "welcome_msg":      "أهلاً بك في بوت التحميل. أرسل الرابط فقط.",
            "help_msg":         "أرسل رابط الفيديو من انستجرام، فيسبوك، أو تيك توك.",
            "msg_analyzing":    "جاري تحليل الرابط... 🔍",
            "msg_routing":      "تم توجيه الطلب إلى وحدة: {platform}... 🔄",
            "msg_complete":     "تم التحميل بنجاح. جاري الرفع... 📤",
            "msg_error":        "عذراً، فشل التحميل. (الوحدة: {platform}) ❌\nDetailed Error: {error}",
            "msg_banned":       "⛔ عذراً، أنت محظور من استخدام البوت.",
            "msg_caption":      "المصدر: {platform}",
            "required_channels": "",
            "msg_force_sub":    "🚫 يجب الاشتراك في:\n\n{channels}\n\nثم أرسل الرابط مرة أخرى.",
            # ─── بروكسيات افتراضية (HTTP) - تُستخدم إذا لم تُضف بروكسيات من لوحة التحكم ───
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
        for key, val in defaults.items():
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, val))

        _ensure_column(cursor, "users",    "is_banned",     "INTEGER DEFAULT 0")
        _ensure_column(cursor, "users",    "photo_url",     "TEXT")
        _ensure_column(cursor, "messages", "message_type",  "TEXT")
        _ensure_column(cursor, "messages", "message_text",  "TEXT")

        conn.commit()
        logger.info("قاعدة البيانات جاهزة (WAL mode): %s", config.DB_PATH)


def _ensure_column(cursor, table: str, column: str, definition: str) -> None:
    try:
        cursor.execute(f"SELECT {column} FROM {table} LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


# ─── عمليات المستخدمين (قراءة بدون قفل، كتابة بقفل) ────────────────────────
def upsert_user(user_id: int, username: str, first_name: str, photo_url: str = None) -> None:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _write_lock:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO users (user_id, username, first_name, joined_date, last_active, is_banned, photo_url)
               VALUES (?, ?, ?, ?, ?, 0, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 username=excluded.username, first_name=excluded.first_name,
                 last_active=excluded.last_active, photo_url=excluded.photo_url""",
            (user_id, username, first_name, now, now, photo_url),
        )
        conn.commit()


def get_user(user_id: int) -> dict | None:
    conn   = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_all_users() -> list[dict]:
    conn   = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY last_active DESC")
    return [dict(r) for r in cursor.fetchall()]


def set_ban_status(user_id: int, is_banned: bool) -> None:
    with _write_lock:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_banned=? WHERE user_id=?", (1 if is_banned else 0, user_id))
        conn.commit()


# ─── عمليات الرسائل ────────────────────────────────────────────────────────
def log_message(user_id: int, message_type: str, message_text: str) -> None:
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _write_lock:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO messages (user_id, message_type, message_text, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, message_type, message_text, timestamp),
        )
        conn.commit()


def get_user_messages(user_id: int, limit: int = 50) -> list[dict]:
    conn   = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM messages WHERE user_id=? ORDER BY timestamp DESC LIMIT ?",
        (user_id, limit),
    )
    return [dict(r) for r in reversed(cursor.fetchall())]


# ─── عمليات الإعدادات (مخزّنة في الذاكرة cache) ────────────────────────────
_settings_cache: dict = {}
_cache_lock = threading.Lock()


def get_setting(key: str, default: str = "") -> str:
    with _cache_lock:
        if key in _settings_cache:
            return _settings_cache[key]
    conn   = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cursor.fetchone()
    val = row[0] if row else default
    with _cache_lock:
        _settings_cache[key] = val
    return val


def set_setting(key: str, value: str) -> None:
    with _write_lock:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute("REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
    with _cache_lock:
        _settings_cache[key] = value  # تحديث الـ cache


# ─── الإحصائيات ────────────────────────────────────────────────────────────
def get_stats() -> dict:
    conn   = _get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned=1")
    banned = cursor.fetchone()[0]
    time_24h = (datetime.datetime.now() - datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("SELECT COUNT(*) FROM users WHERE last_active >= ?", (time_24h,))
    active_24h = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM error_logs")
    total_errors = cursor.fetchone()[0]
    return {"total_users": total, "banned_users": banned, "active_24h": active_24h, "total_errors": total_errors}


# ─── سجل الأخطاء ─────────────────────────────────────────────────────────────
def log_error(user_id: int | None, platform: str, url: str, error_msg: str) -> None:
    """تسجيل خطأ في قاعدة البيانات."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _write_lock:
        conn   = _get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO error_logs (user_id, platform, url, error_msg, timestamp) VALUES (?, ?, ?, ?, ?)",
            (user_id, platform, url, error_msg, timestamp),
        )
        conn.commit()


def get_errors(limit: int = 100) -> list[dict]:
    """جلب آخر الأخطاء المسجلة."""
    conn   = _get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM error_logs ORDER BY timestamp DESC LIMIT ?", (limit,)
    )
    return [dict(r) for r in cursor.fetchall()]


def clear_errors() -> None:
    """مسح جميع سجلات الأخطاء."""
    with _write_lock:
        conn   = _get_conn()
        conn.execute("DELETE FROM error_logs")
        conn.commit()


# ─── إدارة البروكسيات (مخزّنة في settings) ──────────────────────────────────
_PROXY_SETTING_KEY = "proxy_list"


def get_proxies() -> list[str]:
    """جلب قائمة البروكسيات من قاعدة البيانات."""
    raw = get_setting(_PROXY_SETTING_KEY, "")
    if not raw:
        return []
    return [p.strip() for p in raw.splitlines() if p.strip()]


def set_proxies(proxies: list[str]) -> None:
    """حفظ قائمة البروكسيات في قاعدة البيانات (بدون تكرار)."""
    unique = list(dict.fromkeys(p.strip() for p in proxies if p.strip()))
    # إبطال الـ cache يدوياً لأن البروكسيات تتغير كثيراً
    with _cache_lock:
        _settings_cache.pop(_PROXY_SETTING_KEY, None)
    set_setting(_PROXY_SETTING_KEY, "\n".join(unique))


def remove_proxy(proxy: str) -> None:
    """حذف بروكسي واحد من القائمة."""
    proxies = get_proxies()
    updated = [p for p in proxies if p != proxy.strip()]
    if len(updated) < len(proxies):
        set_proxies(updated)
