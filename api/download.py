from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, StreamingResponse
import yt_dlp
import os
import uuid
import asyncio
from pathlib import Path

app = FastAPI(
    title="YouTube Downloader API",
    description="API untuk mengunduh, streaming (via FFmpeg), dan mencari video dari YouTube.",
    version="3.0"
)

# AMBIL COOKIES DARI ENV & TULIS DENGAN UTF-8
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

# --- Endpoint yang sudah ada (tidak berubah) ---
@app.get("/")
async def home():
    return {"message": "Server aktif!", "cookies": "loaded" if COOKIE_PATH else "none"}

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
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        video_file = next((f for f in temp_dir.iterdir() if f.suffix in {".mp4", ".webm", ".mkv"}), None)
        if not video_file:
            return JSONResponse({"error": "Video tidak ditemukan setelah unduh"}, status_code=500)

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
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        audio_file = next((f for f in temp_dir.iterdir() if f.suffix == ".mp3"), None)
        if not audio_file:
            return JSONResponse({"error": "Audio tidak ditemukan setelah konversi"}, status_code=500)

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

@app.get("/search")
async def search_videos(q: str = Query(..., description="Kata kunci pencarian"), limit: int = Query(10, description="Jumlah maksimal hasil")):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
    }
    try:
        search_query = f"ytsearch{limit}:{q}"
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_results = ydl.extract_info(search_query, download=False)

        videos = []
        for entry in search_results.get('entries', []):
            if entry:
                videos.append({
                    "id": entry.get("id"),
                    "title": entry.get("title"),
                    "uploader": entry.get("uploader"),
                    "duration": entry.get("duration"),
                    "thumbnail": entry.get("thumbnail"),
                    "url": entry.get("webpage_url"),
                })
        
        return {"query": q, "results": videos}

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# --- Endpoint Streaming yang Telah Dimodifikasi ---
@app.get("/stream")
async def stream_video(url: str = Query(...), quality: str = Query("1080")):
    """
    Streaming video secara langsung menggunakan FFmpeg tanpa mengunduh file ke server.
    """
    # Path ke FFmpeg, sesuaikan jika lingkungan Anda berbeda
    # Di Vercel, biasanya ada di sini.
    ffmpeg_path = "/opt/vercel/bin/ffmpeg" 

    ydl_opts = {
        'format': f'best[height<={quality}]+bestaudio/best[height<={quality}]/best',
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
    }

    try:
        # Langkah 1: Dapatkan URL streaming langsung dengan yt-dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            # Coba dapatkan URL format yang sudah digabung (DASH)
            # Jika tidak ada, yt-dlp akan memilih format terbaik tunggal
            video_url = info.get('url')
            if not video_url:
                # Jika 'url' tidak ada, coba 'requested_formats'
                if 'requested_formats' in info and len(info['requested_formats']) > 0:
                     # Untuk streaming, kita butuh format yang sudah jadi satu
                     # Kita akan coba meminta format terbaik yang sudah termasuk audio
                    ydl_single_format_opts = {
                        'format': f'best[height<={quality}][vcodec!=none][acodec!=none]/best[height<={quality}]/best',
                        'quiet': True,
                        'no_warnings': True,
                        'cookiefile': COOKIE_PATH,
                    }
                    with yt_dlp.YoutubeDL(ydl_single_format_opts) as ydl_single:
                        info_single = ydl_single.extract_info(url, download=False)
                        video_url = info_single.get('url')

            if not video_url:
                 return JSONResponse({"error": "Tidak bisa mendapatkan URL streaming yang cocok."}, status_code=500)


        # Langkah 2: Siapkan perintah FFmpeg
        # -i: input URL
        # -c copy: copy codec video dan audio tanpa re-encoding (sangat cepat)
        # -f mp4: format output mp4
        # -movflags frag_keyframe+empty_moov: Buat MP4 fragmentasi untuk streaming web
        # pipe:1: output ke stdout
        command = [
            ffmpeg_path,
            '-i', video_url,
            '-c', 'copy',
            '-f', 'mp4',
            '-movflags', 'frag_keyframe+empty_moov',
            'pipe:1'
        ]

        # Langkah 3: Jalankan proses FFmpeg
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Langkah 4: Buat generator untuk streaming output FFmpeg
        async def generate():
            try:
                while True:
                    # Baca output dari FFmpeg dalam chunk
                    chunk = await process.stdout.read(8192)
                    if not chunk:
                        break
                    yield chunk
            finally:
                # Tunggu proses selesai dan tangkap error
                await process.wait()
                if process.returncode != 0:
                    error_message = await process.stderr.read()
                    print(f"FFmpeg Error: {error_message.decode()}")
                # Tutup pipa untuk membersihkan sumber daya
                process.stdout.close()
                process.stderr.close()

        # Langkah 5: Kembalikan StreamingResponse
        return StreamingResponse(
            generate(),
            media_type="video/mp4",
            headers={
                "Content-Disposition": "inline; filename=\"stream.mp4\"",
                "Accept-Ranges": "bytes",
                "Cache-Control": "no-cache"
            }
        )

    except Exception as e:
        return JSONResponse({"error": f"Failed to start stream: {str(e)}"}, status_code=500)


async def cleanup(directory: Path):
    await asyncio.sleep(600)
    try:
        for f in directory.iterdir():
            f.unlink()
        directory.rmdir()
    except Exception as e:
        print(f"Cleanup error for {directory}: {e}")
