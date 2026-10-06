"""End-to-end pipeline check: sample audio → transcript → structured summary.

Run:  python scripts/run_pipeline_test.py [path/to/audio.(wav|mp3|m4a)]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.pipeline.runner import MeetingPipeline  # noqa: E402


def main() -> int:
    audio = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        PROJECT_ROOT / "samples" / "sample_meeting.wav"
    )
    if not audio.exists():
        print(f"ERROR: sample audio not found: {audio}")
        return 1

    print(f"Running pipeline on: {audio}")
    result = MeetingPipeline().run(audio)
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
