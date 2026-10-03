"""FastAPI host for the React dashboard.

Serves the JSON API under /api and, when ``frontend/dist`` has been built, the
compiled SPA from the same origin so production is a single port. Without a
build it falls back to the original server-rendered table, so the dashboard
still works on a machine with no Node toolchain.
"""
from __future__ import annotations

from pathlib import Path
from string import Template

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import AppConfig, get_config
from app.dashboard.api import router as api_router
from app.pipeline.orchestrator import process_batch, status_summary
from app.storage.database import get_engine, get_session_factory
from app.storage.models import Document

# frontend/ sits next to the repo root; main.py is the package entrypoint.
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

_HTML = """<!doctype html>
<html><head><title>Finance Report Extractor</title>
<style>
body{font-family:system-ui;margin:2rem;background:#f5f7fa;color:#1c2733}
h1{color:#1f4e78}.cards{display:flex;gap:1rem;flex-wrap:wrap}
.card{background:#fff;border-radius:8px;padding:1rem 1.5rem;box-shadow:0 1px 3px rgba(0,0,0,.12)}
.card h2{margin:.2rem 0;font-size:1.6rem;color:#1f4e78}
table{border-collapse:collapse;width:100%;background:#fff;margin-top:1rem}
th,td{border:1px solid #ddd;padding:.4rem .6rem;text-align:left;font-size:.9rem}
th{background:#1f4e78;color:#fff}
button{background:#1f4e78;color:#fff;border:none;padding:.6rem 1.2rem;border-radius:6px;cursor:pointer}
.note{max-width:52rem;margin:.6rem 0 1.2rem;color:#55606b;font-size:.9rem}
code{background:#eef1f5;padding:.1rem .35rem;border-radius:4px}
</style></head><body>
<h1>Finance Report Extractor &mdash; Dashboard</h1>
<p class="note">The React frontend is not built yet. Run <code>npm install &amp;&amp; npm run build</code>
inside <code>frontend/</code>, or use <code>npm run dev</code> for hot reload on port 5173.</p>
<div class="cards">
<div class="card"><h2>$companies</h2>Companies</div>
<div class="card"><h2>$documents</h2>PDFs</div>
<div class="card"><h2>$completed</h2>Completed</div>
<div class="card"><h2>$review</h2>Review Required</div>
<div class="card"><h2>$failed</h2>Failed</div>
<div class="card"><h2>$avg_conf</h2>Avg Confidence</div>
</div>
<form method="post" action="/start"><button type="submit">Start processing pending</button></form>
<table><tr><th>Company</th><th>File</th><th>Status</th><th>Year</th><th>Confidence</th></tr>
$rows</table>
</body></html>"""


def create_app(cfg: AppConfig) -> FastAPI:
    app = FastAPI(title="Finance Report Extractor Dashboard")

    # Vite's dev server runs on a different port and proxies /api through, so CORS
    # is only needed when it is reached directly (e.g. a separate origin).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173", "http://127.0.0.1:5173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(api_router)
    app.dependency_overrides[get_config] = lambda: cfg

    def render() -> str:
        s = status_summary(cfg)
        engine = get_engine(cfg)
        Session = get_session_factory(engine)
        with Session() as session:
            docs = list(session.query(Document).order_by(Document.company).limit(300))
        rows = "".join(
            f"<tr><td>{d.company}</td><td>{Path(d.file_path).name}</td>"
            f"<td>{d.status}</td><td>{d.reporting_year or '-'}</td>"
            f"<td>{f'{d.avg_confidence:.0%}' if d.avg_confidence else '-'}</td></tr>"
            for d in docs
        )
        c = s["status_counts"]
        avg = s.get("avg_confidence")
        # string.Template, not str.format: the stylesheet above is full of CSS
        # braces, which .format() reads as replacement fields and raises
        # KeyError('font-family') — the reason this page used to 500.
        return Template(_HTML).safe_substitute(
            companies=s["companies"], documents=s["documents"],
            completed=c.get("COMPLETED", 0), review=c.get("REVIEW_REQUIRED", 0),
            failed=c.get("FAILED", 0),
            avg_conf=f"{avg * 100:.1f}%" if avg is not None else "-",
            rows=rows,
        )

    assets_dir = _FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/start", response_class=HTMLResponse)
    @app.post("/start")
    def start() -> HTMLResponse:
        import threading

        def work():
            process_batch(cfg)
        threading.Thread(target=work, daemon=True).start()
        return HTMLResponse("<p>Processing started in background. <a href='/'>Back</a></p>")

    @app.get("/", response_class=HTMLResponse)
    def index():
        index_file = _FRONTEND_DIST / "index.html"
        if index_file.is_file():
            return FileResponse(index_file)
        return HTMLResponse(render())

    # Client-side routing: any unmatched non-API path falls through to the SPA
    # shell so deep links (/documents/4) work on refresh.
    @app.get("/{full_path:path}", response_class=HTMLResponse,
             include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return HTMLResponse("Not found", status_code=404)
        index_file = _FRONTEND_DIST / "index.html"
        if index_file.is_file():
            return FileResponse(index_file)
        return HTMLResponse(render(), status_code=404)

    return app