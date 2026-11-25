import json
import os
import time
from fastapi import HTTPException

def analyze_video_with_gemini(source, transcript, clip_length, limit):
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise HTTPException(503, "Add GEMINI_API_KEY in Render Environment and redeploy.")
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
        video = client.files.upload(file=str(source))
        try:
            deadline = time.time() + 600
            while video.state and video.state.name == "PROCESSING":
                if time.time() > deadline:
                    raise RuntimeError("Gemini video processing timed out.")
                time.sleep(5)
                video = client.files.get(name=video.name)
            if video.state and video.state.name == "FAILED":
                raise RuntimeError("Gemini could not process this video.")
            transcript_text = " ".join("[%.1f-%.1f] %s" % (x["start"], x["end"], x["text"]) for x in transcript["segments"])
            prompt = (
                "Act as an expert short-form video editor. Analyze the actual video visuals and audio "
                "together with this timestamped transcript. Find up to %s distinct self-contained "
                "moments, each no longer than %s seconds. Do not choose by keywords alone. Prefer "
                "strong hooks, funny or emotional reactions, useful insights, surprising reveals, "
                "demonstrations, story turns and satisfying payoffs. Reject greetings, introductions, "
                "repetition, dead air and contextless fragments. Use original-video timestamps in seconds. "
                "Start and end on natural boundaries. Return only JSON: "
                '{"clips":[{"start":12.3,"end":42.1,"hook":"short title","reason":"why engaging","quality_score":85,"visual_notes":"visible action"}]}. '
                "Score editorial quality, not guaranteed virality. Transcript: %s"
            ) % (limit, clip_length, transcript_text[:24000])
            response = client.models.generate_content(
                model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
                contents=[video, prompt],
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2, max_output_tokens=5000)
            )
            data = json.loads(response.text or "{}")
            duration = float(transcript["duration"])
            clips = []
            for item in data.get("clips", []):
                try:
                    start = max(0.0, float(item["start"]))
                    end = min(duration, float(item["end"]))
                except (KeyError, TypeError, ValueError):
                    continue
                if end <= start or end - start < 8:
                    continue
                if end - start > clip_length:
                    end = start + clip_length
                if end > duration:
                    end = duration
                    start = max(0.0, end - clip_length)
                spoken = " ".join(x["text"] for x in transcript["segments"] if x["start"] < end and x["end"] > start)
                clips.append({
                    "start": round(start, 2), "end": round(end, 2), "duration": round(end-start, 2),
                    "score": max(1, min(99, float(item.get("quality_score", 50)))),
                    "hook": str(item.get("hook", "AI highlight"))[:160],
                    "reason": str(item.get("reason", ""))[:300],
                    "visual_notes": str(item.get("visual_notes", ""))[:240], "text": spoken[:600]
                })
            clips.sort(key=lambda x: x["score"], reverse=True)
            selected = []
            for clip in clips:
                if all(clip["end"] <= old["start"] or clip["start"] >= old["end"] for old in selected):
                    selected.append(clip)
                if len(selected) >= limit:
                    break
            if not selected:
                raise RuntimeError("Gemini found no usable moments in this video.")
            return selected
        finally:
            try:
                client.files.delete(name=video.name)
            except Exception:
                pass
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "Gemini video analysis failed: " + str(exc)[:350])
