from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, StreamingResponse
import yt_dlp
import os
import uuid
import asyncio
from pathlib import Path

app = FastAPI()

# BACA COOKIES DARI ENVIRONMENT VARIABLE (Vercel)
cookie_txt = os.getenv("YOUTUBE_COOKIES", "")
COOKIE_PATH = None
if cookie_txt.strip():
    COOKIE_PATH = "/tmp/cookies.txt"
    with open(COOKIE_PATH, "w", encoding="utf-8") as f:
        f.write(cookie_txt.strip())

@app.get("/")
async def home():
    return {"message": "Server yt-dlp aktif!", "cookies": "loaded" if COOKIE_PATH else "none"}

@app.get("/info")
async def get_info(url: str = Query(...)):
    ydl_opts = {'quiet': True, 'cookiefile': COOKIE_PATH}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return {
            "title": info.get("title"),
            "author": info.get("uploader"),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail") or (info.get("thumbnails", [{}])[-1].get("url") if info.get("thumbnails") else None),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/download")
async def download_video(url: str = Query(...), q: str = Query("1080")):
    video_id = str(uuid.uuid4())[:8]
    temp_dir = Path("/tmp") / video_id
    temp_dir.mkdir(exist_ok=True)

    ydl_opts = {
        'format': f'best[height<={q}]+bestaudio/best[height<={q}]/best',
        'merge_output_format': 'mp4',
        'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
        'quiet': True,
        'cookiefile': COOKIE_PATH,   # INI YANG BIKIN BISA BYPASS BOT!
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        video_file = next((f for f in temp_dir.iterdir() if f.suffix in {".mp4", ".mkv", ".webm"}), None)
        if not video_file:
            return JSONResponse({"error": "File tidak ditemukan"}, status_code=500)

        title = "".join(c for c in (info.get("title") or "video") if c.isalnum() or c in " -_")[:100]

        def streamer():
            with open(video_file, "rb") as f:
                yield from f
            asyncio.create_task(cleanup(temp_dir))

        return StreamingResponse(
            streamer(),
            media_type="video/mp4",
            headers={"Content-Disposition": f'attachment; filename="{title}.mp4"'}
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

async def cleanup(directory: Path):
    await asyncio.sleep(600)
    try:
        for f in directory.iterdir():
            f.unlink()
        directory.rmdir()
    except:
        pass