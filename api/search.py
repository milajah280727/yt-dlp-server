from fastapi import FastAPI, Query, HTTPException
import yt_dlp
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# --- LOGIKA COOKIE (DIDUPLIKASI UNTUK SETIAP FILE AGAR STANDALONE) ---
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

@app.get("/search")
async def search_videos(query: str = Query(..., description="Kata kunci pencarian video"), max_results: int = Query(10, description="Jumlah maksimal hasil")):
    """Endpoint untuk mencari video di YouTube berdasarkan kata kunci."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
    }
    search_url = f"ytsearch{max_results}:{query}"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_result = ydl.extract_info(search_url, download=False)

        videos = []
        if 'entries' in search_result:
            for entry in search_result['entries']:
                if entry:
                    videos.append({
                        "id": entry.get("id"),
                        "title": entry.get("title", "Tidak ada judul"),
                        "uploader": entry.get("uploader", "Tidak ada channel"),
                        "thumbnail": entry.get("thumbnail"),
                        "duration": entry.get("duration", 0),
                    })
        
        return {"query": query, "results": videos}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal melakukan pencarian: {str(e)}")