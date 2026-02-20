"""
config.py - الإعدادات المركزية للمشروع
يتم قراءة الإعدادات من مجلد secrets/
"""
import os

# ─── المسارات الأساسية ────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
SECRETS_DIR = os.path.join(BASE_DIR, "secrets")


def _read_secret(filename: str, default: str = "") -> str:
    """قراءة قيمة من ملف نصي في مجلد secrets/ (يتجاهل الأسطر الفارغة والتعليقات)."""
    path = os.path.join(SECRETS_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except FileNotFoundError:
        pass
    return default


# ─── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN: str = _read_secret("token.txt")
PROXY_URL: str      = _read_secret("proxy.txt")        # اختياري

# ─── Database ─────────────────────────────────────────────────────────────────
DB_PATH: str = os.path.join(BASE_DIR, "data", "users.db")

# ─── Downloads ────────────────────────────────────────────────────────────────
DOWNLOADS_DIR: str = os.path.join(BASE_DIR, "downloads")

# ─── Cookies (في مجلد secrets/) ───────────────────────────────────────────────
INSTAGRAM_COOKIES: str = os.path.join(SECRETS_DIR, "instagram_cookies.txt")
TIKTOK_COOKIES: str    = os.path.join(SECRETS_DIR, "tiktok_cookies.txt")

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_FILE: str = os.path.join(BASE_DIR, "logs", "bot.log")

# ─── Validation ───────────────────────────────────────────────────────────────
if not TELEGRAM_TOKEN:
    raise ValueError("❌ التوكن غير موجود - ضع التوكن في ملف secrets/token.txt")
