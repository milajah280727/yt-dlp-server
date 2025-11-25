from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, JSONResponse
import yt_dlp
import os
import uuid
import asyncio
from pathlib import Path

app = FastAPI()

# Optional: Cookies untuk video private / age-restricted
cookie_txt = os.getenv("YOUTUBE_COOKIES", "")
COOKIE_PATH = "/tmp/cookies.txt" if cookie_txt.strip() else None
if COOKIE_PATH:
    try:
        with open(COOKIE_PATH, "w", encoding="utf-8", errors="ignore") as f:
            f.write(cookie_txt.strip() + "\n")
    except:
        COOKIE_PATH = None

def get_ydl_opts(extra=None):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'retries': 5,
    }
    if COOKIE_PATH:
        opts['cookiefile'] = COOKIE_PATH
    if extra:
        opts.update(extra)
    return opts

async def wait_for_file(temp_dir: Path, pattern: str, timeout=30):
    for _ in range(int(timeout / 0.2)):
        await asyncio.sleep(0.2)
        files = list(temp_dir.iterdir())
        match = next((f for f in files if pattern in f.name.lower()), None)
        if match and match.stat().st_size > 1000:
            return match
    return None

@app.get("/")
async def home():
    return {"message": "YT Downloader API Ready!", "author": "reebza"}

@app.get("/info")
async def info(url: str = Query(...)):
    try:
        with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
        return {
            "title": info.get("title", "Unknown"),
            "uploader": info.get("uploader", "Unknown"),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail"),
            "id": info.get("id")
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)

@app.get("/resolutions")
async def resolutions(url: str = Query(...)):
    try:
        with yt_dlp.YoutubeDL(get_ydl_opts({'format': 'best'})) as ydl:
            info = ydl.extract_info(url, download=False)
        formats = info.get("formats", [])
        heights = sorted({f['height'] for f in formats if f.get('height')}, reverse=True)
        return {"available": [h for h in heights if h]}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)

@app.get("/download/video")
async def download_video(url: str = Query(...), height: int = Query(720)):
    temp_dir = Path("/tmp") / str(uuid.uuid4())[:8]
    temp_dir.mkdir(exist_ok=True)

    ydl_opts = get_ydl_opts({
        'format': f'best[height<={height}]+bestaudio/best',
        'merge_output_format': 'mp4',
        'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
    })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        file = await wait_for_file(temp_dir, ".mp4")
        if not file:
            return JSONResponse({"error": "Video tidak tersedia"}, 500)

        safe_title = "".join(c if ord(c) < 128 else "_" for c in info.get("title", "video")[:100])

        def streamer():
            with open(file, "rb") as f:
                yield from f
            asyncio.create_task(asyncio.to_thread(lambda: [f.unlink() for f in temp_dir.iterdir()] + [temp_dir.rmdir()]))

        return StreamingResponse(
            streamer(),
            media_type="video/mp4",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}.mp4"'}
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)

@app.get("/download/audio")
async def download_audio(url: str = Query(...)):
    temp_dir = Path("/tmp") / str(uuid.uuid4())[:8]
    temp_dir.mkdir(exist_ok=True)

    ydl_opts = get_ydl_opts({
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
    })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        file = await wait_for_file(temp_dir, ".m4a")
        if not file:
            return JSONResponse({"error": "Audio tidak tersedia"}, 500)

        safe_title = "".join(c if ord(c) < 128 else "_" for c in info.get("title", "audio")[:100])

        def streamer():
            with open(file, "rb") as f:
                yield from f
            asyncio.create_task(asyncio.to_thread(lambda: [f.unlink() for f in temp_dir.iterdir()] + [temp_dir.rmdir()]))

        return StreamingResponse(
            streamer(),
            media_type="audio/mp4",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}.m4a"'}
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)

@app.get("/stream/video")
async def stream_video(url: str = Query(...), height: int = Query(720)):
    temp_dir = Path("/tmp") / str(uuid.uuid4())[:8]
    temp_dir.mkdir(exist_ok=True)

    ydl_opts = get_ydl_opts({
        'format': f'best[height<={height}]+bestaudio/best',
        'merge_output_format': 'mp4',
        'outtmpl': str(temp_dir / 'stream.mp4'),
    })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)

        file = await wait_for_file(temp_dir, "stream.mp4", timeout=40)
        if not file:
            return JSONResponse({"error": "Stream tidak siap"}, 500)

        def streamer():
            with open(file, "rb") as f:
                while chunk := f.read(1024*1024):
                    yield chunk
            asyncio.create_task(asyncio.to_thread(lambda: [f.unlink() for f in temp_dir.iterdir()] + [temp_dir.rmdir()]))

        return StreamingResponse(
            streamer(),
            media_type="video/mp4",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Disposition": "inline",
                "Cache-Control": "public, max-age=3600"
            }
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)