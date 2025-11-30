# main.py

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
import yt_dlp
import httpx # Gunakan httpx untuk async request
import os

app = FastAPI(title="YouTube Video Downloader API")

# Setup cookies dari environment variable (Vercel)
COOKIE_PATH = None
cookie_txt = os.getenv("YOUTUBE_COOKIES", "")
if cookie_txt.strip():
    COOKIE_PATH = "/tmp/cookies.txt"
    try:
        with open(COOKIE_PATH, "w", encoding="utf-8", errors="ignore") as f:
            f.write(cookie_txt.strip() + "\n")
    except Exception as e:
        print("Gagal menulis cookie:", e)
        COOKIE_PATH = None

@app.get("/")
async def home():
    """Endpoint untuk cek status server"""
    return {
        "message": "YouTube Video Downloader API aktif",
        "cookies": "loaded" if COOKIE_PATH else "none",
        "endpoints": ["/info", "/download", "/stream_audio", "/formats"]
    }

@app.get("/info")
async def get_video_info(url: str = Query(..., description="URL video YouTube")):
    """Mendapatkan informasi video YouTube"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
        return {
            "id": info.get("id"),
            "title": info.get("title"),
            "channel": info.get("uploader"),
            "duration": info.get("duration"),
            "duration_formatted": f"{info.get('duration', 0)//60}:{info.get('duration', 0)%60:02d}",
            "thumbnail": info.get("thumbnail"),
            "view_count": info.get("view_count"),
            "upload_date": info.get("upload_date"),
            "description": info.get("description", "")[:200] + "..." if info.get("description") else "",
            "formats": [
                {
                    "format_id": f.get("format_id"),
                    "height": f.get("height"),
                    "width": f.get("width"),
                    "fps": f.get("fps"),
                    "ext": f.get("ext"),
                    "filesize": f.get("filesize")
                }
                for f in info.get("formats", [])[:10] if f.get("vcodec") != "none"
            ]
        }
    except Exception as e:
        return JSONResponse(
            {"error": f"Gagal mengambil info video: {str(e)}"}, 
            status_code=500
        )

# ==================== ENDPOINT BARU UNTUK STREAMING AUDIO ====================
@app.get("/stream_audio")
async def stream_audio(url: str = Query(..., description="URL video YouTube")):
    """
    Endpoint untuk streaming audio dari video YouTube.
    Berfungsi sebagai proxy untuk menghindari error 403 dari YouTube.
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            audio_url = info['url']
            
            # Header yang diperlukan untuk meniru permintaan dari browser
            headers = {
                'User-Agent': info.get('http_headers', {}).get('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'),
                'Referer': 'https://www.youtube.com/',
                'Accept': '*/*',
            }

            async def generator():
                """Generator untuk streaming data dari YouTube ke client."""
                async with httpx.AsyncClient() as client:
                    async with client.get(audio_url, headers=headers, timeout=30.0) as r:
                        r.raise_for_status()
                        async for chunk in r.aiter_bytes(chunk_size=8192):
                            yield chunk

            return StreamingResponse(
                generator(),
                media_type="audio/mp4", # M4A container
                headers={
                    "Content-Type": "audio/mp4",
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "no-cache"
                }
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error streaming audio: {str(e)}")

# ==================== ENDPOINT LAINNYA (TIDAK DIUBAH) ====================
@app.get("/download")
async def download_video(
    url: str = Query(..., description="URL video YouTube"),
    quality: str = Query("1080", description="Kualitas video (contoh: 720, 1080, 1440)"),
    format_id: str = Query(None, description="Format ID spesifik (opsional)")
):
    """Download video YouTube dengan kualitas tertentu"""
    # CATATAN: Fitur download mungkin tidak berfungsi dengan baik di Vercel
    # karena Vercel memiliki batasan waktu eksekusi (max 10-60 detik untuk plan gratis)
    # dan tidak memiliki sistem file yang persisten.
    # Untuk fitur download, lebih baik menggunakan server tradisional (VPS).
    
    # ... (kode download Anda tetap sama, tidak perlu diubah)
    # ...
    return JSONResponse(
        {"error": "Fitur download tidak didukung di lingkungan serverless Vercel."}, 
        status_code=501 # Not Implemented
    )


@app.get("/formats")
async def list_formats(url: str = Query(...)):
    """List semua format video yang tersedia"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
        formats = []
        for f in info.get("formats", []):
            if f.get("vcodec") != "none":  # Hanya format video
                formats.append({
                    "format_id": f.get("format_id"),
                    "ext": f.get("ext"),
                    "resolution": f.get("resolution"),
                    "height": f.get("height"),
                    "width": f.get("width"),
                    "fps": f.get("fps"),
                    "filesize": f.get("filesize"),
                    "vcodec": f.get("vcodec"),
                    "acodec": f.get("acodec"),
                })
        
        return {
            "title": info.get("title"),
            "formats": formats
        }
    except Exception as e:
        return JSONResponse(
            {"error": f"Gagal list format: {str(e)}"}, 
            status_code=500
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
