from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
import yt_dlp
import os
import uuid
import asyncio
from pathlib import Path

# Inisialisasi aplikasi FastAPI
app = FastAPI(
    title="Y-Player API",
    description="API yang powerful dan efisien untuk streaming dan download video/audio.",
    version="2.0.0"
)

# --- PENANGANAN COOKIE ---
# Membaca cookie dari variabel lingkungan untuk mengakses video terbatas
cookie_txt = os.getenv("YOUTUBE_COOKIES", "")
COOKIE_PATH = None
if cookie_txt.strip():
    COOKIE_PATH = "/tmp/cookies.txt"
    try:
        # Menulis cookie dengan encoding UTF-8 untuk mencegah error karakter
        with open(COOKIE_PATH, "w", encoding="utf-8", errors="ignore") as f:
            f.write(cookie_txt.strip() + "\n")
    except Exception as e:
        print(f"Error writing cookie file: {e}")
        COOKIE_PATH = None

# --- ENDPOINT API ---

@app.get("/", tags=["General"])
async def root():
    """Endpoint untuk memeriksa status server."""
    return {"message": "Y-Player API is running", "status": "active", "cookies": "loaded" if COOKIE_PATH else "none"}

@app.get("/info", tags=["Info"])
async def get_info(url: str = Query(..., description="URL video YouTube")):
    """
    Endpoint untuk mendapatkan informasi lengkap video.
    Mengembalikan metadata, daftar format untuk streaming, dan daftar semua format untuk download.
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        # --- 1. FORMAT UNTUK STREAMING (EFISIEN) ---
        # Hanya mengambil format yang sudah memiliki video & audio (pre-merged)
        # Ini memudahkan client untuk langsung memutar tanpa perlu merge
        streaming_formats = {}
        for f in info.get('formats', []):
            if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                height = f.get('height')
                if height:
                    resolution = f"{height}p"
                    # Simpan hanya satu format terbaik per resolusi untuk menghindari duplikat
                    if resolution not in streaming_formats:
                        streaming_formats[resolution] = {
                            "url": f['url'],
                            "fps": f.get('fps', 0),
                            "ext": f.get('ext'),
                            "filesize": f.get('filesize'),
                            "format_id": f.get('format_id') # Tambahkan format_id untuk referensi
                        }
        
        # Urutkan dari resolusi tertinggi ke terendah
        streaming_formats = dict(sorted(streaming_formats.items(), key=lambda item: int(item[0].replace('p', '')), reverse=True))

        # --- 2. SEMUA FORMAT UNTUK DOWNLOAD (POWERFUL) ---
        # Membuat daftar detail dari SEMUA format yang tersedia
        # Memberikan kontrol penuh kepada client untuk memilih format spesifik
        all_formats = []
        for f in info.get('formats', []):
            format_info = {
                "format_id": f.get('format_id'),
                "ext": f.get('ext'),
                "resolution": f.get('resolution') or "audio only",
                "fps": f.get('fps'),
                "vcodec": f.get('vcodec'),
                "acodec": f.get('acodec'),
                "filesize": f.get('filesize'),
                # Label yang mudah dibaca untuk ditampilkan di UI
                "label": f"{f.get('format_note') or f.get('resolution') or 'audio'} - {f.get('ext')} ({f.get('vcodec') or 'no video'}, {f.get('acodec') or 'no audio'})"
            }
            all_formats.append(format_info)

        # --- 3. KEMBALIKAN RESPONS YANG LENGKAP ---
        return {
            "id": info.get("id"),
            "title": info.get("title", "Unknown"),
            "author": info.get("uploader", "Unknown"),
            "duration": info.get("duration", 0),
            "thumbnail": info.get("thumbnail") or (info.get("thumbnails")[-1]["url"] if info.get("thumbnails") else None),
            "description": info.get("description", ""),
            
            # Untuk fitur streaming yang efisien
            "streaming_formats": streaming_formats,
            
            # Untuk fitur download yang powerful
            "all_formats": all_formats,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to extract info: {str(e)}")

@app.get("/download", tags=["Download"])
async def download_file(url: str = Query(...), format_id: str = Query(...)):
    """
    Endpoint untuk mengunduh video/audio dengan format_id spesifik.
    Format_id didapat dari endpoint /info pada bagian 'all_formats'.
    """
    video_id = str(uuid.uuid4())[:8]
    temp_dir = Path("/tmp") / video_id
    temp_dir.mkdir(exist_ok=True)

    ydl_opts = {
        'format': format_id, # Menggunakan format_id yang sangat spesifik
        'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'cookiefile': COOKIE_PATH,
        'retries': 3,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        # Cari file yang telah diunduh
        downloaded_file = next((f for f in temp_dir.iterdir() if f.is_file()), None)
        if not downloaded_file:
            raise HTTPException(status_code=500, detail="Downloaded file not found.")

        # Buat nama file yang aman untuk header
        safe_title = "".join(c if c.isalnum() or c in " ._-" else "_" for c in (info.get("title") or "video")[:100])

        def stream_file():
            with open(downloaded_file, "rb") as f:
                yield from f
            # Jadwalkan pembersihan setelah streaming selesai
            asyncio.create_task(cleanup(temp_dir))

        return StreamingResponse(
            stream_file(),
            media_type="application/octet-stream", # Media type yang lebih umum
            headers={"Content-Disposition": f'attachment; filename="{safe_title}.{downloaded_file.suffix.lstrip(".")}"'}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download file: {str(e)}")

@app.get("/download-audio", tags=["Download"])
async def download_audio(url: str = Query(...), quality: str = Query("best")):
    """
    Endpoint khusus untuk mengunduh audio dan mengonversinya ke MP3.
    """
    video_id = str(uuid.uuid4())[:8]
    temp_dir = Path("/tmp") / video_id
    temp_dir.mkdir(exist_ok=True)

    # Tentukan pemilih format berdasarkan kualitas
    format_selector = 'bestaudio/best' if quality == "best" else f'bestaudio[abr<={quality}]/bestaudio'

    ydl_opts = {
        'format': format_selector,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': quality if quality != "best" else '0',  # 0 berarti kualitas terbaik
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

        # Cari file MP3 yang sudah dikonversi
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

# --- FUNGSI BANTUAN ---

async def cleanup(directory: Path):
    """Membersihkan direktori sementara setelah delay 10 menit."""
    await asyncio.sleep(600) # Tunggu 10 menit
    try:
        for item in directory.iterdir():
            if item.is_file():
                item.unlink()
        directory.rmdir()
        print(f"Cleaned up directory: {directory}")
    except Exception as e:
        print(f"Error during cleanup: {e}")
