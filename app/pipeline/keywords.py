"""TF-IDF keyword extraction over the meeting transcript.

Statistical only: ranks terms by TF-IDF weight within the single transcript
document (each sentence is treated as a sub-document so IDF is meaningful).
It does NOT understand semantic meaning — it surfaces statistically
prominent words and two-word phrases.

Kept fully separate from the Gemini analysis service: no API key, no
network, deterministic output. Returns [] when scikit-learn is missing or
the text is too short to rank.
"""
from __future__ import annotations

import re

# Extra domain-noise stop words beyond sklearn's English list: meeting
# filler that would otherwise top every transcript.
_EXTRA_STOP_WORDS = frozenset(
    {
        "yeah", "okay", "ok", "uh", "um", "ah", "hmm", "like", "just",
        "really", "actually", "basically", "anyway", "well", "right",
        "going", "gonna", "wanna", "got", "get", "getting", "let", "lets",
        "thing", "things", "stuff", "lot", "bit", "maybe", "probably",
        "think", "know", "mean", "said", "say", "says", "tell", "told",
        "ask", "asked", "meeting", "meetings", "discuss", "discussed",
        "talk", "talking", "today", "tomorrow", "yesterday", "week",
        "month", "year", "time", "times", "people", "person", "everyone",
        "somebody", "someone", "something", "nothing", "everything",
        "kind", "sort", "way", "make", "made", "take", "takes", "took",
        "come", "goes", "going", "back", "forward", "first", "last",
        "next", "previous", "new", "old", "good", "great", "bad", "best",
        "better", "sure", "yes", "yeah", "please", "thanks", "thank",
    }
)

_TOKEN_RE = re.compile(r"[a-z][a-z0-9\-]*")


def _sentences(text: str) -> list[str]:
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    return [p for p in parts if len(_TOKEN_RE.findall(p.casefold())) >= 3]


def _is_junk(term: str) -> bool:
    words = term.split()
    if any(len(w) < 2 for w in words):
        return True
    if any(w in _EXTRA_STOP_WORDS for w in words):
        return True
    # Drop phrases that merely repeat one stem ("report reports").
    stems = {w[:5] for w in words}
    return len(stems) < len(words)


def extract_keywords(transcript: str, max_terms: int = 12) -> list[str]:
    """Return up to `max_terms` representative terms, highest TF-IDF first."""
    text = (transcript or "").strip()
    if not text or max_terms <= 0:
        return []
    sentences = _sentences(text)
    if len(sentences) < 2:
        return []
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError:
        return []

    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words="english",
        ngram_range=(1, 2),
        token_pattern=r"[a-z][a-z0-9\-]+",
        max_features=200,
    )
    try:
        matrix = vectorizer.fit_transform(sentences)
    except ValueError:
        # Empty vocabulary (e.g. transcript is only stop words).
        return []

    import numpy as np

    scores = np.asarray(matrix.sum(axis=0)).ravel()
    terms = vectorizer.get_feature_names_out()
    ranked = sorted(zip(scores, terms), key=lambda pair: -pair[0])

    out: list[str] = []
    seen: set[str] = set()
    for _, term in ranked:
        term = str(term).strip()
        if not term or _is_junk(term):
            continue
        key = term.casefold()
        if key in seen:
            continue
        if " " not in term and any(key in kept for kept in seen if " " in kept):
            # Unigram adds nothing next to an accepted phrase ("estimates"
            # beside "cost estimates") — prefer the phrase.
            continue
        seen.add(key)
        out.append(term)
        if " " in term:
            # A new phrase subsumes earlier lone words: drop them so the
            # list never shows both "estimates" and "cost estimates".
            covered = {w for w in key.split()}
            out = [t for t in out if " " in t or t.casefold() not in covered]
            seen = {s for s in seen if " " in s or s not in covered}
        if len(out) >= max_terms:
            break
    return out
