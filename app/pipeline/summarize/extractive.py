"""Lightweight extractive summarization pipeline (pure Python, no GPU).

Pipeline stages
---------------
1. Sentence segmentation.
2. Term-frequency scoring to pick an overview summary and key points.
3. Pattern-based extraction of decisions and action items.

Everything is deterministic and dependency-free, which keeps the demo
self-contained. Replace this class with a transformer/LLM implementation
behind the same `Summarizer` interface to upgrade the output.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from app.config import MAX_KEY_POINTS, MAX_LIST_ITEMS, SUMMARY_SENTENCES
from app.pipeline.summarize.base import MeetingSummary, Summarizer

# --------------------------------------------------------------------------- #
# Text utilities
# --------------------------------------------------------------------------- #

STOPWORDS = frozenset(
    """a about above after again against all am an and any are aren't as at be
    because been before being below between both but by can't cannot could
    couldn't did didn't do does doesn't doing don't down during each few for
    from further had hadn't has hasn't have haven't having he he'd he'll he's
    her here here's hers herself him himself his how how's i i'd i'll i'm i've
    if in into is isn't it it's its itself let's me more most mustn't my myself
    no nor not of off on once only or other ought our ours ourselves out over
    own same shan't she she'd she'll she's should shouldn't so some such than
    that that's the their theirs them themselves then there there's these they
    they'd they'll they're they've this those through to too under until up
    very was wasn't we we'd we'll we're we've were weren't what what's when
    when's where where's which while who who's whom why why's with won't would
    wouldn't you you'd you'll you're you've your yours yourself yourselves
    will just get got going make made really yeah okay ok um uh like also
    right well know think want going good great thing things kind
    """.split()
)

_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "st", "vs", "etc", "e.g", "i.e",
    "inc", "ltd", "jr", "sr", "fig", "approx",
}


def split_sentences(text: str) -> list[str]:
    """Rule-based sentence segmentation good enough for meeting transcripts."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    # Split on sentence enders followed by whitespace + capital/digit/quote.
    rough = re.split(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])", text)
    sentences: list[str] = []
    for chunk in rough:
        chunk = chunk.strip()
        if not chunk:
            continue
        # Re-join accidental splits like "Mr. Smith".
        first_word = chunk.split(" ")[0].rstrip(".").lower()
        if sentences and first_word in _ABBREVIATIONS:
            sentences[-1] = sentences[-1] + " " + chunk
        else:
            sentences.append(chunk)
    # Merge very short fragments (e.g. "Thanks.") into the previous sentence.
    merged: list[str] = []
    for s in sentences:
        if merged and len(s.split()) <= 2 and not s.endswith(("?", "!")):
            merged[-1] = merged[-1] + " " + s
        else:
            merged.append(s)
    return merged


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _content_tokens(sentence: str) -> list[str]:
    return [
        t for t in tokenize(sentence)
        if t not in STOPWORDS and len(t) > 2 and not t.isdigit()
    ]


def _clean_bullet(sentence: str) -> str:
    """Normalize a sentence for use as a bullet point."""
    s = re.sub(r"^[\"'\s]+|[\"'\s]+$", "", sentence)
    s = re.sub(r"^(?:and|so|then|but|also|plus|okay|ok|alright|well|now)\s+", "",
               s, flags=re.I)
    s = re.sub(r"^(?:[A-Z][a-z]+\s*:\s*)+", "", s)  # strip speaker labels
    s = s.strip()
    if not s:
        return ""
    s = s[0].upper() + s[1:]
    return s.rstrip(".").strip()


def _jaccard(a: str, b: str) -> float:
    sa, sb = set(tokenize(a)), set(tokenize(b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _headline_for(summary: str) -> str:
    """Derive a short headline from the summary (fallback backend only)."""
    first = split_sentences(summary)
    head = (first[0] if first else summary).strip()
    if len(head) > 90:
        head = head[:87].rsplit(" ", 1)[0] + "..."
    return head or "Meeting summary"


# --------------------------------------------------------------------------- #
# Pattern rules for decisions / action items
# --------------------------------------------------------------------------- #

DECISION_PATTERNS = re.compile(
    r"(?i)\b("
    r"(?:we|i|they|the team|management)\s+(?:have\s+)?(?:decided|agreed|confirmed|resolved)"
    r"|decided\s+to|agreed\s+(?:to|on)|approved|sign[- ]?off|signed off"
    r"|final\s+(?:decision|answer|call)|we(?:'ll| will)\s+(?:go\s+with|stick\s+with|use|move|delay|postpone|ship)"
    r"|lets?\s+(?:go\s+with|proceed|ship|move\s+ahead)"
    r"|it\s+(?:was\s+)?(?:agreed|decided|confirmed)"
    r"|conclusion\s+is|we\s+are\s+(?:going\s+with|delaying|postponing|shipping)"
    r"|postponed|delayed\s+until|will\s+be\s+(?:delayed|postponed|moved)"
    r")\b"
)

ACTION_PATTERNS = re.compile(
    r"(?i)\b("
    r"action\s+items?|todo|to[- ]do|follow[- ]?up"
    r"|will\s+(?:fix|prepare|send|share|schedule|draft|review|update|handle|own|lead|write|contact|book|complete|deliver|take|follow|coordinate|organize|check|start|finish|implement|design|build|test|publish|announce|assign|upload|submit|confirm|escalate|procure|migrate)"
    r"|needs?\s+to|should\s+(?:fix|prepare|send|share|schedule|draft|review|update|handle|write|contact|book|start|finish)"
    r"|responsible\s+for|in\s+charge\s+of|assigned\s+to"
    r"|please\s+(?:remember\s+to|upload|submit|share|send|provide)"
    r"|by\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|next\s+week|end\s+of\s+(?:day|day|week)|eod|eow|cob|close\s+of\s+business)"
    r"|please\s+(?:fix|prepare|send|share|schedule|draft|review|update|write|contact|book)"
    r")\b"
)

_NAME_PREFIX = re.compile(r"^\s*([A-Z][a-z]{1,15})\s+(?:will|to|needs to|should|is going to|has to)\b")

# Pleasantries / meeting bookkeeping that should never rank as a key point.
_META_RE = re.compile(
    r"(?i)^(thanks|thank you|hello|hi\b|okay\b|alright\b|so\b|anyway\b)|"
    r"\b(thanks everyone|that is all|appreciate (?:it|that)|welcome back)\b"
)


# --------------------------------------------------------------------------- #
# Summarizer
# --------------------------------------------------------------------------- #

class ExtractiveSummarizer(Summarizer):
    name = "extractive"

    def __init__(
        self,
        summary_sentences: int = SUMMARY_SENTENCES,
        max_key_points: int = MAX_KEY_POINTS,
        max_list_items: int = MAX_LIST_ITEMS,
    ) -> None:
        self.summary_sentences = summary_sentences
        self.max_key_points = max_key_points
        self.max_list_items = max_list_items

    # -- scoring ------------------------------------------------------------ #

    def _score(self, sentences: list[str]) -> list[float]:
        freq: Counter[str] = Counter()
        for s in sentences:
            freq.update(_content_tokens(s))

        scores: list[float] = []
        n = len(sentences)
        for i, s in enumerate(sentences):
            tokens = _content_tokens(s)
            if not tokens:
                scores.append(0.0)
                continue
            raw = sum(1.0 + math.log(freq[t]) for t in tokens)
            # Normalize by length so verbose sentences don't dominate.
            value = raw / math.sqrt(len(tokens))
            # Meetings usually state context first, outcomes second.
            position_boost = 1.0 + max(0.0, 0.3 - 0.05 * i)
            value *= position_boost
            # Penalize very short utterances ("Thanks." "Yep.")
            if len(tokens) < 3:
                value *= 0.4
            # Penalize meeting pleasantries/bookkeeping.
            if _META_RE.search(s):
                value *= 0.35
            scores.append(value)
        _ = n
        return scores

    def _pick(self, scored: list[tuple[str, float]], count: int,
              avoid: list[str]) -> list[str]:
        """Pick top-scoring sentences with lexical diversity."""
        picked: list[str] = []
        for sentence, _ in sorted(scored, key=lambda x: -x[1]):
            if len(picked) >= count:
                break
            if any(_jaccard(sentence, p) > 0.45 for p in picked + avoid):
                continue
            bullet = _clean_bullet(sentence)
            if bullet:
                picked.append(bullet)
        return picked

    # -- main --------------------------------------------------------------- #

    def summarize(self, transcript_text: str) -> MeetingSummary:
        text = transcript_text.strip()
        if not text:
            return MeetingSummary(
                headline="No meeting content detected",
                summary="No speech was detected in the provided audio.",
            )

        sentences = split_sentences(text)
        if not sentences:
            return MeetingSummary(headline="Meeting summary", summary=text)

        # Very short transcripts: everything is the summary.
        if len(sentences) <= self.summary_sentences:
            joined = " ".join(sentences)
            return MeetingSummary(
                headline=_headline_for(joined),
                summary=joined,
            )

        scores = self._score(sentences)
        ranked = list(zip(sentences, scores))

        # 1. Overview summary.
        top = sorted(ranked, key=lambda x: -x[1])[: self.summary_sentences]
        summary_sents = sorted(top, key=lambda x: sentences.index(x[0]))
        summary = " ".join(s for s, _ in summary_sents)
        summary_set = {s for s, _ in summary_sents}

        # 2. Decisions (pattern extraction).
        decision_texts: list[str] = []
        for s in sentences:
            if DECISION_PATTERNS.search(s):
                bullet = _clean_bullet(s)
                if bullet and not any(_jaccard(bullet, d) > 0.5 for d in decision_texts):
                    decision_texts.append(bullet)
            if len(decision_texts) >= self.max_list_items:
                break
        decisions = [
            {"decision": d, "reason": "", "evidence": d} for d in decision_texts
        ]

        # 3. Action items (pattern extraction).
        action_texts: list[str] = []
        owners: list[str | None] = []
        for s in sentences:
            if ACTION_PATTERNS.search(s):
                bullet = _clean_bullet(s)
                if bullet and not any(_jaccard(bullet, a) > 0.5 for a in action_texts):
                    # "Sarah will fix the bugs" -> owner Sarah, task fix...
                    m = _NAME_PREFIX.match(s)
                    owner: str | None = m.group(1) if m else None
                    if m and not bullet.startswith(m.group(1) + ":"):
                        rest_of_bullet = _clean_bullet(s[m.end(1):])
                        if rest_of_bullet:
                            rest_of_bullet = (
                                rest_of_bullet[0].lower() + rest_of_bullet[1:]
                            )
                        bullet = f"{m.group(1)}: {rest_of_bullet}"
                    action_texts.append(bullet)
                    owners.append(owner)
            if len(action_texts) >= self.max_list_items:
                break
        action_items = [
            {
                "task": t.split(": ", 1)[1] if ": " in t else t,
                "owner": o,
                "deadline": None,
                "priority": "medium",
                "evidence": t,
            }
            for t, o in zip(action_texts, owners)
        ]

        # 4. Key points: next-best diverse sentences, excluding anything
        #    already surfaced above so each section adds new information,
        #    and skipping pleasantries outright.
        used = set(summary_set)
        rest = [
            pair for pair in ranked
            if pair[0] not in used and not _META_RE.search(pair[0])
        ]
        key_points = self._pick(
            rest,
            self.max_key_points,
            avoid=[*[s for s, _ in summary_sents], *decision_texts, *action_texts],
        )

        return MeetingSummary(
            headline=_headline_for(summary),
            summary=summary,
            key_points=key_points,
            decisions=decisions,
            action_items=action_items,
            topics=[],
            open_questions=[],
        )
