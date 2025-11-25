from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, StreamingResponse
import yt_dlp
import os
import uuid
import asyncio
from pathlib import Path

app = FastAPI()

# === COOKIES SETUP (untuk video age-restricted / login) ===
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
        "message": "Server aktif!",
        "cookies": "loaded" if COOKIE_PATH else "none",
        "audio_format": "m4a (no FFmpeg needed - 100% work!)"
    }

@app.get("/info")
async def get_info(url: str = Query(...)):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
    }
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

# === DOWNLOAD VIDEO (MP4) ===
@app.get("/download")
async def download_video(url: str = Query(...), quality: str = Query("1080")):
    video_id = str(uuid.uuid4())[:8]
    temp_dir = Path("/tmp") / video_id
    temp_dir.mkdir(exist_ok=True)

    ydl_opts = {
        'format': f'best[height<={quality}]+bestaudio/best',
        'merge_output_format': 'mp4',
        'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
        'retries': 3,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        video_file = next((f for f in temp_dir.iterdir() if f.suffix == ".mp4"), None)
        if not video_file:
            return JSONResponse({"error": "Video gagal di-merge"}, status_code=500)

        safe_title = "".join(c if ord(c) < 128 else "_" for c in (info.get("title") or "video")[:100])

        def stream_file():
            with open(video_file, "rb") as f:
                yield from f
            asyncio.create_task(cleanup(temp_dir))

        return StreamingResponse(
            stream_file(),
            media_type="video/mp4",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}.mp4"'}
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# === DOWNLOAD AUDIO (.m4a - TANPA FFMPEG!) ===
@app.get("/download-audio")
async def download_audio(url: str = Query(...)):
    video_id = str(uuid.uuid4())[:8]
    temp_dir = Path("/tmp") / video_id
    temp_dir.mkdir(exist_ok=True)

    ydl_opts = {
        'format': 'bestaudio/best',  # YouTube kasih .m4a atau .webm terbaik
        'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
        'retries': 3,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        # Cari file audio (biasanya .m4a, kadang .webm)
        audio_file = next((f for f in temp_dir.iterdir() if f.suffix in {".m4a", ".webm", ".opus"}), None)
        if not audio_file:
            return JSONResponse({"error": "Audio tidak ditemukan"}, status_code=500)

        safe_title = "".join(c if ord(c) < 128 else "_" for c in (info.get("title") or "audio")[:100])
        ext = audio_file.suffix

        def stream_file():
            with open(audio_file, "rb") as f:
                yield from f
            asyncio.create_task(cleanup(temp_dir))

        return StreamingResponse(
            stream_file(),
            media_type="audio/mp4" if ext == ".m4a" else "audio/webm",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}{ext}"'}
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# === STREAMING LANGSUNG DI BROWSER (Video/Audio) ===
@app.get("/stream")
async def stream_media(url: str = Query(...), type: str = Query("video"), quality: str = Query("720")):
    if type not in ["video", "audio"]:
        return JSONResponse({"error": "type harus 'video' atau 'audio'"}, status_code=400)

    video_id = str(uuid.uuid4())[:8]
    temp_dir = Path("/tmp") / video_id
    temp_dir.mkdir(exist_ok=True)

    if type == "video":
        ydl_opts = {
            'format': f'best[height<={quality}]+bestaudio/best',
            'merge_output_format': 'mp4',
            'outtmpl': str(temp_dir / 'stream.mp4'),
            'quiet': True,
            'cookiefile': COOKIE_PATH,
        }
        final_file = temp_dir / "stream.mp4"
        content_type = "video/mp4"
    else:  # audio
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': str(temp_dir / 'stream.%(ext)s'),
            'quiet': True,
            'cookiefile': COOKIE_PATH,
        }
        final_file = next(temp_dir.glob("stream.*"))
        content_type = "audio/mp4" if final_file.suffix == ".m4a" else "audio/webm"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        # Tunggu file muncul
        for _ in range(50):
            if type == "audio":
                final_file = next((f for f in temp_dir.iterdir() if f.suffix in {".m4a", ".webm"}), None)
            if final_file and final_file.exists():
                break
            await asyncio.sleep(0.2)

        if not final_file or not final_file.exists():
            return JSONResponse({"error": "File tidak siap"}, status_code=500)

        def stream_file():
            with open(final_file, "rb") as f:
                while chunk := f.read(1024 * 1024):  # 1MB chunks
                    yield chunk
            asyncio.create_task(cleanup(temp_dir))

        return StreamingResponse(
            stream_file(),
            media_type=content_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Disposition": "inline",  # langsung play di browser
            }
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# === CLEANUP OTOMATIS ===
async def cleanup(directory: Path):
    await asyncio.sleep(600)  # 10 menit
    try:
        for f in directory.iterdir():
            f.unlink()
        directory.rmdir()
    except:
        pass