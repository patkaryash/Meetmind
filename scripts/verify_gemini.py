"""Verify Gemini backend returns valid structured JSON (no audio needed).

Usage:
  set GEMINI_API_KEY=...   (or put it in .env)
  python scripts/verify_gemini.py [path/to/transcript.txt]

Reads samples/meeting_script.txt by default, sends it to GeminiSummarizer,
and prints the structured JSON. Fails loudly on invalid output.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.pipeline.summarize.gemini import GeminiSummarizer  # noqa: E402


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        PROJECT_ROOT / "samples" / "meeting_script.txt"
    )
    transcript = src.read_text(encoding="utf-8").strip()
    print(f"Transcript: {src} ({len(transcript)} chars)")
    summary = GeminiSummarizer().summarize(transcript)
    data = summary.to_dict()
    # Minimal schema assertion before printing.
    assert isinstance(data["headline"], str) and data["summary"], "empty summary"
    assert isinstance(data["key_points"], list), "key_points must be a list"
    assert isinstance(data["decisions"], list), "decisions must be a list"
    assert isinstance(data["action_items"], list), "action_items must be a list"
    for d in data["decisions"]:
        assert d.get("decision") and d.get("evidence"), f"bad decision: {d!r}"
    for a in data["action_items"]:
        assert a.get("task") and a.get("evidence"), f"bad action: {a!r}"
        assert a.get("priority") in ("high", "medium", "low"), f"bad priority: {a!r}"
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print("\nOK: valid structured JSON.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
