from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def root():
    """Endpoint untuk memeriksa status server."""
    return {"message": "Y-Player API is running", "status": "active"}