import psutil
import speedtest
import logging
import os

logger = logging.getLogger(__name__)

def get_server_specs():
    """Returns a dictionary containing server RAM, Storage, and Internet Speed."""
    specs = {
        "ram": "N/A",
        "storage": "N/A",
    }

    try:
        # RAM Stats
        ram = psutil.virtual_memory()
        specs["ram"] = f"{ram.used / (1024**3):.1f}GB / {ram.total / (1024**3):.1f}GB ({ram.percent}%)"
    except Exception as e:
        logger.warning(f"Could not get RAM specs: {e}")

    try:
        # Storage Stats (Root partition or current partition)
        # Note: disk_usage('/') can fail in some sandboxed environments like Cloud Run
        usage = psutil.disk_usage('/')
        specs["storage"] = f"{usage.used / (1024**3):.1f}GB / {usage.total / (1024**3):.1f}GB ({usage.percent}%)"
    except Exception as e:
        logger.warning(f"Could not get Storage specs: {e}")

    return specs

def get_internet_speed():
    """Runs a speed test and returns download/upload speeds."""
    try:
        st = speedtest.Speedtest()
        st.get_best_server()
        download_speed = st.download() / 1_000_000  # Mbps
        upload_speed = st.upload() / 1_000_000    # Mbps
        return {
            "download": f"{download_speed:.1f} Mbps",
            "upload": f"{upload_speed:.1f} Mbps"
        }
    except Exception as e:
        logger.error(f"Error running speed test: {e}")
        return {"download": "Error", "upload": "Error"}
