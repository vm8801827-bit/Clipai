import os, re, shutil, subprocess, uuid
from urllib.parse import urlparse
from pathlib import Path
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from app.gemini_ai import analyze_video_with_gemini
from app.captions import make_ass

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
DOWNLOAD_POOL = ThreadPoolExecutor(max_workers=2)

app = FastAPI(title="Clipai API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/media", StaticFiles(directory=str(OUTPUTS)), name="media")

class RenderRequest(BaseModel):
    filename: str
    start: float = Field(ge=0)
    duration: float = Field(gt=0, le=180)
    aspect: str = "9:16"
    captions: bool = True
    caption_style: str = "classic"

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
    return WhisperModel(model_size, device=os.getenv("WHISPER_DEVICE", "cpu"), compute_type=os.getenv("WHISPER_COMPUTE", "int8"), cpu_threads=1, num_workers=1)

def transcribe(filename):
    if filename in TRANSCRIPTS:
        return TRANSCRIPTS[filename]
    source = safe_upload(filename)
    try:
        # Decode only the audio stream to a small mono 16 kHz WAV before Whisper.
        # Passing a large video container directly makes PyAV decode/cache much more data
        # than needed and can exhaust the memory on small free instances.
        audio_path = UPLOADS / f"{uuid.uuid4().hex}-audio.wav"
        try:
            extracted = subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio_path)],
                capture_output=True, text=True, timeout=900
            )
            if extracted.returncode:
                raise HTTPException(422, "Could not extract audio from this video. Try an MP4 with a clear audio track.")
            segments, info = whisper_model().transcribe(str(audio_path), vad_filter=True, word_timestamps=True, beam_size=1)
            items = []
            for seg in segments:
                if not seg.text.strip():
                    continue
                words = [{"start": round(w.start, 3), "end": round(w.end, 3), "text": w.word} for w in (seg.words or []) if w.start is not None and w.end is not None]
                items.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip(), "words": words})
        finally:
            audio_path.unlink(missing_ok=True)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Transcription failed: {str(exc)[:250]}")
    if not items:
        raise HTTPException(422, "No clear speech was detected in this video.")
    result = {"language": info.language, "duration": round(info.duration, 2), "segments": items}
    TRANSCRIPTS[filename] = result
    return result

HOOK_WORDS = {
    "wait", "what", "why", "how", "crazy", "insane", "never", "secret", "truth",
    "actually", "wow", "impossible", "mistake", "problem", "money", "love",
    "hate", "scared", "wild", "guess", "because", "but", "however", "imagine",
    "remember", "listen", "seriously", "exactly", "finally", "discovered"
}
EMOTION_WORDS = {
    "amazing", "awful", "beautiful", "best", "worst", "fail", "failed", "win",
    "won", "shocking", "surprising", "terrible", "incredible", "ridiculous",
    "crazy", "insane", "love", "hate", "fear", "secret", "truth", "mistake",
    "success", "million", "billion", "free", "easy", "hard", "danger", "dangerous"
}

def find_highlights(segments, duration, clip_length=30, limit=20):
    """Rank complete speech moments, then select diverse non-overlapping windows.

    This is a transparent transcript-based heuristic, not an LLM or a guarantee
    that a clip will go viral. Candidate windows are aligned to speech boundaries
    and ranked on hook, language, pacing, and completeness rather than fixed cuts.
    """
    if not segments or duration <= 0:
        return []

    clip_length = max(10, min(int(clip_length), 60))
    limit = max(1, min(int(limit), 40))
    clean = []
    for seg in segments:
        text = re.sub(r"\s+", " ", str(seg.get("text", ""))).strip()
        try:
            a, b = float(seg["start"]), float(seg["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if text and b > a and a < duration:
            clean.append({"start": max(0.0, a), "end": min(float(duration), b), "text": text})
    clean.sort(key=lambda x: x["start"])
    if not clean:
        return []

    # Sentence-like boundaries give candidate clips a coherent beginning.
    starts = set()
    for i, seg in enumerate(clean):
        starts.add(i)
        if i and re.search(r"[.!?…][\"')\]]?$", clean[i-1]["text"]):
            starts.add(i)
    # Add a few later starts in long monologues, but avoid hundreds of near-identical windows.
    starts = sorted(starts)
    candidates = []
    for i in starts:
        clip_start = clean[i]["start"]
        if clip_start >= duration - 5:
            continue
        clip_end = min(float(duration), clip_start + clip_length)
        group = [s for s in clean if s["start"] < clip_end and s["end"] > clip_start]
        if not group:
            continue
        spoken = " ".join(s["text"] for s in group).strip()
        words = re.findall(r"[A-Za-z0-9']+", spoken.lower())
        count = len(words)
        if count < 18:
            continue

        first_sentence = re.split(r"(?<=[.!?])\s+", spoken, maxsplit=1)[0]
        first_words = re.findall(r"[A-Za-z0-9']+", first_sentence.lower())
        hook_count = sum(w in HOOK_WORDS for w in first_words[:18])
        emotion_count = sum(w in EMOTION_WORDS for w in words)
        questions = spoken.count("?")
        exclamations = spoken.count("!")
        numbers = len(re.findall(r"\b\d+(?:\.\d+)?%?\b", spoken))
        contrast = len(re.findall(r"\b(but|however|instead|although|except|yet|turns out)\b", spoken.lower()))
        direct_address = len(re.findall(r"\b(you|your|we|I|listen|look|imagine)\b", words.__str__()))
        speech_duration = max(1.0, group[-1]["end"] - group[0]["start"])
        words_per_second = count / speech_duration
        pacing = max(0.0, 1.0 - abs(words_per_second - 2.35) / 2.35)
        density = min(count / max(25.0, clip_length * 2.0), 1.0)
        opening_bonus = 1.0 if re.match(r"^(why|how|what|wait|listen|imagine|the truth|here'?s|this is)\b", spoken.lower()) else 0.0
        ending_bonus = 1.0 if re.search(r"[.!?][\"')\]]?$", group[-1]["text"]) else 0.0
        # Penalize fragments that begin mid-sentence or are mostly silence.
        fragment_penalty = 1.2 if i and not re.search(r"[.!?…][\"')\]]?$", clean[i-1]["text"]) else 0.0
        silence_ratio = max(0.0, (clip_end - clip_start - speech_duration) / max(1.0, clip_end - clip_start))

        raw = (
            2.2 * min(hook_count, 3)
            + 1.15 * min(emotion_count, 5)
            + 1.6 * min(questions, 2)
            + 0.7 * min(exclamations, 2)
            + 0.8 * min(numbers, 3)
            + 1.0 * min(contrast, 3)
            + 2.0 * opening_bonus
            + 1.0 * ending_bonus
            + 3.0 * pacing
            + 2.0 * density
            - 3.0 * min(silence_ratio, 0.8)
            - fragment_penalty
        )
        score = round(max(1.0, min(99.0, 35.0 + raw * 2.0)), 1)
        reason_parts = []
        if opening_bonus or hook_count:
            reason_parts.append("strong opening hook")
        if emotion_count >= 2 or exclamations:
            reason_parts.append("emotional language")
        if questions or contrast:
            reason_parts.append("curiosity or story turn")
        if pacing > 0.7:
            reason_parts.append("good speech pacing")
        reason = ", ".join(reason_parts[:3]) or "continuous, information-rich speech"
        candidates.append({
            "start": round(clip_start, 2),
            "end": round(clip_end, 2),
            "duration": round(clip_end - clip_start, 2),
            "score": score,
            "reason": reason,
            "text": spoken[:600]
        })

    # Greedy diversity: prioritize quality while preventing duplicate/nearby clips.
    candidates.sort(key=lambda x: (x["score"], len(x["text"])), reverse=True)
    selected = []
    min_gap = max(12.0, clip_length * 0.55)
    for item in candidates:
        if all(
            item["end"] <= old["start"] + min_gap or item["start"] >= old["end"] - min_gap
            for old in selected
        ):
            selected.append(item)
        if len(selected) >= limit:
            break
    selected.sort(key=lambda x: x["start"])
    return selected

@app.get("/api/health")
def health():
    """Expose safe deployment diagnostics without revealing secrets."""
    import importlib.util
    return {
        "ok": True,
        "service": "clipai-api",
        "version": "0.2.0",
        "checks": {
            "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
            "ffmpeg_available": bool(shutil.which("ffmpeg")),
            "whisper_installed": importlib.util.find_spec("faster_whisper") is not None,
            "storage_writable": os.access(STORAGE, os.W_OK),
        },
    }

def _run_import(job_id, raw_url):
    JOBS[job_id]["status"] = "running"
    name = f"{uuid.uuid4().hex}.%(ext)s"
    template = str(UPLOADS / name)
    try:
        result = subprocess.run(
            ["python", "-m", "yt_dlp", "--no-playlist", "--no-warnings",
             "--newline", "--retries", "3", "--fragment-retries", "3",
             "--concurrent-fragments", "8", "--socket-timeout", "20",
             "--restrict-filenames", "--merge-output-format", "mp4",
             "--max-filesize", "2G", "-f", "best[height<=720]/best",
             "-o", template, raw_url],
            capture_output=True, text=True, timeout=900
        )
        if result.returncode:
            raise RuntimeError("Could not import this link. It may be private, login-required, restricted, or unsupported. " + (result.stderr[-500:] or ""))
        matches = sorted(UPLOADS.glob(name.replace("%(ext)s", "*")), key=lambda p: p.stat().st_mtime, reverse=True)
        if not matches:
            raise RuntimeError("The platform did not return a downloadable video.")
        path = matches[0]
        JOBS[job_id].update(status="completed", result={
            "filename": path.name, "original_name": path.name,
            "size": path.stat().st_size, "source": "url"
        })
    except subprocess.TimeoutExpired:
        JOBS[job_id].update(status="failed", error="Link import timed out. Try a shorter/public video or upload the file directly.")
    except Exception as exc:
        JOBS[job_id].update(status="failed", error=str(exc)[:900])

@app.post("/api/import-url")
def import_video_url(payload: dict):
    raw_url = str(payload.get("url", "")).strip()
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").lower()
    allowed = ("youtube.com", "youtu.be", "tiktok.com", "instagram.com", "facebook.com", "fb.watch", "twitch.tv", "x.com", "twitter.com")
    if parsed.scheme not in ("http", "https") or not any(host == d or host.endswith("." + d) for d in allowed):
        raise HTTPException(400, "Paste a public video URL from YouTube, TikTok, Instagram, Facebook, Twitch or X.")
    if not shutil.which("ffmpeg"):
        raise HTTPException(503, "FFmpeg is not installed on the server.")
    if not shutil.which("python"):
        raise HTTPException(503, "Python runtime is unavailable on the server.")
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "queued", "type": "import"}
    DOWNLOAD_POOL.submit(_run_import, job_id, raw_url)
    return {"job_id": job_id}

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
            while chunk := await file.read(8 * 1024 * 1024):
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
        source = safe_upload(filename)
        try:
            highlights = analyze_video_with_gemini(source, transcript, clip_length, clip_count)
            engine = "Gemini video understanding"
        except Exception as gemini_error:
            # Keep clip generation usable when Gemini is temporarily overloaded or unavailable.
            highlights = find_highlights(transcript["segments"], transcript["duration"], clip_length, clip_count)
            if not highlights:
                raise gemini_error
            engine = "Transcript fallback (Gemini temporarily unavailable)"
        JOBS[job_id].update(status="completed", result={**transcript, "highlights": highlights, "analysis_engine": engine})
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
    subtitle = OUTPUTS / f"{uuid.uuid4().hex}.ass"
    use_captions = False
    if req.captions:
        if not transcript:
            transcript = transcribe(req.filename)
        use_captions = make_ass(transcript["segments"], req.start, req.start + req.duration, subtitle, req.caption_style)
    output_name = f"clip-{uuid.uuid4().hex}.mp4"
    output = OUTPUTS / output_name
    vf = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280"
    if use_captions:
        escaped = str(subtitle).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        styles = {
            "classic": "FontName=DejaVu Sans,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Shadow=1,Alignment=2,MarginV=140",
            "bold": "FontName=DejaVu Sans,FontSize=23,Bold=1,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,Outline=3,Shadow=1,Alignment=2,MarginV=150",
            "minimal": "FontName=DejaVu Sans,FontSize=16,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,Outline=1,Shadow=0,Alignment=2,MarginV=110"
        }
        style = styles.get(req.caption_style, styles["classic"])
        vf += f",subtitles='{escaped}'"
    command = ["ffmpeg", "-y", "-ss", str(req.start), "-i", str(source), "-t", str(req.duration), "-vf", vf,
               "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26", "-threads", "2", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(output)]
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
