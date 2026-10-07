# MeetMind

**AI-Based Meeting Transcript Summarization System**

MeetMind turns a meeting recording into a structured summary in three steps:

> Upload audio → Analyze Meeting → Display structured summary

Upload an MP3/WAV/M4A recording and MeetMind:

1. **Transcribes** the audio locally with the open-source
   [faster-whisper](https://github.com/SYSTRAN/faster-whisper) speech-to-text model.
2. **Analyzes** the transcript with Gemini (structured JSON: headline,
   summary, key points, decisions + evidence, action items with
   owner/deadline/priority + evidence, topics, open questions).
   Without `GEMINI_API_KEY` it falls back to the local extractive NLP
   pipeline so transcription can still be tested offline.
3. **Displays** a dashboard with:
   - **Executive Summary** — concise overview + headline
   - **Key Points** — most informative, diverse statements
   - **Decisions** — agreed items with reason + verbatim evidence
   - **Action Items** — task, owner, deadline, priority + evidence
   - **Topics** — compact chips
   - **Open Questions** — unresolved items
   - Full transcript (collapsible), language, audio length and timing

No authentication, no database — audio is processed in memory
and deleted after analysis. Only the transcript text is sent to Gemini;
the API key stays in `.env` on the backend and is never exposed to the frontend.

## Setup on your laptop (Windows, macOS, Linux)

**Prerequisites**

- [Python 3.10–3.12](https://www.python.org/downloads/) (tested on 3.11)
- ~200 MB free disk space (packages + Whisper model)
- Internet access **once**, to download the Whisper model on first run
- No GPU and no ffmpeg needed — audio decoding is built in

**Steps**

```bash
# 1. Clone the repo
git clone https://github.com/patkaryash/Meetmind.git
cd Meetmind

# 2. Create and activate a virtual environment
python -m venv .venv
#   Windows (PowerShell):  .venv\Scripts\Activate.ps1
#   Windows (Git Bash):    source .venv/Scripts/activate
#   macOS / Linux:         source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure Gemini (backend only) and start the app
#   Copy .env.example to .env and set GEMINI_API_KEY (+ optional GEMINI_MODEL)
python -m uvicorn app.main:app --port 8000
```

Then open <http://127.0.0.1:8000>, drop in a recording (MP3/WAV/M4A, ≤100 MB)
and press **Analyze Meeting**. A sample meeting audio is included in
`samples/` if you want to try it right away.

> The first analysis downloads the `base.en` Whisper model (~150 MB) and is
> slower; the model is then cached and reused. A ~90-second meeting takes
> roughly 5–20 s to transcribe on a modern laptop CPU.

### Try the sample

A generated sample meeting is included:

```bash
# regenerate it (Windows TTS, no network needed)
powershell -NoProfile -ExecutionPolicy Bypass -File samples/generate_sample.ps1

# verify the whole pipeline without the UI
python scripts/run_pipeline_test.py
```

## Troubleshooting

- **`python` not found / wrong version** — try `python3`, or install Python 3.11.
- **Port 8000 already in use** — start on another port:
  `python -m uvicorn app.main:app --port 8001`.
- **PowerShell refuses venv activation** ("running scripts is disabled") — run
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use Git Bash.
- **Very slow first analysis** — that's the one-time Whisper model download;
  subsequent runs reuse the cache.
- **"Unsupported file type"** — only `.mp3`, `.wav` and `.m4a` are accepted;
  convert other formats first.
- **Upload rejected as too large** — the default limit is 100 MB; raise it with
  `MEETMIND_MAX_UPLOAD_MB=200` (see configuration table below).

## Project structure

```
app/
├── main.py                 # FastAPI app: /api/analyze, /api/health, static UI
├── config.py               # env-driven settings (incl. GEMINI_API_KEY/MODEL)
├── static/                 # dashboard (plain HTML/CSS/JS, no build step)
└── pipeline/
    ├── registry.py         # ← SWAP COMPONENTS HERE (factories)
    ├── runner.py           # MeetingPipeline: STT → summarization orchestration
    ├── stt/                # speech-to-text component
    │   ├── base.py         #   Transcriber interface
    │   └── whisper.py      #   faster-whisper implementation
    └── summarize/          # summarization component
        ├── base.py         #   Summarizer interface + MeetingSummary schema
        ├── gemini.py       #   Gemini structured-JSON implementation
        └── extractive.py   #   pure-Python fallback (no key / offline)
samples/                    # sample meeting audio + TTS generator
scripts/run_pipeline_test.py
scripts/verify_gemini.py     # transcript → Gemini JSON check (needs .env key)
```

## Swapping components

Both stages are pluggable via simple interfaces; the rest of the app never
touches a concrete implementation:

- **Speech-to-text** — subclass `Transcriber` (`app/pipeline/stt/base.py`),
  implement `transcribe(audio_path) -> Transcript`, and return your class from
  `get_transcriber()` in `app/pipeline/registry.py`.
- **Summarization** — subclass `Summarizer`
  (`app/pipeline/summarize/base.py`), implement
  `summarize(transcript_text) -> MeetingSummary` (e.g. with a transformer or
  LLM backend), and return it from `get_summarizer()`.

## Configuration (environment variables)

| Variable | Default | Purpose |
| --- | --- | --- |
| `MEETMIND_WHISPER_MODEL` | `base.en` | Whisper model size (`tiny.en` ≈ 2–3× faster, slightly less accurate) |
| `MEETMIND_WHISPER_BEAM_SIZE` | `1` | Decoding beams: `1` = fast greedy, `5` = slower but more accurate |
| `MEETMIND_WHISPER_DEVICE` | `cpu` | `cpu` or `cuda` |
| `MEETMIND_WHISPER_COMPUTE_TYPE` | `int8` | faster-whisper compute type |
| `MEETMIND_MAX_UPLOAD_MB` | `100` | Upload size limit (MB) |
| `MEETMIND_SUMMARY_SENTENCES` | `3` | Sentences in the overview summary |
| `MEETMIND_MAX_KEY_POINTS` | `6` | Max key-point bullets |
| `MEETMIND_MAX_LIST_ITEMS` | `8` | Max decisions / action items |
| `GEMINI_API_KEY` | *(empty)* | Gemini key (backend only, in `.env`, never frontend) |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini Flash model name (configurable) |
| `GEMINI_MAX_TRANSCRIPT_CHARS` | `24000` | Truncation cap for very long transcripts |
| `GEMINI_MAX_OUTPUT_TOKENS` | `2000` | Bounds Gemini latency/cost |

## API

`POST /api/analyze` — multipart form, field `audio` (`.mp3`, `.wav`, `.m4a`).
Returns:

```json
{
  "headline": "...",
  "transcript": "...",
  "summary": "...",
  "key_points": ["..."],
  "decisions": [{"decision": "...", "reason": "...", "evidence": "..."}],
  "action_items": [{"task": "...", "owner": "...", "deadline": "...", "priority": "high", "evidence": "..."}],
  "topics": ["..."],
  "open_questions": ["..."],
  "language": "en",
  "audio_duration_seconds": 84.16,
  "backends": {"speech_to_text": "faster-whisper:base.en", "summarization": "gemini:gemini-3.5-flash-lite"},
  "timing": {"transcribe_seconds": 7.0, "summarize_seconds": 2.1, "total_seconds": 9.1}
}
```

Verify the Gemini stage without audio:

```bash
# needs GEMINI_API_KEY in .env
python scripts/verify_gemini.py
```
