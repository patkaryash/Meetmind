"""Application configuration.

All tunables live here so the pipeline components stay decoupled from
environment specifics.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = PROJECT_DIR / "data" / "uploads"

# Load GEMINI_API_KEY / GEMINI_MODEL from .env (backend only, never frontend).
load_dotenv(PROJECT_DIR / ".env")

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# --- Speech-to-text ---
WHISPER_MODEL = os.getenv("MEETMIND_WHISPER_MODEL", "base.en")
WHISPER_DEVICE = os.getenv("MEETMIND_WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("MEETMIND_WHISPER_COMPUTE_TYPE", "int8")
# Greedy decoding (1) is ~2-4x faster than beam 5 on CPU with only a small
# accuracy drop — fine for a demo. Raise to 5 for best quality.
WHISPER_BEAM_SIZE = int(os.getenv("MEETMIND_WHISPER_BEAM_SIZE", "1"))

# --- Upload constraints ---
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a"}
MAX_UPLOAD_BYTES = int(os.getenv("MEETMIND_MAX_UPLOAD_MB", "100")) * 1024 * 1024

# --- Summarization ---
SUMMARY_SENTENCES = int(os.getenv("MEETMIND_SUMMARY_SENTENCES", "3"))
MAX_KEY_POINTS = int(os.getenv("MEETMIND_MAX_KEY_POINTS", "6"))
MAX_LIST_ITEMS = int(os.getenv("MEETMIND_MAX_LIST_ITEMS", "8"))

# --- Gemini analysis (backend only) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
# Safety cap so a very long transcript doesn't blow the prompt / cost.
GEMINI_MAX_TRANSCRIPT_CHARS = int(os.getenv("GEMINI_MAX_TRANSCRIPT_CHARS", "24000"))
# Bounds Gemini latency/cost: the report JSON is small, no need for long output.
GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "2000"))
