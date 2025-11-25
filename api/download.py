from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, StreamingResponse
import yt_dlp
import os
import uuid
import asyncio
from pathlib import Path

app = FastAPI()

# Cookies untuk video private / age-restricted (opsional)
cookie_txt = os.getenv("YOUTUBE_COOKIES", "")
COOKIE_PATH = None
if cookie_txt.strip():
    COOKIE_PATH = "/tmp/cookies.txt"
    try:
        with open(COOKIE_PATH, "w", encoding="utf-8", errors="ignore") as f:
            f.write(cookie_txt.strip() + "\n")
    except Exception as e:
        print("Cookie write error:", e)
        COOKIE_PATH = None

@app.get("/")
async def home():
    return {
        "message": "YT Server Aktif!",
        "audio": "M4A (tanpa FFmpeg - 100% work di Vercel)",
        "cookies": "loaded" if COOKIE_PATH else "none"
    }

# INFO VIDEO
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
        return JSONResponse({"error": str(e)}, 500)

# DOWNLOAD VIDEO (720p, 1080p, dll)
@app.get("/download")
async def download_video(url: str = Query(...), quality: str = Query("720")):
    temp_dir = Path("/tmp") / str(uuid.uuid4())[:8]
    temp_dir.mkdir(exist_ok=True)

    ydl_opts = {
        'format': f'best[height<={quality}]+bestaudio/best',
        'merge_output_format': 'mp4',
        'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
        'noplaylist': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        # Tunggu file muncul
        video_file = None
        for _ in range(60):
            await asyncio.sleep(0.2)
            video_file = next((f for f in temp_dir.iterdir() if f.suffix == ".mp4"), None)
            if video_file and video_file.stat().st_size > 10000:
                break

        if not video_file:
            return JSONResponse({"error": "Video gagal diproses"}, 500)

        safe_title = "".join(c if ord(c) < 128 else "_" for c in (info.get("title") or "video")[:100])

        def stream():
            with open(video_file, "rb") as f:
                yield from f
            asyncio.create_task(cleanup(temp_dir))

        return StreamingResponse(
            stream(),
            media_type="video/mp4",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}.mp4"'}
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)

# DOWNLOAD AUDIO — TANPA FFMPEG! (PAKAI .m4a ASLI YOUTUBE — KUALITAS TERBAIK!)
@app.get("/download-audio")
async def download_audio(url: str = Query(...)):
    temp_dir = Path("/tmp") / str(uuid.uuid4())[:8]
    temp_dir.mkdir(exist_ok=True)

    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',  # Prioritas .m4a (kualitas 129-160kbps)
        'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
        'noplaylist': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        # Tunggu file audio muncul
        audio_file = None
        for _ in range(60):
            await asyncio.sleep(0.2)
            audio_file = next((f for f in temp_dir.iterdir() if f.suffix in {".m4a", ".webm"}), None)
            if audio_file and audio_file.stat().st_size > 50000:  # minimal 50KB
                break

        if not audio_file:
            return JSONResponse({"error": "Audio tidak ditemukan (timeout)"}, 500)

        safe_title = "".join(c if ord(c) < 128 else "_" for c in (info.get("title") or "audio")[:100])
        ext = audio_file.suffix

        def stream():
            with open(audio_file, "rb") as f:
                yield from f
            asyncio.create_task(cleanup(temp_dir))

        return StreamingResponse(
            stream(),
            media_type="audio/mp4" if ext == ".m4a" else "audio/webm",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}{ext}"'}
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)

# STREAMING LANGSUNG (untuk Flutter)
@app.get("/stream")
async def stream_video(url: str = Query(...), quality: str = Query("720")):
    temp_dir = Path("/tmp") / str(uuid.uuid4())[:8]
    temp_dir.mkdir(exist_ok=True)

    ydl_opts = {
        'format': f'best[height<={quality}]+bestaudio/best',
        'merge_output_format': 'mp4',
        'outtmpl': str(temp_dir / 'stream.mp4'),
        'quiet': True,
        'cookiefile': COOKIE_PATH,
        'noplaylist': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)

        file = None
        for _ in range(80):
            await asyncio.sleep(0.2)
            file = temp_dir / "stream.mp4"
            if file.exists() and file.stat().st_size > 100000:
                break

        if not file or not file.exists():
            return JSONResponse({"error": "Stream tidak siap"}, 500)

        def stream():
            with open(file, "rb") as f:
                while chunk := f.read(1024*1024):
                    yield chunk
            asyncio.create_task(cleanup(temp_dir))

        return StreamingResponse(
            stream(),
            media_type="video/mp4",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Disposition": "inline",
                "Cache-Control": "public, max-age=3600"
            }
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)

async def cleanup(directory: Path):
    await asyncio.sleep(600)
    try:
        for f in directory.iterdir():
            f.unlink()
        directory.rmdir()
    except:
        pass