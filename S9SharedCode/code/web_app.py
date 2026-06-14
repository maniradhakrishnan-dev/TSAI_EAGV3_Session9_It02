"""Web dashboard for the Session 8/9 agent.

Provides a local UI at http://localhost:8000 with:
  - Query input + live progress via WebSocket
  - Session history with replay viewer
  - Final result display

Usage:  uv run python web_app.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from persistence import SessionStore, list_sessions, SESSIONS_ROOT

app = FastAPI(title="Browser Agent Dashboard")
CODE_DIR = Path(__file__).parent


# ── API Routes ───────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return (CODE_DIR / "static" / "index.html").read_text()


@app.get("/api/sessions")
async def get_sessions():
    sessions = []
    for sid in reversed(list_sessions()):
        store = SessionStore(sid)
        query = store.read_query() or ""
        has_replay = (store.dir / "replay.html").exists()
        node_count = len(list(store.nodes_dir.glob("n_*.json")))
        sessions.append({"id": sid, "query": query[:120],
                         "has_replay": has_replay, "nodes": node_count})
    return sessions


@app.get("/api/replay/{session_id}", response_class=HTMLResponse)
async def get_replay(session_id: str):
    replay = SESSIONS_ROOT / session_id / "replay.html"
    if replay.exists():
        return HTMLResponse(replay.read_text())
    # Generate on-demand if missing
    try:
        from replay_viewer import generate_html
        html = generate_html(session_id)
        replay.write_text(html)
        return HTMLResponse(html)
    except Exception as e:
        return HTMLResponse(f"<h2>Replay not available: {e}</h2>", status_code=404)


@app.websocket("/ws/run")
async def ws_run(ws: WebSocket):
    """Accept a query, run flow.py as subprocess, stream stdout lines."""
    await ws.accept()
    try:
        data = await ws.receive_text()
        msg = json.loads(data)
        query = msg.get("query", "").strip()
        if not query:
            await ws.send_json({"type": "error", "data": "Empty query"})
            return

        await ws.send_json({"type": "status", "data": "Starting agent..."})

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "flow.py", query,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(CODE_DIR),
        )

        session_id = None
        final_answer = None
        lines_buffer = []

        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            lines_buffer.append(line)

            # Extract session id
            if line.startswith("session s8-"):
                session_id = line.split()[1]
                await ws.send_json({"type": "session", "data": session_id})

            # Node progress
            if line.startswith("[n:"):
                await ws.send_json({"type": "node", "data": line})

            # Critic recovery
            if "critic-fail recovery" in line:
                await ws.send_json({"type": "recovery", "data": line})

            # Memory
            if "[memory" in line:
                await ws.send_json({"type": "info", "data": line})

            # Final answer
            if line.startswith("FINAL:"):
                final_answer = line[6:].strip()

            # Replay path
            if "Replay saved:" in line:
                await ws.send_json({"type": "replay_ready", "data": session_id})

        await proc.wait()

        await ws.send_json({
            "type": "complete",
            "data": {
                "session_id": session_id,
                "final_answer": final_answer,
                "node_count": len([l for l in lines_buffer if l.startswith("[n:")]),
            }
        })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "data": str(e)})
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    print("🚀 Dashboard: http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
