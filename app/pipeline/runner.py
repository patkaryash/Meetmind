"""Pipeline runner: audio file in → structured meeting summary out."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from app.config import MAX_KEYWORDS
from app.pipeline.keywords import extract_keywords
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
    keywords_seconds: float = 0.0
    summarize_seconds: float = 0.0
    keywords: list[str] = field(default_factory=list)

    @property
    def total_seconds(self) -> float:
        return self.transcribe_seconds + self.keywords_seconds + self.summarize_seconds

    def to_dict(self) -> dict:
        summary_dict = self.summary.to_dict()
        return {
            "transcript": self.transcript,
            "headline": summary_dict["headline"],
            "summary": summary_dict["summary"],
            "key_points": summary_dict["key_points"],
            "decisions": summary_dict["decisions"],
            "action_items": summary_dict["action_items"],
            "topics": summary_dict["topics"],
            "open_questions": summary_dict["open_questions"],
            # Statistical TF-IDF terms — distinct from Gemini topic labels.
            "keywords": list(self.keywords),
            "language": self.language,
            "audio_duration_seconds": round(self.duration_seconds, 2),
            "backends": {
                "speech_to_text": self.stt_backend,
                "summarization": self.summarizer_backend,
            },
            "timing": {
                "transcribe_seconds": round(self.transcribe_seconds, 2),
                "keywords_seconds": round(self.keywords_seconds, 3),
                "summarize_seconds": round(self.summarize_seconds, 3),
                "total_seconds": round(self.total_seconds, 2),
            },
        }


class MeetingPipeline:
    """Orchestrates STT → keywords → summarization. Components come from the
    registry, so each stage can be replaced independently."""

    def __init__(self, transcriber=None, summarizer=None) -> None:
        self.transcriber = transcriber or get_transcriber()
        self.summarizer = summarizer or get_summarizer()

    def warmup(self) -> None:
        self.transcriber.warmup()

    def run(self, audio_path: Path) -> PipelineResult:
        t0 = time.perf_counter()
        transcript = self.transcriber.transcribe(audio_path)
        t1 = time.perf_counter()
        keywords = extract_keywords(transcript.text, MAX_KEYWORDS)
        t2 = time.perf_counter()
        summary = self.summarizer.summarize(transcript.text)
        t3 = time.perf_counter()

        return PipelineResult(
            transcript=transcript.text,
            summary=summary,
            language=transcript.language,
            duration_seconds=transcript.duration_seconds,
            stt_backend=getattr(transcript, "backend", self.transcriber.name),
            summarizer_backend=self.summarizer.name,
            transcribe_seconds=t1 - t0,
            keywords_seconds=t2 - t1,
            summarize_seconds=t3 - t2,
            keywords=keywords,
        )
