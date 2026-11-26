# ClipGenius AI Pro

A separate deployment of the ClipGenius short-form video editor. The existing `clipai-qu6c` service and `main` branch are intentionally left untouched.

## Features
- Upload MP4, MOV, M4V, and WEBM videos
- Import supported public video links through yt-dlp
- Speech transcription with faster-whisper
- Gemini video understanding to suggest distinct highlight moments
- Transcript-based fallback when Gemini is temporarily unavailable
- Review and adjust suggested clip start/length
- Render vertical 9:16, square 1:1, or landscape 16:9 MP4 clips
- Burned-in captions, optional hook title, and ZIP download

## Deploy
Create a new Render Web Service from this repository using branch `clipgenius-ai-pro`, Docker runtime, and service name `clipgenius-ai-pro`. Do not change the existing service.

Set `GEMINI_API_KEY` in the new Render service's Environment settings. Never commit the key to GitHub.

The included Render configuration uses the free plan and temporary container storage. Free instances can restart or spin down; uploads and background jobs may be lost after a restart. For reliable long-running production use, attach a persistent disk at `/var/data` and set `CLIPAI_STORAGE=/var/data` on a paid Render instance. Persistent storage does not by itself make in-memory jobs survive a restart; use a durable task queue/database before claiming restart-safe processing.

## Health check
`GET /api/health` reports whether Gemini is configured, FFmpeg and Whisper are installed, and storage is writable. It never returns secret values.
