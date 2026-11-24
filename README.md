# Clipai — AI Video Clipping Platform

Clipai turns long-form videos into vertical short-form clips.

## Features in this MVP
- Upload MP4, MOV, M4V and WEBM videos (500 MB default limit).
- Transcribe spoken audio with Faster-Whisper.
- Suggest up to five candidate moments using transcript-based scoring. Scores are heuristic suggestions, not a guarantee of virality.
- Edit clip start and duration.
- Render 1080×1920 vertical MP4 with optional burned-in subtitles.
- Preview and download the result.

## Stack
- React + Vite frontend
- FastAPI backend
- FFmpeg video processing
- Faster-Whisper speech recognition

## Run locally
Install FFmpeg first, then:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

For local Vite development, set `VITE_API_URL=http://localhost:8000` in `frontend/.env.local`.

## Docker
```bash
docker build -t clipai .
docker run --rm -p 10000:10000 clipai
```

## Deploy on Render
Create a new Blueprint from this GitHub repository and review the service settings before deploying. The Dockerfile installs FFmpeg and serves both the built frontend and API from one web service.

**Important:** speech recognition downloads a Whisper model on first analysis and can be CPU/RAM intensive. Use an instance with enough memory for the selected model. Render's default filesystem is ephemeral; configure a persistent disk mounted at `/app/backend/storage` before using this for important user uploads or generated clips. Persistent disks are a paid feature and affect deployment behavior.

## Current limitations
- Highlight suggestions use transcript heuristics; they are not a trained virality predictor.
- No user accounts, payments, team workspaces, cloud object storage, face tracking, speaker diarization, or advanced caption styling yet.
- This is an MVP foundation, not a claim of feature parity with commercial clipping platforms.
