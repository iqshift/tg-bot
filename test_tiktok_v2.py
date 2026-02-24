import os
import sys
import logging

# إضافة المسار الحالي للمشروع
sys.path.append(os.getcwd())

from downloaders.tiktok import TikTokDownloader
import config

# إعداد السجلات
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("TestTikTok")

def test_download():
    url = "https://vt.tiktok.com/ZSm4m1WCB/"
    downloader = TikTokDownloader()
    
    print(f"\n🚀 Testing URL: {url}\n" + "="*50)
    
    try:
        result = downloader.download_video(url)
        print("\n✅ Download Success!")
        print(f"📝 Description: {result.get('description')}")
        
        results = result.get("results", [])
        if isinstance(results, list):
            print(f"📸 Found {len(results)} images:")
            for i, path in enumerate(results):
                exists = os.path.exists(path)
                size = os.path.getsize(path) if exists else 0
                print(f"   [{i+1}] Path: {path} | Exists: {exists} | Size: {size} bytes")
        else:
            print(f"🎥 Found 1 video: {results}")
            
    except Exception as e:
        print(f"\n❌ Download Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # التأكد من وجود مجلد التحميلات
    os.makedirs(config.DOWNLOADS_DIR, exist_ok=True)
    test_download()
