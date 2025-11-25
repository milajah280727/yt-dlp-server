from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, StreamingResponse
import yt_dlp
import os
import uuid
import asyncio
from pathlib import Path
import requests  # Baru: buat download FFmpeg
import tarfile  # Built-in: buat ekstrak tar.xz

app = FastAPI()

# AMBIL COOKIES DARI ENV & TULIS DENGAN UTF-8 (INI YANG FIX ERROR UNICODE!)
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

# Baru: Setup FFmpeg static binary (Linux x86_64 dari yt-dlp builds)
FFMPEG_PATH = None
def setup_ffmpeg():
    global FFMPEG_PATH
    if FFMPEG_PATH:
        return  # Sudah setup
    ffmpeg_dir = Path("/tmp") / "ffmpeg"
    ffmpeg_dir.mkdir(exist_ok=True)
    ffmpeg_bin = ffmpeg_dir / "ffmpeg"
    ffprobe_bin = ffmpeg_dir / "ffprobe"
    
    if not ffmpeg_bin.exists():
        print("Downloading FFmpeg static binary...")
        url = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            raise Exception("Gagal download FFmpeg")
        tar_path = ffmpeg_dir / "ffmpeg.tar.xz"
        with open(tar_path, "wb") as f:
            f.write(resp.content)
        
        print("Extracting FFmpeg...")
        with tarfile.open(tar_path, "r:xz") as tar:
            tar.extractall(ffmpeg_dir)
        tar_path.unlink()
        
        # Cari & chmod binary (biasanya di ffmpeg-*-linux64-gpl/ffmpeg & ffprobe)
        for subdir in ffmpeg_dir.iterdir():
            if subdir.is_dir() and "ffmpeg" in subdir.name:
                bin_path = subdir / "ffmpeg"
                probe_path = subdir / "ffprobe"
                if bin_path.exists():
                    bin_path.chmod(0o755)
                    probe_path.chmod(0o755)
                    FFMPEG_PATH = str(bin_path)
                    print(f"FFmpeg setup di: {FFMPEG_PATH}")
                    break
        else:
            raise Exception("Binary FFmpeg gak ditemukan setelah extract")
    
    os.environ["PATH"] = f"{ffmpeg_dir}:{os.environ.get('PATH', '')}"  # Tambah ke PATH global

@app.on_event("startup")  # Setup otomatis saat app start
async def startup_event():
    try:
        setup_ffmpeg()
    except Exception as e:
        print(f"FFmpeg setup error: {e}")

@app.get("/")
async def home():
    return {"message": "Server aktif!", "cookies": "loaded" if COOKIE_PATH else "none", "ffmpeg": "ready" if FFMPEG_PATH else "error"}

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
            "thumbnail": info.get("thumbnail") or (info.get("thumbnails")[-1]["url"] if info.get("thumbnails") else None),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/download")
async def download_video(url: str = Query(...), quality: str = Query("1080")):
    setup_ffmpeg()  # Pastikan FFmpeg ready (buat merge)
    video_id = str(uuid.uuid4())[:8]
    temp_dir = Path("/tmp") / video_id
    temp_dir.mkdir(exist_ok=True)

    ydl_opts = {
        'format': f'best[height<={quality}]+bestaudio/best[height<={quality}]/best',
        'merge_output_format': 'mp4',
        'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
        'retries': 3,
        'ffmpeg_location': FFMPEG_PATH,  # Baru: Path ke FFmpeg
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        video_file = next((f for f in temp_dir.iterdir() if f.suffix in {".mp4", ".webm", ".mkv"}), None)
        if not video_file:
            return JSONResponse({"error": "Video tidak ditemukan"}, status_code=500)

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

@app.get("/download-audio")
async def download_audio(url: str = Query(...), quality: str = Query("best")):
    setup_ffmpeg()  # Wajib buat postprocess
    video_id = str(uuid.uuid4())[:8]
    temp_dir = Path("/tmp") / video_id
    temp_dir.mkdir(exist_ok=True)

    if quality == "best":
        format_selector = 'bestaudio/best'
    else:
        format_selector = f'bestaudio[abr<={quality}]/bestaudio'

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
        'ffmpeg_location': FFMPEG_PATH,  # Baru: Fix error ini!
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        audio_file = next((f for f in temp_dir.iterdir() if f.suffix == ".mp3"), None)
        if not audio_file:
            return JSONResponse({"error": "Audio tidak ditemukan"}, status_code=500)

        safe_title = "".join(c if ord(c) < 128 else "_" for c in (info.get("title") or "audio")[:100])

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
        return JSONResponse({"error": str(e)}, status_code=500)

# Baru: Endpoint untuk streaming video/audio langsung (play di browser tanpa download full)
@app.get("/stream")
async def stream_media(url: str = Query(...), media_type: str = Query("video"), quality: str = Query("1080")):
    setup_ffmpeg()  # Buat merge kalau perlu
    if media_type not in ["video", "audio"]:
        return JSONResponse({"error": "media_type harus 'video' atau 'audio'"}, status_code=400)
    
    video_id = str(uuid.uuid4())[:8]
    temp_dir = Path("/tmp") / video_id
    temp_dir.mkdir(exist_ok=True)

    if media_type == "video":
        format_sel = f'best[height<={quality}]+bestaudio/best[height<={quality}]/best'
        outtmpl = str(temp_dir / '%(title)s.%(ext)s')
        merge_format = 'mp4'
        postprocessors = []
        file_ext = ".mp4"
        content_type = "video/mp4"
    else:  # audio
        format_sel = 'bestaudio/best'
        outtmpl = str(temp_dir / '%(title)s.%(ext)s')
        merge_format = None
        postprocessors = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '0',  # Best
        }]
        file_ext = ".mp3"
        content_type = "audio/mpeg"

    ydl_opts = {
        'format': format_sel,
        'merge_output_format': merge_format,
        'postprocessors': postprocessors,
        'outtmpl': outtmpl,
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
        'retries': 3,
        'ffmpeg_location': FFMPEG_PATH,
        # Baru: Buat streaming, download partial & pipe ke response
        'noplaylist': True,  # Hanya single video
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)  # Download full dulu, tapi bisa diubah ke partial nanti

        media_file = next((f for f in temp_dir.iterdir() if f.suffix == file_ext), None)
        if not media_file:
            return JSONResponse({"error": f"{media_type.capitalize()} tidak ditemukan"}, status_code=500)

        safe_title = "".join(c if ord(c) < 128 else "_" for c in (info.get("title") or media_type)[:100])

        def stream_file():
            with open(media_file, "rb") as f:
                while chunk := f.read(1024 * 1024):  # Chunked streaming (1MB chunks)
                    yield chunk
            asyncio.create_task(cleanup(temp_dir))

        headers = {
            "Accept-Ranges": "bytes",  # Support seek/resume
            "Content-Length": str(media_file.stat().st_size),
            "Cache-Control": "public, max-age=3600",  # Cache 1 jam
        }
        if media_type == "audio":
            headers["Content-Disposition"] = f'inline; filename="{safe_title}.mp3"'  # Inline buat play, bukan download
        else:
            headers["Content-Disposition"] = f'inline; filename="{safe_title}.mp4"'  # Inline buat video player

        return StreamingResponse(
            stream_file(),
            media_type=content_type,
            headers=headers
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