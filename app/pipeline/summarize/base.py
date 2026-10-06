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
    """Structured meeting summary shown in the UI."""

    summary: str = ""
    key_points: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)


class Summarizer(ABC):
    """Interface every summarization backend must implement."""

    name: str = "base"

    @abstractmethod
    def summarize(self, transcript_text: str) -> MeetingSummary:
        """Turn raw transcript text into a structured meeting summary."""
