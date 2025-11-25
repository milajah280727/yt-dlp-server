from fastapi import FastAPI, Query, HTTPException
import yt_dlp
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# --- LOGIKA COOKIE ---
cookie_txt = os.getenv("YOUTUBE_COOKIES", "")
COOKIE_PATH = None
if cookie_txt.strip():
    COOKIE_PATH = "/tmp/cookies.txt"
    try:
        with open(COOKIE_PATH, "w", encoding="utf-8", errors="ignore") as f:
            f.write(cookie_txt.strip() + "\n")
    except Exception as e:
        print(f"Error writing cookie file: {e}")
        COOKIE_PATH = None
# --- SELESAI LOGIKA COOKIE ---

@app.get("/info")
async def get_info(url: str = Query(..., description="URL video YouTube")):
    """Endpoint untuk mendapatkan informasi lengkap video."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        # --- FORMAT UNTUK STREAMING ---
        streaming_formats = {}
        for f in info.get('formats', []):
            if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                height = f.get('height')
                if height:
                    resolution = f"{height}p"
                    if resolution not in streaming_formats:
                        streaming_formats[resolution] = {
                            "url": f['url'],
                            "fps": f.get('fps', 0),
                            "ext": f.get('ext'),
                            "filesize": f.get('filesize'),
                            "format_id": f.get('format_id')
                        }
        
        streaming_formats = dict(sorted(streaming_formats.items(), key=lambda item: int(item[0].replace('p', '')), reverse=True))

        # --- SEMUA FORMAT UNTUK DOWNLOAD ---
        all_formats = []
        for f in info.get('formats', []):
            format_info = {
                "format_id": f.get('format_id'),
                "ext": f.get('ext'),
                "resolution": f.get('resolution') or "audio only",
                "fps": f.get('fps'),
                "vcodec": f.get('vcodec'),
                "acodec": f.get('acodec'),
                "filesize": f.get('filesize'),
                "label": f"{f.get('format_note') or f.get('resolution') or 'audio'} - {f.get('ext')} ({f.get('vcodec') or 'no video'}, {f.get('acodec') or 'no audio'})"
            }
            all_formats.append(format_info)

        return {
            "id": info.get("id"),
            "title": info.get("title", "Unknown"),
            "author": info.get("uploader", "Unknown"),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail") or (info.get("thumbnails")[-1]["url"] if info.get("thumbnails") else None),
            "description": info.get("description", ""),
            "streaming_formats": streaming_formats,
            "all_formats": all_formats,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to extract info: {str(e)}")