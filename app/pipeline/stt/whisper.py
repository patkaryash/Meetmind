"""Faster-Whisper implementation of the `Transcriber` interface.

The model is loaded lazily on first use (and cached) so app startup stays
fast and repeated requests don't pay the load cost.
"""
from __future__ import annotations

from pathlib import Path

from app.config import (
    WHISPER_BEAM_SIZE,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE,
    WHISPER_MODEL,
)
from app.pipeline.stt.base import Transcriber, Transcript


class FasterWhisperTranscriber(Transcriber):
    name = "faster-whisper"

    def __init__(
        self,
        model_name: str = WHISPER_MODEL,
        device: str = WHISPER_DEVICE,
        compute_type: str = WHISPER_COMPUTE_TYPE,
        beam_size: int = WHISPER_BEAM_SIZE,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_name, device=self.device, compute_type=self.compute_type
            )
        return self._model

    def warmup(self) -> None:
        self._load()

    def transcribe(self, audio_path: Path) -> Transcript:
        model = self._load()
        segments, info = model.transcribe(
            str(audio_path),
            beam_size=self.beam_size,
            vad_filter=True,
        )
        parts = [seg.text.strip() for seg in segments if seg.text.strip()]
        return Transcript(
            text=" ".join(parts),
            language=info.language or "",
            duration_seconds=float(info.duration or 0.0),
            backend=f"{self.name}:{self.model_name}",
        )
