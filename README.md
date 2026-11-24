# Clipai — AI video clipping studio

Clipai is a self-hosted video clipping MVP built with React, FastAPI, FFmpeg and Faster-Whisper.

## Included
- Upload MP4, MOV, M4V and WEBM files.
- Import supported public video links with yt-dlp (availability depends on the source platform and its terms).
- Transcribe speech using Faster-Whisper.
- Suggest candidate highlights using transparent transcript heuristics. Scores are suggestions, not trained virality predictions.
- Select or deselect suggestions and edit each clip's start time and duration.
- Render 9:16 MP4 clips with optional burned-in subtitles (Classic, Bold, Minimal).
- Preview and download individual clips.

## Not included yet
- Accounts, authentication, billing, team workspaces or cloud media library.
- Face tracking / speaker-aware reframing, diarization, word-by-word animated captions, gaming layouts or automatic social publishing.
- These require additional services/models and are not represented as working features in this MVP.

## Local development
Install FFmpeg, Python 3.12 and Node 22.

Backend:
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend:
```bash
cd frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev
```

## Docker
```bash
docker build -t clipai .
docker run --rm -p 10000:10000 clipai
```

## Render deployment notes
The repository includes a Render Blueprint and Dockerfile. Create a Blueprint from the repository and deploy the service. The free instance has limited RAM, CPU and ephemeral disk; Whisper model download and video transcoding may exceed those limits for longer/larger files. Files and in-memory job state are not durable across restarts. For reliable use, configure persistent storage and an instance sized for FFmpeg and Whisper.

## API
- `GET /api/health`
- `POST /api/upload` multipart field `file`
- `POST /api/import-url` JSON `{"url":"https://..." }`
- `POST /api/analyze` JSON `{"filename":"...","clip_length":30,"clip_count":10}`
- `GET /api/jobs/{job_id}`
- `POST /api/render` JSON with `filename`, `start`, `duration`, optional `captions`, `caption_style`
- `GET /media/{filename}`

This is an MVP foundation; do not upload sensitive or irreplaceable media to an ephemeral demo deployment.
