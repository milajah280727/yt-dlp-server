from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, JSONResponse
import yt_dlp
import os
import uuid
import asyncio
from pathlib import Path

app = FastAPI(title="YouTube Downloader API")

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
    return {"message": "API aktif", "endpoints": ["/download_video", "/download_audio"]}

@app.get("/download_video")
async def download_video(
    url: str = Query(..., description="URL video YouTube"),
    quality: str = Query("1080", description="Maksimal resolusi video (contoh: 360, 720, 1080)"),
):
    """Endpoint untuk download video + audio, resolusi sesuai quality"""
    video_id = str(uuid.uuid4())[:8]
    temp_dir = Path("/tmp") / video_id
    temp_dir.mkdir(exist_ok=True)

    # format selector: video + audio, video dengan height <= quality
    format_selector = f"best[height<={quality}][vcodec^=avc]+bestaudio/best[height<={quality}]/best"

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

        # cari file hasil download
        video_file = None
        for ext in [".mp4", ".mkv", ".webm"]:
            video_file = next((f for f in temp_dir.iterdir() if f.suffix == ext), None)
            if video_file:
                break

        if not video_file:
            return JSONResponse({"error": "File video tidak ditemukan"}, status_code=500)

        safe_title = "".join(c if c.isalnum() or c in " .-_()" else "_" for c in (info.get("title") or "video")[:100])

        async def stream_file():
            try:
                with open(video_file, "rb") as f:
                    while chunk := f.read(8192):
                        yield chunk
            finally:
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
        await cleanup(temp_dir)
        return JSONResponse({"error": f"Gagal download video: {str(e)}"}, status_code=500)

@app.get("/download_audio")
async def download_audio(
    url: str = Query(..., description="URL video YouTube"),
    audio_format: str = Query("mp3", description="Format audio: mp3 / m4a / opus")
):
    """Endpoint untuk download audio-only dari YouTube"""
    audio_id = str(uuid.uuid4())[:8]
    temp_dir = Path("/tmp") / audio_id
    temp_dir.mkdir(exist_ok=True)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
        'postprocessors': [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': audio_format,
                'preferredquality': '192',
            }
        ]  # membutuhkan ffmpeg terpasang di server
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        # cari file audio hasil convert
        audio_file = None
        for ext in [f".{audio_format}", ".mp3", ".m4a", ".opus", ".webm"]:
            audio_file = next((f for f in temp_dir.iterdir() if f.suffix == ext), None)
            if audio_file:
                break

        if not audio_file:
            return JSONResponse({"error": "File audio tidak ditemukan"}, status_code=500)

        safe_title = "".join(c if c.isalnum() or c in " .-_()" else "_" for c in (info.get("title") or "audio")[:100])

        async def stream_file():
            try:
                with open(audio_file, "rb") as f:
                    while chunk := f.read(8192):
                        yield chunk
            finally:
                await cleanup(temp_dir)

        # Tentukan media_type sesuai format audio
        mime = "audio/mpeg" if audio_file.suffix == ".mp3" else "audio/mp4"

        return StreamingResponse(
            stream_file(),
            media_type=mime,
            headers={
                "Content-Disposition": f'attachment; filename=\"{safe_title}{audio_file.suffix}\"',
                "Content-Length": str(audio_file.stat().st_size)
            }
        )

    except Exception as e:
        await cleanup(temp_dir)
        return JSONResponse({"error": f"Gagal download audio: {str(e)}"}, status_code=500)

async def cleanup(directory: Path):
    await asyncio.sleep(600)  # hapus setelah 10 menit
    try:
        for file in directory.iterdir():
            file.unlink()
        directory.rmdir()
    except Exception as e:
        print("Cleanup error:", e)
