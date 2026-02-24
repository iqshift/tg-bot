import os
import sys
import logging
import shutil

# إضافة المسار الحالي للمشروع
sys.path.append(os.getcwd())

from downloaders.instagram import InstagramDownloader
import config

# إعداد السجلات
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("TestInstagram")

def test_download():
    url = "https://www.instagram.com/p/DU0YVn6Fqb6/?img_index=2&igsh=a3NxYXRjOW1peWNh"
    downloader = InstagramDownloader()
    
    print(f"\n🚀 Testing Instagram URL: {url}\n" + "="*50)
    
    try:
        result = downloader.download_video(url)
        print("\n✅ Download Success!")
        print(f"📝 Description: {result.get('description')}")
        
        results = result.get("results", [])
        if isinstance(results, list):
            print(f"📸 Found {len(results)} images/media items:")
            for i, path in enumerate(results):
                exists = os.path.exists(path)
                size = os.path.getsize(path) if exists else 0
                print(f"   [{i+1}] Path: {path} | Exists: {exists} | Size: {size} bytes")
        else:
            print(f"🎥 Found 1 item: {results} | Exists: {os.path.exists(results)}")
            
    except Exception as e:
        print(f"\n❌ Download Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # التأكد من وجود مجلد التحميلات
    os.makedirs(config.DOWNLOADS_DIR, exist_ok=True)
    test_download()
