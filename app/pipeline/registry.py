"""Component registry.

Single place where concrete STT / summarization backends are chosen.
To swap a component, change only the factory functions below.
"""
from __future__ import annotations

import threading

from app.pipeline.stt.base import Transcriber
from app.pipeline.summarize.base import Summarizer

_lock = threading.Lock()
_transcriber: Transcriber | None = None
_summarizer: Summarizer | None = None


def get_transcriber() -> Transcriber:
    """Factory: speech-to-text backend (swap here)."""
    global _transcriber
    if _transcriber is None:
        with _lock:
            if _transcriber is None:
                from app.pipeline.stt.whisper import FasterWhisperTranscriber

                _transcriber = FasterWhisperTranscriber()
    return _transcriber


def get_summarizer() -> Summarizer:
    """Factory: summarization backend (swap here)."""
    global _summarizer
    if _summarizer is None:
        with _lock:
            if _summarizer is None:
                from app.pipeline.summarize.extractive import ExtractiveSummarizer

                _summarizer = ExtractiveSummarizer()
    return _summarizer
