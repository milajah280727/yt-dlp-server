from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import StreamingResponse
import yt_dlp
import os
import uuid
import asyncio
from pathlib import Path
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

async def cleanup(directory: Path):
    await asyncio.sleep(600)
    try:
        for item in directory.iterdir():
            if item.is_file():
                item.unlink()
        directory.rmdir()
        print(f"Cleaned up directory: {directory}")
    except Exception as e:
        print(f"Error during cleanup: {e}")

@app.get("/download-audio")
async def download_audio(url: str = Query(...), quality: str = Query("best")):
    """Endpoint khusus untuk mengunduh audio dan mengonversinya ke MP3."""
    video_id = str(uuid.uuid4())[:8]
    temp_dir = Path("/tmp") / video_id
    temp_dir.mkdir(exist_ok=True)

    format_selector = 'bestaudio/best' if quality == "best" else f'bestaudio[abr<={quality}]/bestaudio'

    ydl_opts = {
        'format': format_selector,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': quality if quality != "best" else '0',
        }],
        'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
        'retries': 3,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        audio_file = next((f for f in temp_dir.iterdir() if f.suffix == ".mp3"), None)
        if not audio_file:
            raise HTTPException(status_code=500, detail="Converted audio file not found.")

        safe_title = "".join(c if c.isalnum() or c in " ._-" else "_" for c in (info.get("title") or "audio")[:100])

        def stream_file():
            with open(audio_file, "rb") as f:
                yield from f
            asyncio.create_task(cleanup(temp_dir))

        return StreamingResponse(
            stream_file(),
            media_type="audio/mpeg",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}.mp3"'}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download/convert audio: {str(e)}")