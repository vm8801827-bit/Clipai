import os, re, shutil, subprocess, uuid
from pathlib import Path
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
STORAGE = Path(os.getenv("CLIPAI_STORAGE", ROOT / "storage"))
UPLOADS, OUTPUTS = STORAGE / "uploads", STORAGE / "outputs"
UPLOADS.mkdir(parents=True, exist_ok=True)
OUTPUTS.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "0"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024 if MAX_UPLOAD_MB > 0 else 0
TRANSCRIPTS = {}
JOBS = {}
JOB_POOL = ThreadPoolExecutor(max_workers=1)

app = FastAPI(title="Clipai API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/media", StaticFiles(directory=str(OUTPUTS)), name="media")

class RenderRequest(BaseModel):
    filename: str
    start: float = Field(ge=0)
    duration: float = Field(gt=0, le=180)
    aspect: str = "9:16"
    captions: bool = True

def safe_upload(filename):
    path = UPLOADS / Path(filename).name
    if not path.exists() or path.parent != UPLOADS:
        raise HTTPException(404, "Uploaded video not found.")
    return path

@lru_cache(maxsize=1)
def whisper_model():
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise HTTPException(503, "Speech recognition is unavailable. Install faster-whisper.")
    model_size = os.getenv("WHISPER_MODEL", "small")
    return WhisperModel(model_size, device=os.getenv("WHISPER_DEVICE", "cpu"), compute_type=os.getenv("WHISPER_COMPUTE", "int8"))

def transcribe(filename):
    if filename in TRANSCRIPTS:
        return TRANSCRIPTS[filename]
    source = safe_upload(filename)
    try:
        segments, info = whisper_model().transcribe(str(source), vad_filter=True, word_timestamps=False)
        items = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments if s.text.strip()]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Transcription failed: {str(exc)[:250]}")
    if not items:
        raise HTTPException(422, "No clear speech was detected in this video.")
    result = {"language": info.language, "duration": round(info.duration, 2), "segments": items}
    TRANSCRIPTS[filename] = result
    return result

HOOK_WORDS = {"wait", "what", "why", "how", "crazy", "insane", "never", "secret", "truth", "actually", "bro", "wow", "impossible", "mistake", "problem", "money", "love", "hate", "scared", "wild", "guess"}
def find_highlights(segments, duration, clip_length=30, limit=20):
    candidates = []
    # Score overlapping transcript windows; these are heuristic suggestions, not a promise of virality.
    for i, seg in enumerate(segments):
        start = seg["start"]
        end = min(duration, start + clip_length)
        group = [s for s in segments if s["start"] < end and s["end"] > start]
        text = " ".join(s["text"] for s in group).strip()
        words = re.findall(r"[\w']+", text.lower())
        if len(words) < 12:
            continue
        hooks = sum(1 for w in words if w in HOOK_WORDS)
        punctuation = sum(text.count(p) for p in "!?")
        density = min(len(words) / 35, 1.5)
        score = round(min(99, 30 + hooks * 5 + punctuation * 4 + density * 15), 1)
        candidates.append({"start": round(start, 1), "end": round(end, 1), "duration": round(end-start, 1), "score": score, "reason": "Strong conversational hook" if hooks else "Dense, continuous speech", "text": text[:420]})
    candidates.sort(key=lambda x: x["score"], reverse=True)
    selected = []
    for item in candidates:
        if all(abs(item["start"] - old["start"]) > 18 for old in selected):
            selected.append(item)
        if len(selected) == limit:
            break
    return selected

@app.get("/api/health")
def health():
    return {"ok": True, "service": "clipai-api", "version": "0.2.0"}

@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".mp4", ".mov", ".m4v", ".webm"}:
        raise HTTPException(400, "Upload an MP4, MOV, M4V, or WEBM video.")
    name = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOADS / name
    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if MAX_UPLOAD_BYTES and size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"Video exceeds the configured {MAX_UPLOAD_MB} MB application limit.")
                # Free hosts have finite temporary storage. Keep a safety reserve rather than
                # allowing a large upload to fill the service disk and crash the app.
                if shutil.disk_usage(STORAGE).free < len(chunk) + 64 * 1024 * 1024:
                    raise HTTPException(507, "Not enough temporary storage on the free server for this video. Try a smaller/compressed file.")
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return {"filename": name, "original_name": file.filename, "size": size}

def _run_analysis(job_id, filename, payload):
    JOBS[job_id]["status"] = "running"
    try:
        transcript = transcribe(filename)
        clip_length = int(payload.get("clip_length", 30))
        clip_count = int(payload.get("clip_count", 10))
        if clip_length not in (30, 60):
            clip_length = 30
        if clip_count not in (10, 20, 30, 40):
            clip_count = 10
        highlights = find_highlights(transcript["segments"], transcript["duration"], clip_length, clip_count)
        JOBS[job_id].update(status="completed", result={**transcript, "highlights": highlights})
    except HTTPException as exc:
        JOBS[job_id].update(status="failed", error=str(exc.detail))
    except Exception as exc:
        JOBS[job_id].update(status="failed", error=str(exc)[:500])

@app.post("/api/analyze")
def analyze_video(payload: dict):
    filename = str(payload.get("filename", ""))
    safe_upload(filename)
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "queued", "type": "analysis"}
    JOB_POOL.submit(_run_analysis, job_id, filename, payload)
    return {"job_id": job_id}

@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found. The free server may have restarted; please retry.")
    return job

def make_srt(segments, clip_start, clip_end, path):
    def stamp(seconds):
        ms = int(max(0, seconds) * 1000)
        h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"
    rows, idx = [], 1
    for seg in segments:
        a, b = max(seg["start"], clip_start), min(seg["end"], clip_end)
        if b <= a:
            continue
        rows += [str(idx), f"{stamp(a-clip_start)} --> {stamp(b-clip_start)}", seg["text"], ""]
        idx += 1
    path.write_text("\n".join(rows), encoding="utf-8")
    return idx > 1

def _render_clip(req: RenderRequest):
    source = safe_upload(req.filename)
    if req.aspect != "9:16":
        raise HTTPException(400, "Only 9:16 output is currently supported.")
    if shutil.which("ffmpeg") is None:
        raise HTTPException(503, "FFmpeg is not installed on the server.")
    transcript = TRANSCRIPTS.get(req.filename)
    subtitle = OUTPUTS / f"{uuid.uuid4().hex}.srt"
    use_captions = False
    if req.captions:
        if not transcript:
            transcript = transcribe(req.filename)
        use_captions = make_srt(transcript["segments"], req.start, req.start + req.duration, subtitle)
    output_name = f"clip-{uuid.uuid4().hex}.mp4"
    output = OUTPUTS / output_name
    vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    if use_captions:
        escaped = str(subtitle).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        vf += f",subtitles='{escaped}':force_style='FontName=DejaVu Sans,FontSize=18,Outline=2,Shadow=1,Alignment=2,MarginV=140'"
    command = ["ffmpeg", "-y", "-ss", str(req.start), "-i", str(source), "-t", str(req.duration), "-vf", vf,
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-movflags", "+faststart", str(output)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=900)
    subtitle.unlink(missing_ok=True)
    if result.returncode:
        raise HTTPException(500, result.stderr[-1400:] or "FFmpeg render failed.")
    return {"filename": output_name, "url": f"/media/{output_name}", "captions": use_captions}

def _run_render(job_id, payload):
    JOBS[job_id]["status"] = "running"
    try:
        result = _render_clip(RenderRequest(**payload))
        JOBS[job_id].update(status="completed", result=result)
    except HTTPException as exc:
        JOBS[job_id].update(status="failed", error=str(exc.detail))
    except Exception as exc:
        JOBS[job_id].update(status="failed", error=str(exc)[:500])

@app.post("/api/render")
def render_clip(req: RenderRequest):
    safe_upload(req.filename)
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "queued", "type": "render"}
    JOB_POOL.submit(_run_render, job_id, req.dict())
    return {"job_id": job_id}

# Serve the built React app from the same origin as the API.
WEB = ROOT.parent / "frontend" / "dist"
if WEB.exists():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="frontend")
