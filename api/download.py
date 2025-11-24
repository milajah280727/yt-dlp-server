from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
import yt_dlp
import os
import uuid
import asyncio
from pathlib import Path

app = FastAPI(title="yt-dlp Server 2025 - 1080p+ Ready")

@app.get("/")
async def home():
    return {"message": "Server yt-dlp aktif! Gunakan /info atau /download"}

@app.get("/info")
async def get_info(url: str = Query(..., description="YouTube URL")):
    ydl_opts = {'quiet': True, 'no_warnings': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return {
            "title": info.get("title", "Unknown"),
            "author": info.get("uploader", "Unknown"),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail"),
            "view_count": info.get("view_count", 0),
            "formats": [
                {"height": f.get("height"), "ext": f.get("ext"), "format_id": f.get("format_id")}
                for f in info.get("formats", []) if f.get("height")
            ]
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/download")
async def download_video(
    url: str = Query(..., description="YouTube URL"),
    q: str = Query("1080", description="Kualitas: 1080, 720, 480, best, worst")
):
    video_id = str(uuid.uuid4())[:8]
    temp_dir = Path("/tmp") / video_id
    temp_dir.mkdir(exist_ok=True)

    ydl_opts = {
        'format': f'best[height<={q}]+bestaudio/best',
        'merge_output_format': 'mp4',
        'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)

        # Cari file MP4 yang sudah jadi
        mp4_file = next(temp_dir.glob("*.mp4"), None)
        if not mp4_file:
            return JSONResponse({"error": "File tidak ditemukan setelah download"}, status_code=500)

        title = info.get("title", "video")[:100]

        # Streaming file + hapus otomatis setelah 10 menit
        def file_stream():
            with open(mp4_file, "rb") as f:
                yield from f
            # Hapus setelah selesai streaming
            asyncio.create_task(cleanup_temp(temp_dir))

        return StreamingResponse(
            file_stream(),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{title}.mp4"',
                "Accept-Ranges": "bytes",
            }
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

async def cleanup_temp(directory: Path):
    await asyncio.sleep(600)  # 10 menit
    try:
        for file in directory.iterdir():
            file.unlink()
        directory.rmdir()
    except:
        pass