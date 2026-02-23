import os
import sys
import logging
import shutil

# إعداد المسارات لتمكين الاستيراد
sys.path.append(os.getcwd())

import config
from downloaders.instagram import InstagramDownloader

# إعداد السجلات للمعاينة
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_description_extraction():
    print("🚀 Starting Video Description Extraction Test...")
    
    downloader = InstagramDownloader()
    
    # رابط منشور لاختبار الوصف
    test_url = "https://www.instagram.com/p/DTe27BhCJf2/?igsh=Z3ExYnVqMzJic25j"
    
    try:
        print(f"📥 Fetching content from: {test_url}")
        res_dict = downloader.download_video(test_url)
        
        results     = res_dict.get("results")
        description = res_dict.get("description")
        
        print(f"\n📝 Extracted Description: \n{'-'*20}\n{description}\n{'-'*20}")
        
        if description:
            print("✅ SUCCESS! Description extracted correctly.")
        else:
            print("⚠️ WARNING: Description is empty.")

        if isinstance(results, list):
            print(f"✅ Found Carousel with {len(results)} items.")
        else:
            print(f"✅ Found Single file: {results}")

        # تنظيف
        downloader.cleanup(results)
        print("✨ Cleanup executed.")

    except Exception as e:
        print(f"❌ Test Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_description_extraction()
