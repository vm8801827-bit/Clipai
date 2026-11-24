import os, shutil, subprocess, uuid
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "storage" / "uploads"
OUTPUTS = ROOT / "storage" / "outputs"
UPLOADS.mkdir(parents=True, exist_ok=True)
OUTPUTS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Clipai API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/media", StaticFiles(directory=str(OUTPUTS)), name="media")

class RenderRequest(BaseModel):
    filename: str
    start: float = Field(ge=0)
    duration: float = Field(gt=0, le=180)
    aspect: str = "9:16"

@app.get("/api/health")
def health():
    return {"ok": True, "service": "clipai-api"}

@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".mp4", ".mov", ".m4v", ".webm"}:
        raise HTTPException(400, "Upload an MP4, MOV, M4V, or WEBM video.")
    name = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOADS / name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return {"filename": name, "original_name": file.filename, "size": dest.stat().st_size}

@app.post("/api/render")
def render_clip(req: RenderRequest):
    source = UPLOADS / Path(req.filename).name
    if not source.exists():
        raise HTTPException(404, "Uploaded video not found.")
    if req.aspect != "9:16":
        raise HTTPException(400, "Only 9:16 output is currently supported.")
    if shutil.which("ffmpeg") is None:
        raise HTTPException(503, "FFmpeg is not installed on the server.")
    output_name = f"clip-{uuid.uuid4().hex}.mp4"
    output = OUTPUTS / output_name
    command = ["ffmpeg", "-y", "-ss", str(req.start), "-i", str(source), "-t", str(req.duration),
               "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-movflags", "+faststart", str(output)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise HTTPException(500, result.stderr[-1200:] or "FFmpeg render failed.")
    return {"filename": output_name, "url": f"/media/{output_name}"}
