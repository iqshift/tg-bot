"""
config.py - الإعدادات المركزية للمشروع
يتم قراءة الإعدادات من مجلد secrets/
"""
import os

# ─── المسارات الأساسية ────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
SECRETS_DIR = os.path.join(BASE_DIR, "secrets")


def _read_secret(filename: str, env_key: str = "", default: str = "") -> str:
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

def _write_secret(filename: str, value: str) -> bool:
    """كتابة القيمة في ملف في مجلد secrets/"""
    try:
        os.makedirs(SECRETS_DIR, exist_ok=True)
        path = os.path.join(SECRETS_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(value.strip())
        return True
    except Exception as e:
        print(f"❌ Error writing secret {filename}: {e}")
        return False


# ─── Telegram ─────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN_FILE = "token.txt"
WEBHOOK_URL_FILE    = "webhook_url.txt"

TELEGRAM_TOKEN: str = _read_secret(TELEGRAM_TOKEN_FILE, env_key="TELEGRAM_TOKEN")
PROXY_URL: str      = _read_secret("proxy.txt",         env_key="PROXY_URL")

# ─── Webhook ──────────────────────────────────────────────────────────────────
WEBHOOK_URL: str    = _read_secret(WEBHOOK_URL_FILE,    env_key="WEBHOOK_URL")
WEBHOOK_PORT: int   = int(os.environ.get("PORT", 8080))

# ─── Database ─────────────────────────────────────────────────────────────────
DB_PATH: str = os.path.join(BASE_DIR, "data", "users.db")

# ─── Downloads ────────────────────────────────────────────────────────────────
DOWNLOADS_DIR: str = os.path.join(BASE_DIR, "downloads")

# ─── Cookies (في data/cookies/ حتى يصلها Docker) ─────────────────────────────
COOKIES_DIR: str       = os.path.join(BASE_DIR, "data", "cookies")
INSTAGRAM_COOKIES: str = os.path.join(COOKIES_DIR, "instagram_cookies.txt")
TIKTOK_COOKIES: str    = os.path.join(COOKIES_DIR, "tiktok_cookies.txt")

# ─── Proxy Rotation (للتحايل على rate-limit Instagram) ───────────────────────
PROXY_LIST_FILE: str = os.path.join(BASE_DIR, "working_socks5.txt")


# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_FILE: str = os.path.join(BASE_DIR, "logs", "bot.log")

# ─── Validation ───────────────────────────────────────────────────────────────
if not TELEGRAM_TOKEN:
    print("⚠️ [CONFIG] Warning: TELEGRAM_TOKEN is not set. Bot features will be disabled until configured.")
