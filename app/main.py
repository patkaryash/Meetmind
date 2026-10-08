"""MeetMind — FastAPI application.

Workflow: upload audio → analyze meeting → display structured summary.
"""
from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import (
    ALLOWED_AUDIO_EXTENSIONS,
    GEMINI_MODEL,
    MAX_UPLOAD_BYTES,
    STATIC_DIR,
    UPLOAD_DIR,
)
from app.pipeline.runner import MeetingPipeline
from app.pipeline.summarize.gemini import GeminiAnalysisError
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="MeetMind", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline = MeetingPipeline()


@app.on_event("startup")
def _startup() -> None:
    # Load the Whisper model in the background of startup so the first
    # request doesn't stall. Failures are swallowed: warmup is best-effort.
    import threading

    threading.Thread(target=pipeline.warmup, daemon=True).start()


@app.get("/api/health")
def health() -> dict:
    from app.config import GEMINI_API_KEY

    return {
        "status": "ok",
        "gemini_configured": bool(GEMINI_API_KEY),
        "gemini_model": GEMINI_MODEL,
    }


@app.post("/api/analyze")
async def analyze(audio: UploadFile = File(...)) -> JSONResponse:
    # -- validate ---------------------------------------------------------- #
    filename = audio.filename or "upload"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. "
                   f"Allowed: {', '.join(sorted(ALLOWED_AUDIO_EXTENSIONS))}",
        )

    # -- save to a private temp location ----------------------------------- #
    upload_path = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
    size = 0
    try:
        with upload_path.open("wb") as out:
            while chunk := await audio.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="File too large.")
                out.write(chunk)
    except Exception:
        upload_path.unlink(missing_ok=True)
        raise

    if size == 0:
        upload_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Empty file.")

    # -- run the pipeline --------------------------------------------------- #
    started = time.perf_counter()
    try:
        result = pipeline.run(upload_path)
    except GeminiAnalysisError as exc:
        # Transcription worked but LLM analysis failed: 502 with a useful
        # message (bad key, quota, invalid JSON, ...) instead of a crash.
        raise HTTPException(status_code=502, detail=f"Meeting analysis failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — surface as a clean API error
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {type(exc).__name__}: {exc}",
        ) from exc
    finally:
        upload_path.unlink(missing_ok=True)

    payload = result.to_dict()
    payload["filename"] = filename
    payload["timing"]["request_seconds"] = round(time.perf_counter() - started, 2)
    return JSONResponse(payload)


# Serve the dashboard last so API routes take precedence.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
