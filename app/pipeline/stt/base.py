"""Speech-to-text component interface.

Swap implementations by providing another `Transcriber` subclass and
registering it in `app/pipeline/registry.py` — nothing else in the app
needs to change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Transcript:
    """Normalized output of any speech-to-text backend."""

    text: str
    language: str = ""
    duration_seconds: float = 0.0
    backend: str = ""


class Transcriber(ABC):
    """Interface every speech-to-text backend must implement."""

    name: str = "base"

    @abstractmethod
    def transcribe(self, audio_path: Path) -> Transcript:
        """Convert an audio file on disk into transcript text."""

    def warmup(self) -> None:
        """Optional: preload models. Default does nothing."""
