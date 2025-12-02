from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, StreamingResponse
import yt_dlp
import os
import uuid
import asyncio
from pathlib import Path

app = FastAPI(title="YouTube Video Downloader API")

# Setup cookies dari environment variable
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
        "endpoints": ["/info", "/download"]
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

@app.get("/download")
async def download_video(
    url: str = Query(..., description="URL video YouTube"),
    quality: str = Query("1080", description="Kualitas video (contoh: 720, 1080, 1440)"),
    format_id: str = Query(None, description="Format ID spesifik (opsional)")
):
    """Download video YouTube dengan kualitas tertentu"""
    video_id = str(uuid.uuid4())[:8]
    temp_dir = Path("/tmp") / video_id
    temp_dir.mkdir(exist_ok=True)

    # Tentukan format berdasarkan parameter
    if format_id:
        format_selector = format_id
    else:
        format_selector = f'best[height<={quality}][vcodec^=avc]+bestaudio/best[height<={quality}]/best'

    ydl_opts = {
        'format': format_selector,
        'merge_output_format': 'mp4',
        'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
        'retries': 3,
        'fragment_retries': 3,
        'skip_unavailable_fragments': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        # Cari file video yang sudah di-merge
        video_file = None
        for ext in [".mp4", ".webm", ".mkv"]:
            video_file = next((f for f in temp_dir.iterdir() if f.suffix == ext), None)
            if video_file:
                break

        if not video_file:
            return JSONResponse(
                {"error": "File video tidak ditemukan setelah download"}, 
                status_code=500
            )

        # Bersihkan nama file untuk header
        safe_title = "".join(
            c if c.isalnum() or c in " .-_()" else "_" 
            for c in (info.get("title") or "video")[:100]
        )

        async def stream_file():
            """Generator untuk streaming file dengan cleanup otomatis"""
            try:
                with open(video_file, "rb") as f:
                    while chunk := f.read(8192):
                        yield chunk
            finally:
                # Cleanup setelah streaming selesai
                await cleanup(temp_dir)

        return StreamingResponse(
            stream_file(),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_title}.mp4"',
                "Content-Length": str(video_file.stat().st_size)
            }
        )

    except Exception as e:
        # Cleanup jika terjadi error
        await cleanup(temp_dir)
        return JSONResponse(
            {"error": f"Gagal download video: {str(e)}"}, 
            status_code=500
        )

async def cleanup(directory: Path):
    """Hapus folder temporary setelah 10 menit"""
    await asyncio.sleep(600)
    try:
        for file in directory.iterdir():
            file.unlink()
        directory.rmdir()
    except Exception as e:
        print(f"Cleanup error: {e}")

# Tambahkan endpoint untuk list format video (opsional)
@app.get("/formats")
async def list_formats(url: str = Query(...)):
    """List semua format video yang tersedia"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
        'listformats': True,
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