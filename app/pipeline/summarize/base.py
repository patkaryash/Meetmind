"""Summarization component interface.

Swap implementations (extractive, transformer-based, LLM-backed, ...) by
providing another `Summarizer` subclass and registering it in
`app/pipeline/registry.py`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class MeetingSummary:
    """Structured meeting intelligence shown in the UI.

    Decisions and action items always carry a verbatim `evidence` quote so
    the UI can prove every claim comes from the transcript.
    """

    headline: str = ""
    summary: str = ""
    key_points: list[str] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    action_items: list[dict] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "headline": self.headline,
            "summary": self.summary,
            "key_points": list(self.key_points),
            "decisions": [dict(d) for d in self.decisions],
            "action_items": [dict(a) for a in self.action_items],
            "topics": list(self.topics),
            "open_questions": list(self.open_questions),
        }


class Summarizer(ABC):
    """Interface every summarization backend must implement."""

    name: str = "base"

    @abstractmethod
    def summarize(self, transcript_text: str) -> MeetingSummary:
        """Turn raw transcript text into a structured meeting summary."""
