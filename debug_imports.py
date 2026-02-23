import sys
import os

print("--- Testing Imports ---")
try:
    import psutil
    print("✅ psutil imported")
except ImportError as e:
    print(f"❌ psutil import failed: {e}")

try:
    import speedtest
    print("✅ speedtest imported")
except ImportError as e:
    print(f"❌ speedtest import failed: {e}")

try:
    from utils import server_utils
    print("✅ utils.server_utils imported")
except ImportError as e:
    print(f"❌ utils.server_utils import failed: {e}")

try:
    from web import server
    print("✅ web.server imported")
except ImportError as e:
    print(f"❌ web.server import failed: {e}")

print("--- End of Test ---")
