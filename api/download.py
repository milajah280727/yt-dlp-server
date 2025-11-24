from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, StreamingResponse
import yt_dlp
import os
import uuid
import asyncio
from pathlib import Path

app = FastAPI(title="YT Downloader API - Video & MP3")

# === COOKIES SETUP ===
cookie_txt = os.getenv("YOUTUBE_COOKIES", "")
COOKIE_PATH = None
if cookie_txt.strip():
    COOKIE_PATH = "/tmp/cookies.txt"
    try:
        with open(COOKIE_PATH, "w", encoding="utf-8", errors="ignore") as f:
            f.write(cookie_txt.strip() + "\n")
        print("Cookies loaded!")
    except Exception as e:
        print("Cookie error:", e)

@app.get("/")
async def home():
    return {"message": "Server YT Downloader AKTIF!", "audio_support": True, "cookies": bool(COOKIE_PATH)}

@app.get("/info")
async def get_info(url: str = Query(...)):
    ydl_opts = {'quiet': True, 'no_warnings': True, 'cookiefile': COOKIE_PATH}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return {
            "title": info.get("title", "Unknown"),
            "author": info.get("uploader", "Unknown"),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail") or (info.get("thumbnails", [{}])[-1].get("url")),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# === ENDPOINT KHUSUS VIDEO ===
@app.get("/download")
async def download_video(url: str = Query(...), q: str = Query("1080", alias="quality")):
    video_id = str(uuid.uuid4())[:8]
    temp_dir = Path("/tmp") / video_id
    temp_dir.mkdir(exist_ok=True)

    ydl_opts = {
        'format': f'best[height<={q}]+bestaudio/best[height<={q}]/best',
        'merge_output_format': 'mp4',
        'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
        'quiet': True,
        'cookiefile': COOKIE_PATH,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        video_file = next((f for f in temp_dir.iterdir() if f.suffix in {".mp4", ".mkv", ".webm"}), None)
        if not video_file:
            return JSONResponse({"error": "File video tidak ditemukan"}, status_code=500)

        safe_title = "".join(c if ord(c) < 128 else "_" for c in (info.get("title") or "video")[:100])
        filename = f"{safe_title}.mp4"

        def stream():
            with open(video_file, "rb") as f:
                yield from f
            asyncio.create_task(cleanup(temp_dir))

        return StreamingResponse(
            stream(),
            media_type="video/mp4",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# === ENDPOINT KHUSUS AUDIO MP3 (BARU!) ===
@app.get("/download-audio")
async def download_audio(url: str = Query(...), q: str = Query("best", alias="quality")):
    video_id = str(uuid.uuid4())[:8]
    temp_dir = Path("/tmp") / video_id
    temp_dir.mkdir(exist_ok=True)

    # Format audio terbaik (320kbps kalau ada)
    format_selector = "bestaudio/best"
    if q != "best":
        format_selector = f"ba[ext=m4a][abr<={q}]/ba[ext=m4a]/best"

    ydl_opts = {
        'format': format_selector,
        'postprocessors': [{
            'key': 'FFmpegExtract,ExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320' if q == "best" else q,
        }],
        'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
        'quiet': True,
        'cookiefile': COOKIE_PATH,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        # Cari file .mp3
        audio_file = next((f for f in temp_dir.iterdir() if f.suffix == ".mp3"), None)
        if not audio_file:
            return JSONResponse({"error": "File audio tidak ditemukan"}, status_code=500)

        safe_title = "".join(c if ord(c) < 128 else "_" for c in (info.get("title") or "audio")[:100])
        filename = f"{safe_title}.mp3"

        def stream():
            with open(audio_file, "rb") as f:
                yield from f
            asyncio.create_task(cleanup(temp_dir))

        return StreamingResponse(
            stream(),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Type": "audio/mpeg",
            }
        )
    except Exception as e:
        return JSONResponse({"error": f"Audio download failed: {str(e)}"}, status_code=500)

# === CLEANUP OTOMATIS ===
async def cleanup(directory: Path):
    await asyncio.sleep(600)  # 10 menit
    try:
        for f in directory.iterdir():
            f.unlink()
        directory.rmdir()
    except:
        pass

print("Server YT Downloader Pro siap! Support Video + MP3 320kbps!")