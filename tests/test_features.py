"""MeetMind feature tests (stdlib unittest, no extra dependencies).

Covers the one-day upgrade without touching the network, the Whisper
model, or the Gemini API:
- TF-IDF keyword extraction edge cases (F3)
- Gemini output normalization: dedup, evidence grounding, malformed
  items, empty sections, long-transcript truncation (F4)
- Pipeline result schema incl. keywords + 4-stage timing (F3/F5)
- Upload constraints shared by backend and frontend (F5)

Run:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import unittest

from app import config
from app.pipeline.keywords import extract_keywords
from app.pipeline.runner import PipelineResult
from app.pipeline.summarize import gemini as G
from app.pipeline.summarize.base import MeetingSummary

MEETING_TEXT = (
    "The council approved the meeting agenda. Members discussed the Ward 4 "
    "resurfacing project and its cost estimates. The Bell MTS tower proposal "
    "was deferred pending a site visit. Staff will circulate the transit "
    "summit briefing before the April meeting. The consent agenda passed "
    "without objection, and board appointments were confirmed unanimously."
)


class KeywordExtractionTests(unittest.TestCase):
    def test_returns_ranked_terms(self):
        terms = extract_keywords(MEETING_TEXT, max_terms=8)
        self.assertTrue(0 < len(terms) <= 8)
        self.assertIn("agenda", terms)

    def test_empty_and_short_text(self):
        self.assertEqual(extract_keywords("", max_terms=8), [])
        self.assertEqual(extract_keywords("   ", max_terms=8), [])
        self.assertEqual(extract_keywords("Hi. Ok yes.", max_terms=8), [])
        self.assertEqual(extract_keywords(MEETING_TEXT, max_terms=0), [])

    def test_no_junk_or_duplicates(self):
        terms = extract_keywords(MEETING_TEXT, max_terms=12)
        lowered = [t.casefold() for t in terms]
        self.assertEqual(len(lowered), len(set(lowered)))
        for term in lowered:
            words = term.split()
            self.assertTrue(all(len(w) >= 2 for w in words))
            self.assertNotIn(term, {"meeting", "yeah", "just", "thing"})
        # No term merely repeats another ("agenda" vs "meeting agenda").
        for i, a in enumerate(lowered):
            for b in lowered[i + 1:]:
                self.assertFalse(a in b or b in a, f"{a!r} overlaps {b!r}")

    def test_supports_bigrams(self):
        text = (
            "Database integration is blocked on the API documentation. "
            "The database integration team met twice about database integration. "
            "API documentation reviews take time. Please finish API documentation."
        )
        terms = extract_keywords(text, max_terms=6)
        self.assertTrue(any(" " in t for t in terms), terms)

    def test_deterministic(self):
        self.assertEqual(
            extract_keywords(MEETING_TEXT, max_terms=8),
            extract_keywords(MEETING_TEXT, max_terms=8),
        )


class NormalizationTests(unittest.TestCase):
    def test_str_list_dedupes_and_skips_dicts(self):
        out = G._as_str_list(["Alpha", "  alpha ", "", {"x": 1}, ["y"], 42, None])
        self.assertEqual(out, ["Alpha", "42"])

    def test_str_list_non_list(self):
        self.assertEqual(G._as_str_list("nope"), [])
        self.assertEqual(G._as_str_list(None), [])

    def test_decisions_dedupe_and_drop_empty(self):
        items = G._normalize_decisions(
            [
                {"decision": "Adopt agenda", "evidence": "adopt the agenda"},
                {"decision": "adopt AGENDA!", "evidence": "adopt the agenda"},
                {"decision": "  ", "evidence": "nothing"},
                "Adopt agenda",
                42,
            ],
            transcript="We voted to adopt the agenda today.",
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["decision"], "Adopt agenda")

    def test_actions_null_unknown_fields(self):
        (item,) = G._normalize_actions(
            [{"task": "Fix login", "owner": "unknown", "deadline": "",
              "priority": "URGENT", "evidence": "fix login"}],
            transcript="Please fix login soon.",
        )
        self.assertIsNone(item["owner"])
        self.assertIsNone(item["deadline"])
        self.assertEqual(item["priority"], "medium")

    def test_actions_missing_fields(self):
        (item,) = G._normalize_actions(["Do the thing"], transcript="Do the thing now.")
        self.assertIsNone(item["owner"])
        self.assertIsNone(item["deadline"])
        self.assertEqual(item["priority"], "medium")


class EvidenceGroundingTests(unittest.TestCase):
    TRANSCRIPT = "The council voted to adopt the agenda as presented. All in favour."

    def test_verbatim_kept(self):
        self.assertEqual(
            G.verify_evidence("adopt the agenda as presented", self.TRANSCRIPT),
            "adopt the agenda as presented",
        )

    def test_case_and_punctuation_insensitive(self):
        self.assertEqual(
            G.verify_evidence("Adopt the agenda, as presented!", self.TRANSCRIPT),
            "Adopt the agenda, as presented!",
        )

    def test_fabricated_evidence_dropped(self):
        self.assertEqual(
            G.verify_evidence("The council built a rocket to Mars", self.TRANSCRIPT),
            "",
        )

    def test_empty_inputs(self):
        self.assertEqual(G.verify_evidence("", self.TRANSCRIPT), "")
        self.assertEqual(G.verify_evidence("something", ""), "")

    def test_to_summary_grounds_evidence(self):
        summary = G._to_summary(
            {
                "headline": "H",
                "summary": "S",
                "key_points": [],
                "decisions": [
                    {"decision": "Adopt agenda",
                     "evidence": "The council built a rocket to Mars"},
                ],
                "action_items": [],
                "topics": [],
                "open_questions": [],
            },
            self.TRANSCRIPT,
        )
        self.assertEqual(summary.decisions[0]["evidence"], "")


class PromptContractTests(unittest.TestCase):
    def test_empty_transcript_needs_no_api(self):
        summarizer = object.__new__(G.GeminiSummarizer)
        summary = summarizer.summarize("   ")
        self.assertEqual(summary.headline, "No meeting content detected")
        self.assertEqual(summary.key_points, [])

    def test_long_transcript_truncated_head_and_tail(self):
        text = ("word " * 20000).strip() + " UNIQUE_TAIL_MARKER"
        out = G._truncate(text, limit=1000)
        self.assertLess(len(out), len(text))
        self.assertIn("UNIQUE_TAIL_MARKER", out)
        self.assertIn("truncated", out)

    def test_strip_fences(self):
        self.assertEqual(G._strip_fences('```json\n{"a": 1}\n```'), '{"a": 1}')
        self.assertEqual(G._strip_fences('{"a": 1}'), '{"a": 1}')

    def test_schema_keys_stable(self):
        for key in ("headline", "summary", "key_points", "decisions",
                    "action_items", "topics", "open_questions"):
            self.assertIn(key, G.RESPONSE_SCHEMA["required"])


class PipelineSchemaTests(unittest.TestCase):
    def _result(self, **overrides):
        kwargs = {
            "transcript": "hello world. " * 10,
            "summary": MeetingSummary(headline="H", summary="S"),
            "language": "en",
            "duration_seconds": 60.0,
            "stt_backend": "test-stt",
            "summarizer_backend": "test-sum",
            "transcribe_seconds": 1.0,
            "keywords_seconds": 0.05,
            "summarize_seconds": 2.0,
            "keywords": ["agenda", "council"],
        }
        kwargs.update(overrides)
        return PipelineResult(**kwargs)

    def test_to_dict_has_keywords_and_timing(self):
        payload = self._result().to_dict()
        self.assertEqual(payload["keywords"], ["agenda", "council"])
        timing = payload["timing"]
        self.assertAlmostEqual(timing["total_seconds"], 3.05)
        self.assertIn("keywords_seconds", timing)
        # Pre-existing frontend contract keys still present.
        for key in ("transcript", "headline", "summary", "key_points",
                    "decisions", "action_items", "topics", "open_questions",
                    "language", "audio_duration_seconds", "backends", "timing"):
            self.assertIn(key, payload)

    def test_empty_sections_are_valid(self):
        payload = self._result(keywords=[]).to_dict()
        self.assertEqual(payload["keywords"], [])
        self.assertEqual(payload["key_points"], [])


class UploadConstraintTests(unittest.TestCase):
    def test_allowed_extensions(self):
        self.assertEqual(config.ALLOWED_AUDIO_EXTENSIONS, {".mp3", ".wav", ".m4a"})

    def test_upload_limits_sane(self):
        self.assertGreater(config.MAX_UPLOAD_BYTES, 0)
        self.assertGreater(config.MAX_KEYWORDS, 0)


if __name__ == "__main__":
    unittest.main()
