"""
config.py - الإعدادات المركزية للمشروع
يتم قراءة الإعدادات من مجلد secrets/
"""
import os

# ─── المسارات الأساسية ────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
SECRETS_DIR = os.path.join(BASE_DIR, "secrets")


def _read_secret(filename: str, env_key: str = "", default: str = "") -> str:
    """
    يقرأ القيمة بهذا الترتيب:
      1. متغير البيئة (Cloud Run / Docker env vars)
      2. ملف في secrets/ (VPS / محلي)
      3. القيمة الافتراضية
    """
    # 1. متغير البيئة
    if env_key and os.environ.get(env_key):
        return os.environ[env_key]
    # 2. ملف في secrets/
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
TELEGRAM_TOKEN: str = _read_secret("token.txt",       env_key="TELEGRAM_TOKEN")
PROXY_URL: str      = _read_secret("proxy.txt",       env_key="PROXY_URL")

# ─── Webhook ──────────────────────────────────────────────────────────────────
WEBHOOK_URL: str    = _read_secret("webhook_url.txt", env_key="WEBHOOK_URL")
WEBHOOK_PORT: int   = int(os.environ.get("PORT", 8080))

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
    raise ValueError("❌ التوكن غير موجود - ضع التوكن في secrets/token.txt أو env var TELEGRAM_TOKEN")
