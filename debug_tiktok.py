import requests
import re
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TiktokDebug")

url = "https://vt.tiktok.com/ZSm4m1WCB/"

headers = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def debug_tiktok():
    try:
        logger.info(f"Fetching URL: {url}")
        session = requests.Session()
        response = session.get(url, headers=headers, timeout=15, allow_redirects=True)
        logger.info(f"Final URL: {response.url}")
        logger.info(f"Status Code: {response.status_code}")
        
        # Save a bit of content for inspection
        with open("tiktok_debug.html", "w", encoding="utf-8") as f:
            f.write(response.text)
            
        logger.info("Saved response to tiktok_debug.html")
        
        # Check for the script tag
        match = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>', response.text)
        if match:
            logger.info("Found __UNIVERSAL_DATA_FOR_REHYDRATION__ script tag")
            try:
                data = json.loads(match.group(1))
                logger.info("Successfully parsed JSON data")
                
                # Search for specific keys
                def find_key(obj, key):
                    if isinstance(obj, dict):
                        if key in obj: return obj[key]
                        for v in obj.values():
                            res = find_key(v, key)
                            if res: return res
                    elif isinstance(obj, list):
                        for item in obj:
                            res = find_key(item, key)
                            if res: return res
                    return None
                
                image_post = find_key(data, "imagePost")
                if image_post:
                    logger.info("Found imagePost data!")
                    images = image_post.get("images", [])
                    logger.info(f"Number of images: {len(images)}")
                    if images:
                        logger.info(f"First image data keys: {list(images[0].keys())}")
                        url_list = images[0].get("imageURL", {}).get("urlList", [])
                        img_url = url_list[0] if url_list else images[0].get("displayLink")
                        
                        if img_url:
                            logger.info(f"Testing download for: {img_url}")
                            headers_dl = {
                                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                                "Referer": "https://www.tiktok.com/",
                            }
                            res_dl = requests.get(img_url, headers=headers_dl, timeout=10)
                            logger.info(f"Download Result: {res_dl.status_code}")
                            if res_dl.status_code == 200:
                                logger.info("✅ Download Success!")
                            else:
                                logger.error(f"❌ Download Failed with status: {res_dl.status_code}")
                        else:
                            logger.warning("No image URL found to test")
                else:
                    logger.warning("imagePost NOT found in data")
                    # Print keys of the root to see what we have
                    logger.info(f"Root keys: {list(data.keys())}")
            except Exception as e:
                logger.error(f"Error parsing JSON: {e}")
        else:
            logger.warning("__UNIVERSAL_DATA_FOR_REHYDRATION__ NOT found")
            # Try searching for other likely tags
            if "SIGI_STATE" in response.text:
                logger.info("Found SIGI_STATE")
            if "RENDER_DATA" in response.text:
                logger.info("Found RENDER_DATA")
            
    except Exception as e:
        logger.error(f"Error during request: {e}")

if __name__ == "__main__":
    debug_tiktok()
