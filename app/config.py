"""Application configuration.

All tunables live here so the pipeline components stay decoupled from
environment specifics.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = PROJECT_DIR / "data" / "uploads"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# --- Speech-to-text ---
WHISPER_MODEL = os.getenv("MEETMIND_WHISPER_MODEL", "base.en")
WHISPER_DEVICE = os.getenv("MEETMIND_WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("MEETMIND_WHISPER_COMPUTE_TYPE", "int8")

# --- Upload constraints ---
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a"}
MAX_UPLOAD_BYTES = int(os.getenv("MEETMIND_MAX_UPLOAD_MB", "100")) * 1024 * 1024

# --- Summarization ---
SUMMARY_SENTENCES = int(os.getenv("MEETMIND_SUMMARY_SENTENCES", "3"))
MAX_KEY_POINTS = int(os.getenv("MEETMIND_MAX_KEY_POINTS", "6"))
MAX_LIST_ITEMS = int(os.getenv("MEETMIND_MAX_LIST_ITEMS", "8"))
