"""Gemini-backed summarization stage (backend only).

Pipeline position (unchanged):

    Meeting Audio → Existing STT → Full Transcript → GeminiSummarizer
    → structured MeetingSummary → frontend report.

The API key is read from the `GEMINI_API_KEY` environment variable and is
never exposed to the frontend.
"""
from __future__ import annotations

import json
import re

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


def _as_str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()][:20]


def _normalize_decisions(value) -> list[dict]:
    out: list[dict] = []
    if not isinstance(value, list):
        return out
    for item in value[:20]:
        if isinstance(item, str):
            item = {"decision": item, "reason": "", "evidence": item}
        if not isinstance(item, dict):
            continue
        decision = str(item.get("decision", "")).strip()
        evidence = str(item.get("evidence", "")).strip()
        if not decision:
            continue
        out.append(
            {
                "decision": decision,
                "reason": str(item.get("reason", "") or "").strip(),
                "evidence": evidence or decision,
            }
        )
    return out


def _normalize_actions(value) -> list[dict]:
    out: list[dict] = []
    if not isinstance(value, list):
        return out
    for item in value[:20]:
        if isinstance(item, str):
            item = {"task": item, "evidence": item}
        if not isinstance(item, dict):
            continue
        task = str(item.get("task", "")).strip()
        evidence = str(item.get("evidence", "") or task).strip()
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
                "evidence": evidence or task,
            }
        )
    return out


def _to_summary(data: dict) -> MeetingSummary:
    return MeetingSummary(
        headline=str(data.get("headline", "") or "Meeting analysis")[:160],
        summary=str(data.get("summary", "") or ""),
        key_points=_as_str_list(data.get("key_points")),
        decisions=_normalize_decisions(data.get("decisions")),
        action_items=_normalize_actions(data.get("action_items")),
        topics=_as_str_list(data.get("topics"))[:12],
        open_questions=_as_str_list(data.get("open_questions"))[:20],
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
        summary = _to_summary(data)
        if not summary.summary and not summary.key_points:
            raise GeminiAnalysisError(
                "Gemini returned an empty analysis. Please retry with a longer recording."
            )
        return summary
