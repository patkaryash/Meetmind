"""Pipeline runner: audio file in → structured meeting summary out."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from app.pipeline.registry import get_summarizer, get_transcriber
from app.pipeline.summarize.base import MeetingSummary


@dataclass
class PipelineResult:
    transcript: str
    summary: MeetingSummary
    language: str = ""
    duration_seconds: float = 0.0
    stt_backend: str = ""
    summarizer_backend: str = ""
    transcribe_seconds: float = 0.0
    summarize_seconds: float = 0.0

    @property
    def total_seconds(self) -> float:
        return self.transcribe_seconds + self.summarize_seconds

    def to_dict(self) -> dict:
        return {
            "transcript": self.transcript,
            "summary": self.summary.summary,
            "key_points": self.summary.key_points,
            "decisions": self.summary.decisions,
            "action_items": self.summary.action_items,
            "language": self.language,
            "audio_duration_seconds": round(self.duration_seconds, 2),
            "backends": {
                "speech_to_text": self.stt_backend,
                "summarization": self.summarizer_backend,
            },
            "timing": {
                "transcribe_seconds": round(self.transcribe_seconds, 2),
                "summarize_seconds": round(self.summarize_seconds, 3),
                "total_seconds": round(self.total_seconds, 2),
            },
        }


class MeetingPipeline:
    """Orchestrates STT → summarization. Components come from the registry,
    so each stage can be replaced independently."""

    def __init__(self, transcriber=None, summarizer=None) -> None:
        self.transcriber = transcriber or get_transcriber()
        self.summarizer = summarizer or get_summarizer()

    def warmup(self) -> None:
        self.transcriber.warmup()

    def run(self, audio_path: Path) -> PipelineResult:
        t0 = time.perf_counter()
        transcript = self.transcriber.transcribe(audio_path)
        t1 = time.perf_counter()
        summary = self.summarizer.summarize(transcript.text)
        t2 = time.perf_counter()

        return PipelineResult(
            transcript=transcript.text,
            summary=summary,
            language=transcript.language,
            duration_seconds=transcript.duration_seconds,
            stt_backend=getattr(transcript, "backend", self.transcriber.name),
            summarizer_backend=self.summarizer.name,
            transcribe_seconds=t1 - t0,
            summarize_seconds=t2 - t1,
        )
