from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, StreamingResponse
import yt_dlp
import os
import uuid
import asyncio
from pathlib import Path

app = FastAPI(title="yt-dlp Server 2025 - Anti Bot Check + Headers")

# Path cookies (opsional — bisa jalan tanpa ini)
COOKIE_PATH = "cookies/cookies.txt" if os.path.exists("cookies/cookies.txt") else None

@app.get("/")
async def home():
    return {
        "message": "yt-dlp Server aktif!",
        "cookies_loaded": COOKIE_PATH is not None,
        "tip": "Bisa download 1080p tanpa cookies berkat headers anti-bot!"
    }

@app.get("/info")
async def get_info(url: str = Query(..., description="YouTube URL")):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.youtube.com/',
            'Accept-Language': 'en-US,en;q=0.9',
        },
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return {
            "title": info.get("title", "Unknown"),
            "author": info.get("uploader", "Unknown"),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail") or (info.get("thumbnails")[-1].get("url") if info.get("thumbnails") else None),
            "view_count": info.get("view_count", 0),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/download")
async def download_video(
    url: str = Query(..., description="YouTube URL"),
    q: str = Query("1080", description="1080, 720, 480, best")
):
    video_id = str(uuid.uuid4())[:8]
    temp_dir = Path("/tmp") / video_id
    temp_dir.mkdir(exist_ok=True)

    # Format pintar: Coba 1080p + audio → fallback 720p muxed → worst (anti-bot)
    format_selector = f'best[height<={q}]+bestaudio/best[height<={q}]/best[height<=720]/best'

    ydl_opts = {
        'format': format_selector,
        'merge_output_format': 'mp4',
        'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
        'retries': 5,
        'fragment_retries': 15,
        'sleep_interval': 1,
        'max_sleep_interval': 5,
        # HEADERS ANTI-BOT YANG KAMU MAU (SIMULASI BROWSER ASLI)
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.youtube.com/',
            'Origin': 'https://www.youtube.com',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        # Cari file video (MP4 atau fallback)
        video_file = next((f for f in temp_dir.iterdir() if f.suffix in {".mp4", ".mkv", ".webm"}), None)
        if not video_file:
            return JSONResponse({"error": "File video tidak ditemukan setelah download"}, status_code=500)

        title = (info.get("title") or "video")[:120]
        safe_title = "".join(c for c in title if c.isalnum() or c in " -_").rstrip()

        def file_stream():
            with open(video_file, "rb") as f:
                yield from f
            asyncio.create_task(cleanup_temp(temp_dir))

        return StreamingResponse(
            file_stream(),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_title}.mp4"',
                "Content-Type": "video/mp4",
                "Accept-Ranges": "bytes",
                "Cache-Control": "no-cache",
            }
        )
    except Exception as e:
        error_msg = str(e)
        if "Sign in" in error_msg or "bot" in error_msg.lower():
            return JSONResponse({
                "error": "YouTube blokir sementara. Coba lagi 5 menit kemudian atau video lain. Headers sudah dioptimasi!"
            }, status_code=403)
        return JSONResponse({"error": error_msg}, status_code=500)

async def cleanup_temp(directory: Path):
    await asyncio.sleep(600)
    try:
        for file in directory.iterdir():
            file.unlink()
        directory.rmdir()
    except:
        pass