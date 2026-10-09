# MeetMindFrontend

Vanilla HTML/CSS/JS project — no build tooling, no package manager, no tests.

## Structure
- `index.html` — app shell (sidebar + topbar) with upload / processing / results / error views
- `app.js` — main script (calls `POST /api/analyze`, renders report + sidebar section nav)
- `style.css` — dark graphite workspace theme (single coral accent, no gradients/glow)

## Development
Run the backend from the repo root so it serves this folder:

```
python -m uvicorn app.main:app --port 8000
```

then open http://127.0.0.1:8000/ . The backend injects
cache-busting `?v=` query strings into the asset URLs — after changing
CSS/JS, restart uvicorn (or hard-refresh with Ctrl+Shift+R) so the new
hashes are picked up. Do not open `index.html` via `file://` for full
testing (`fetch("/api/analyze")` needs the backend).