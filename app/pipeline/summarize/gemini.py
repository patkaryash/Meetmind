"""Gemini-backed summarization stage (backend only).

Pipeline position (unchanged):

    Meeting Audio → Existing STT → Full Transcript → GeminiSummarizer
    → structured MeetingSummary → frontend report.

The API key is read from the `GEMINI_API_KEY` environment variable and is
never exposed to the frontend.
"""
from __future__ import annotations

import difflib
import json
import re
import string

from app.config import (
    GEMINI_API_KEY,
    GEMINI_MAX_OUTPUT_TOKENS,
    GEMINI_MAX_TRANSCRIPT_CHARS,
    GEMINI_MODEL,
)
from app.pipeline.summarize.base import MeetingSummary, Summarizer


class GeminiAnalysisError(RuntimeError):
    """Raised when Gemini analysis fails (auth, quota, bad response, ...)."""


SYSTEM_PROMPT = """You are MeetMind, a meeting-intelligence extractor for a university NLP mini-project.
Analyze the meeting transcript and return ONLY valid JSON matching the requested schema. No markdown, no commentary.

STRICT RULES:
1. Base EVERY statement strictly on the transcript. Never invent people, decisions, deadlines, tasks, or facts.
2. Never assume a task owner unless the transcript names them. Use null when owner or deadline is not mentioned.
3. Distinguish carefully:
   - KEY POINT: a topic that was discussed, e.g. "The team discussed PostgreSQL."
   - DECISION: the group clearly agreed/decided, e.g. "The team agreed to use PostgreSQL as the backend database."
   - ACTION ITEM: a concrete task assigned to someone, e.g. "Yash will integrate PostgreSQL."
   Do NOT classify all three as the same thing.
4. Do NOT create fake decisions. Do NOT convert a discussion/opinion into a decision unless the transcript clearly indicates agreement (words like decided, agreed, confirmed, approved, we will go with).
5. Keep the summary concise (3-5 sentences): what the meeting was about, main outcomes, next steps.
6. Extract actionable tasks, not vague statements. Preserve technical terms, names, dates, and numbers verbatim.
7. Every decision and action item MUST include a short verbatim "evidence" quote copied directly from the transcript.
8. Priority must be one of: "high", "medium", "low". Use "high" only for urgent/blocking or explicitly time-critical tasks, "low" for nice-to-have, otherwise "medium".
9. Topics: 3-8 short noun-phrase tags (e.g. "Backend", "Database", "Authentication").
10. Open questions: unresolved items only. Empty list if everything was resolved.
11. If the transcript is empty or has no meaningful content, return empty lists and a headline like "No meeting content detected".
"""

RESPONSE_SCHEMA: dict = {
    "type": "OBJECT",
    "properties": {
        "headline": {"type": "STRING"},
        "summary": {"type": "STRING"},
        "key_points": {"type": "ARRAY", "items": {"type": "STRING"}},
        "decisions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "decision": {"type": "STRING"},
                    "reason": {"type": "STRING"},
                    "evidence": {"type": "STRING"},
                },
                "required": ["decision", "evidence"],
            },
        },
        "action_items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "task": {"type": "STRING"},
                    "owner": {"type": "STRING"},
                    "deadline": {"type": "STRING"},
                    "priority": {"type": "STRING", "enum": ["high", "medium", "low"]},
                    "evidence": {"type": "STRING"},
                },
                "required": ["task", "priority", "evidence"],
            },
        },
        "topics": {"type": "ARRAY", "items": {"type": "STRING"}},
        "open_questions": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": [
        "headline",
        "summary",
        "key_points",
        "decisions",
        "action_items",
        "topics",
        "open_questions",
    ],
}


def _truncate(transcript: str, limit: int = GEMINI_MAX_TRANSCRIPT_CHARS) -> str:
    text = transcript.strip()
    if len(text) <= limit:
        return text
    # Keep head + tail so decisions/action items at the end are not lost.
    head = int(limit * 0.7)
    tail = limit - head
    return (
        text[:head].rsplit(" ", 1)[0]
        + f"\n\n[... truncated {len(text) - limit} chars ...]\n\n"
        + text[-tail:]
    )


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    m = re.match(r"^```(?:json)?\s*(.*)\s*```$", raw, re.S | re.I)
    return m.group(1).strip() if m else raw


def _as_str_list(value, limit: int = 20) -> list[str]:
    """Coerce to a de-duplicated list of non-empty strings (order kept).

    Non-string scalars are stringified; dicts/lists are skipped instead of
    being dumped as "{...}" into the UI. Empty lists stay empty — a meeting
    can legitimately have no items in a section.
    """
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if item is None or isinstance(item, bool):
            continue
        if isinstance(item, dict | list):
            continue
        text = str(item).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _canon(text: str) -> str:
    """Canonical form for verbatim comparison: lowercase, no punctuation,
    single-spaced. Lets "Hello, world!" match "hello world"."""
    lowered = text.casefold()
    no_punct = lowered.translate(str.maketrans(string.punctuation, " " * len(string.punctuation)))
    return re.sub(r"\s+", " ", no_punct).strip()


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def verify_evidence(evidence: str, transcript: str) -> str:
    """Ground an evidence quote in the transcript.

    Returns the evidence unchanged when it appears verbatim (modulo case /
    punctuation), the closest actually-verbatim transcript sentence when it
    is a close paraphrase, or "" when nothing in the transcript supports it
    — so the UI never presents false provenance.
    """
    quote = (evidence or "").strip()
    if not quote or not (transcript or "").strip():
        return ""
    canon_quote = _canon(quote)
    if not canon_quote:
        return ""
    canon_transcript = _canon(transcript)
    if canon_quote in canon_transcript:
        return quote
    # Close paraphrase? Snap to the truly verbatim sentence.
    best, best_ratio = "", 0.0
    for sentence in _split_sentences(transcript):
        if len(_canon(sentence)) < max(12, len(canon_quote) // 3):
            continue
        ratio = difflib.SequenceMatcher(None, canon_quote, _canon(sentence)).ratio()
        if ratio > best_ratio:
            best, best_ratio = sentence, ratio
    if best_ratio >= 0.8:
        return best
    return ""


def _dedupe_dicts(items: list[dict], key: str) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        norm = _canon(str(item.get(key, "")))
        if norm in seen:
            continue
        seen.add(norm)
        out.append(item)
    return out


def _normalize_decisions(value, transcript: str = "") -> list[dict]:
    out: list[dict] = []
    if not isinstance(value, list):
        return out
    for item in value[:20]:
        if isinstance(item, str):
            item = {"decision": item, "reason": "", "evidence": item}
        if not isinstance(item, dict):
            continue
        decision = str(item.get("decision", "")).strip()
        if not decision:
            continue
        out.append(
            {
                "decision": decision,
                "reason": str(item.get("reason", "") or "").strip(),
                "evidence": verify_evidence(str(item.get("evidence", "") or ""), transcript),
            }
        )
    return _dedupe_dicts(out, "decision")


def _normalize_actions(value, transcript: str = "") -> list[dict]:
    out: list[dict] = []
    if not isinstance(value, list):
        return out
    for item in value[:20]:
        if isinstance(item, str):
            item = {"task": item, "evidence": item}
        if not isinstance(item, dict):
            continue
        task = str(item.get("task", "")).strip()
        if not task:
            continue
        owner = item.get("owner")
        owner = str(owner).strip() if owner not in (None, "") else None
        if owner in ("", "null", "None", "unknown"):
            owner = None
        deadline = item.get("deadline")
        deadline = str(deadline).strip() if deadline not in (None, "") else None
        if deadline in ("", "null", "None"):
            deadline = None
        priority = str(item.get("priority", "medium")).strip().lower()
        if priority not in ("high", "medium", "low"):
            priority = "medium"
        out.append(
            {
                "task": task,
                "owner": owner,
                "deadline": deadline,
                "priority": priority,
                "evidence": verify_evidence(str(item.get("evidence", "") or ""), transcript),
            }
        )
    return _dedupe_dicts(out, "task")


def _to_summary(data: dict, transcript: str = "") -> MeetingSummary:
    return MeetingSummary(
        headline=str(data.get("headline", "") or "Meeting analysis")[:160],
        summary=str(data.get("summary", "") or ""),
        key_points=_as_str_list(data.get("key_points")),
        decisions=_normalize_decisions(data.get("decisions"), transcript),
        action_items=_normalize_actions(data.get("action_items"), transcript),
        topics=_as_str_list(data.get("topics"), 12),
        open_questions=_as_str_list(data.get("open_questions")),
    )


class GeminiSummarizer(Summarizer):
    """LLM summarizer: transcript → Gemini structured JSON → MeetingSummary."""

    def __init__(self, api_key: str = GEMINI_API_KEY, model: str = GEMINI_MODEL) -> None:
        if not api_key:
            raise GeminiAnalysisError(
                "GEMINI_API_KEY is not set. Add it to the .env file "
                "(see .env.example) and restart the server."
            )
        self.api_key = api_key
        self.model = model or "gemini-3.5-flash-lite"
        self.name = f"gemini:{self.model}"
        self._client = None

    def _client_or_load(self):
        if self._client is None:
            try:
                from google import genai
            except ImportError as exc:
                raise GeminiAnalysisError(
                    "google-genai package is not installed. "
                    "Run: pip install -r requirements.txt"
                ) from exc
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def summarize(self, transcript_text: str) -> MeetingSummary:
        text = (transcript_text or "").strip()
        if not text:
            return MeetingSummary(
                headline="No meeting content detected",
                summary="No speech was detected in the provided audio.",
            )
        prompt_transcript = _truncate(text)
        prompt = (
            SYSTEM_PROMPT
            + "\n\nMEETING TRANSCRIPT:\n\"\"\"\n"
            + prompt_transcript
            + '\n"""\n\nReturn the JSON object now.'
        )
        try:
            client = self._client_or_load()
            kwargs: dict = {
                "model": self.model,
                "contents": prompt,
                "config": {
                    "response_mime_type": "application/json",
                    "response_json_schema": RESPONSE_SCHEMA,
                    "temperature": 0.2,
                    "max_output_tokens": GEMINI_MAX_OUTPUT_TOKENS,
                },
            }
            try:
                response = client.models.generate_content(**kwargs)
            except TypeError:
                # Older SDK without response_json_schema support.
                kwargs["config"] = {
                    "response_mime_type": "application/json",
                    "temperature": 0.2,
                    "max_output_tokens": GEMINI_MAX_OUTPUT_TOKENS,
                }
                response = client.models.generate_content(**kwargs)
            raw = (getattr(response, "text", "") or "").strip()
        except GeminiAnalysisError:
            raise
        except Exception as exc:
            raise GeminiAnalysisError(
                f"Gemini API request failed ({type(exc).__name__}): {exc}. "
                "Check GEMINI_API_KEY / GEMINI_MODEL and network access."
            ) from exc

        if not raw:
            raise GeminiAnalysisError(
                "Gemini returned an empty response. Please retry the analysis."
            )
        try:
            data = json.loads(_strip_fences(raw))
        except json.JSONDecodeError as exc:
            raise GeminiAnalysisError(
                "Gemini returned invalid JSON. Please retry the analysis."
            ) from exc
        if not isinstance(data, dict):
            raise GeminiAnalysisError(
                "Gemini returned an unexpected format. Please retry the analysis."
            )
        summary = _to_summary(data, text)
        if not summary.summary and not summary.key_points:
            raise GeminiAnalysisError(
                "Gemini returned an empty analysis. Please retry with a longer recording."
            )
        return summary
