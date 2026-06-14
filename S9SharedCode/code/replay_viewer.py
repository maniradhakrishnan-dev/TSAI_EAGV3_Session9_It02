"""Generate a self-contained HTML replay viewer for a Session 8 run.

Reads state/sessions/<sid>/ and produces replay_<sid>.html with:
  1. Original user goal
  2. Planner DAG (Mermaid)
  3. Browser path chosen per node
  4. Browser actions taken
  5. Screenshots (base64-embedded)
  6. Extracted data
  7. Final comparison table
  8. Turn count and cost summary

Usage:
    uv run python replay_viewer.py <session_id>
    # Opens replay_s8-XXXX.html in the current directory.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from persistence import SessionStore, list_sessions
from schemas import NodeState

BROWSER_ROOT = Path(__file__).parent / "state" / "sessions"


def _load_session(sid: str):
    store = SessionStore(sid)
    query = store.read_query() or "(no query)"
    nodes = store.read_all_nodes()
    graph_path = store.dir / "graph.json"
    graph_data = json.loads(graph_path.read_text()) if graph_path.exists() else None
    return query, nodes, graph_data, store


def _encode_image(path: Path) -> str:
    data = path.read_bytes()
    return base64.b64encode(data).decode()


def _collect_browser_screenshots(session_dir: Path) -> dict[str, list[dict]]:
    """Map browser_<ts> -> list of {turn, img_b64, legend}."""
    bdir = session_dir / "browser"
    if not bdir.exists():
        return {}
    result = {}
    for bd in sorted(bdir.iterdir()):
        if not bd.is_dir():
            continue
        a11y = bd / "a11y"
        if not a11y.exists():
            continue
        turns = []
        for png in sorted(a11y.glob("turn_*_raw.png")):
            turn_num = png.stem.replace("_raw", "").replace("turn_", "")
            legend_path = a11y / f"turn_{turn_num}_legend.txt"
            legend = legend_path.read_text()[:500] if legend_path.exists() else ""
            turns.append({
                "turn": int(turn_num),
                "img_b64": _encode_image(png),
                "legend": legend[:300],
            })
        result[bd.name] = turns
    return result


def _build_mermaid(graph_data: dict, nodes: list[NodeState]) -> str:
    """Build a Mermaid flowchart from graph edges and node metadata."""
    node_map = {}
    if graph_data and "nodes" in graph_data:
        for n in graph_data["nodes"]:
            nid = n.get("id", "")
            skill = n.get("skill", "?")
            status = n.get("status", "?")
            node_map[nid] = (skill, status)

    lines = ["graph TD"]
    for nid, (skill, status) in node_map.items():
        safe_id = nid.replace(":", "_")
        label = f"{nid}\\n{skill}"
        if status == "complete":
            lines.append(f'    {safe_id}["{label}"]:::complete')
        elif status == "skipped":
            lines.append(f'    {safe_id}["{label}"]:::skipped')
        else:
            lines.append(f'    {safe_id}["{label}"]:::other')

    if graph_data and "edges" in graph_data:
        for e in graph_data["edges"]:
            s = e["source"].replace(":", "_")
            t = e["target"].replace(":", "_")
            lines.append(f"    {s} --> {t}")

    return "\n".join(lines)


def _node_to_card(st: NodeState, idx: int) -> str:
    r = st.result
    skill = st.skill
    elapsed = f"{r.elapsed_s:.1f}s" if r and r.elapsed_s else "—"
    provider = r.provider if r and r.provider else "—"
    status_class = "pass" if st.status == "complete" else "fail"

    # Extract key output info
    output_html = ""
    if r and r.output:
        out = r.output
        if skill == "browser" and isinstance(out, dict):
            path = out.get("path", "—")
            turns = out.get("turns", "—")
            goal = out.get("goal", "")[:150]
            url = out.get("url", "")
            final_url = out.get("final_url", "")[:120]
            actions = out.get("actions", [])

            actions_html = ""
            for a in actions:
                t = a.get("turn", "?")
                acts = a.get("actions", [])
                outcome = a.get("outcome", "")
                act_strs = []
                for act in acts:
                    atype = act.get("type", "?")
                    val = act.get("value", "")
                    mark = act.get("mark", "")
                    if atype == "type":
                        act_strs.append(f'type "{val}" → mark {mark}')
                    elif atype == "click":
                        act_strs.append(f"click mark {mark}")
                    elif atype == "scroll":
                        act_strs.append(f"scroll {act.get('direction','')} {val}")
                    elif atype == "done":
                        done_val = str(val)[:200]
                        act_strs.append(f"✅ done: {done_val}")
                    else:
                        act_strs.append(f"{atype} {val}")
                actions_html += f'<div class="action-turn"><span class="turn-badge">T{t}</span> {" | ".join(act_strs)} <span class="outcome">→ {outcome}</span></div>'

            output_html = f"""
            <div class="browser-meta">
                <span class="badge badge-{path}">{path}</span>
                <span class="meta-item">🔄 {turns} turns</span>
                <span class="meta-item">🎯 {goal}</span>
            </div>
            <div class="browser-urls">
                <div>📍 {url}</div>
                <div>🏁 {final_url}</div>
            </div>
            <details class="actions-detail"><summary>Browser Actions ({len(actions)} turns)</summary>
                {actions_html}
            </details>"""

        elif skill == "critic" and isinstance(out, dict):
            verdict = out.get("verdict", "?")
            rationale = out.get("rationale", "")
            v_class = "pass" if verdict == "pass" else "fail"
            output_html = f'<div class="critic-verdict verdict-{v_class}"><strong>{verdict.upper()}</strong>: {rationale}</div>'

        elif skill == "distiller" and isinstance(out, dict):
            fields = out.get("fields", {})
            rationale = out.get("rationale", "")
            fields_json = json.dumps(fields, indent=2, ensure_ascii=False)
            output_html = f'<details><summary>Extracted Fields</summary><pre class="json-block">{fields_json}</pre><p class="rationale">{rationale}</p></details>'

        elif skill == "planner" and isinstance(out, dict):
            rationale = out.get("rationale", "")
            plan_nodes = out.get("nodes", [])
            plan_items = "".join(
                f'<li><strong>{pn.get("skill","?")}</strong> — {pn.get("metadata",{}).get("label","")}: {pn.get("metadata",{}).get("goal", pn.get("metadata",{}).get("question",""))[:120]}</li>'
                for pn in plan_nodes
            )
            output_html = f'<div class="plan-rationale">{rationale}</div><ul class="plan-nodes">{plan_items}</ul>'

        elif skill == "formatter" and isinstance(out, dict):
            answer = out.get("final_answer", "")
            output_html = f'<div class="final-answer">{answer}</div>'

    return f"""
    <div class="node-card {status_class}" id="node-{st.node_id.replace(':','_')}">
        <div class="node-header">
            <span class="node-id">{st.node_id}</span>
            <span class="skill-badge skill-{skill}">{skill}</span>
            <span class="elapsed">⏱ {elapsed}</span>
            <span class="provider-tag">{provider}</span>
            <span class="status-dot status-{st.status}"></span>
        </div>
        <div class="node-body">{output_html}</div>
    </div>"""


def _compute_summary(nodes: list[NodeState]) -> dict:
    total_time = sum((n.result.elapsed_s or 0) for n in nodes if n.result)
    browser_nodes = [n for n in nodes if n.skill == "browser" and n.status == "complete"]
    total_browser_turns = sum(
        (n.result.output.get("turns", 0) if isinstance(n.result.output, dict) else 0)
        for n in browser_nodes if n.result
    )
    critic_nodes = [n for n in nodes if n.skill == "critic" and n.status == "complete"]
    critic_fails = sum(
        1 for n in critic_nodes
        if n.result and isinstance(n.result.output, dict) and n.result.output.get("verdict") == "fail"
    )
    paths_used = set()
    for n in browser_nodes:
        if n.result and isinstance(n.result.output, dict):
            paths_used.add(n.result.output.get("path", "?"))

    providers = {}
    for n in nodes:
        if n.result and n.result.provider:
            providers[n.result.provider] = providers.get(n.result.provider, 0) + 1

    return {
        "total_nodes": len(nodes),
        "total_time": f"{total_time:.1f}s",
        "browser_calls": len(browser_nodes),
        "total_browser_turns": total_browser_turns,
        "critic_fails": critic_fails,
        "critic_total": len(critic_nodes),
        "paths_used": ", ".join(sorted(paths_used)) or "—",
        "providers": providers,
    }


def generate_html(sid: str) -> str:
    query, nodes, graph_data, store = _load_session(sid)
    mermaid = _build_mermaid(graph_data, nodes) if graph_data else "graph TD\n    A[No graph data]"
    screenshots = _collect_browser_screenshots(store.dir)
    summary = _compute_summary(nodes)

    node_cards = "\n".join(_node_to_card(n, i) for i, n in enumerate(nodes))

    # Build screenshot gallery
    gallery_html = ""
    for browser_id, turns in screenshots.items():
        slides = "".join(
            f'<div class="slide" data-idx="{i}"><img src="data:image/png;base64,{t["img_b64"]}" alt="Turn {t["turn"]}"><div class="slide-caption">Turn {t["turn"]}</div></div>'
            for i, t in enumerate(turns)
        )
        gallery_html += f"""
        <div class="screenshot-gallery">
            <h4>🖥 {browser_id}</h4>
            <div class="carousel-container">
                <button class="carousel-btn prev" onclick="carouselPrev(this)">‹</button>
                <div class="carousel-track">{slides}</div>
                <button class="carousel-btn next" onclick="carouselNext(this)">›</button>
            </div>
            <div class="carousel-counter"></div>
        </div>"""

    # Provider stats
    provider_items = "".join(f"<li><strong>{k}</strong>: {v} calls</li>" for k, v in summary["providers"].items())

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Session Replay — {sid}</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {{
    --bg: #0f0f1a; --surface: #1a1a2e; --surface2: #16213e;
    --accent: #7c3aed; --accent2: #a78bfa; --green: #10b981;
    --red: #ef4444; --yellow: #f59e0b; --blue: #3b82f6;
    --text: #e2e8f0; --text2: #94a3b8; --border: #2d2d44;
    --radius: 12px;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}

/* Hero */
.hero {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    border-radius: var(--radius); padding: 40px; margin-bottom: 32px;
    border: 1px solid var(--border); position: relative; overflow: hidden; }}
.hero::before {{ content: ''; position: absolute; top: -50%; right: -50%;
    width: 100%; height: 200%; background: radial-gradient(circle, rgba(124,58,237,0.1) 0%, transparent 70%);
    pointer-events: none; }}
.hero h1 {{ font-size: 2rem; font-weight: 700; margin-bottom: 8px;
    background: linear-gradient(135deg, var(--accent2), var(--blue));
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
.hero .query {{ font-size: 1.1rem; color: var(--text2); margin-top: 12px;
    padding: 12px 16px; background: rgba(0,0,0,0.3); border-radius: 8px;
    border-left: 3px solid var(--accent); }}
.hero .session-id {{ font-size: 0.85rem; color: var(--text2); font-family: monospace; }}

/* Summary cards */
.summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 16px; margin-bottom: 32px; }}
.stat-card {{ background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 20px; text-align: center;
    transition: transform 0.2s, box-shadow 0.2s; }}
.stat-card:hover {{ transform: translateY(-2px); box-shadow: 0 8px 24px rgba(124,58,237,0.15); }}
.stat-card .stat-value {{ font-size: 1.8rem; font-weight: 700; color: var(--accent2); }}
.stat-card .stat-label {{ font-size: 0.8rem; color: var(--text2); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 4px; }}

/* Sections */
.section {{ background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 24px; margin-bottom: 24px; }}
.section h2 {{ font-size: 1.3rem; font-weight: 600; margin-bottom: 16px;
    padding-bottom: 8px; border-bottom: 1px solid var(--border); }}
.section h3 {{ font-size: 1.1rem; margin: 16px 0 8px; }}

/* Mermaid */
.mermaid {{ background: rgba(0,0,0,0.2); border-radius: 8px; padding: 16px; overflow-x: auto; }}

/* Node cards */
.node-card {{ background: var(--surface2); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px; margin-bottom: 12px;
    transition: border-color 0.2s; }}
.node-card:hover {{ border-color: var(--accent); }}
.node-card.fail {{ border-left: 3px solid var(--red); }}
.node-card.pass {{ border-left: 3px solid var(--green); }}
.node-header {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }}
.node-id {{ font-family: monospace; font-weight: 600; color: var(--accent2); }}
.skill-badge {{ padding: 2px 10px; border-radius: 20px; font-size: 0.75rem;
    font-weight: 600; text-transform: uppercase; }}
.skill-planner {{ background: rgba(124,58,237,0.2); color: var(--accent2); }}
.skill-browser {{ background: rgba(59,130,246,0.2); color: var(--blue); }}
.skill-distiller {{ background: rgba(16,185,129,0.2); color: var(--green); }}
.skill-critic {{ background: rgba(245,158,11,0.2); color: var(--yellow); }}
.skill-formatter {{ background: rgba(236,72,153,0.2); color: #ec4899; }}
.elapsed {{ font-size: 0.8rem; color: var(--text2); }}
.provider-tag {{ font-size: 0.75rem; color: var(--text2); font-family: monospace; }}
.status-dot {{ width: 8px; height: 8px; border-radius: 50%; margin-left: auto; }}
.status-complete {{ background: var(--green); }}
.status-skipped {{ background: var(--text2); }}

/* Browser meta */
.browser-meta {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }}
.badge {{ padding: 2px 8px; border-radius: 12px; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; }}
.badge-a11y {{ background: rgba(59,130,246,0.2); color: var(--blue); }}
.badge-extract {{ background: rgba(16,185,129,0.2); color: var(--green); }}
.badge-vision {{ background: rgba(245,158,11,0.2); color: var(--yellow); }}
.badge-deterministic {{ background: rgba(124,58,237,0.2); color: var(--accent2); }}
.meta-item {{ font-size: 0.8rem; color: var(--text2); }}
.browser-urls {{ font-size: 0.75rem; color: var(--text2); font-family: monospace; margin-bottom: 8px; word-break: break-all; }}
.actions-detail {{ margin-top: 8px; }}
.actions-detail summary {{ cursor: pointer; color: var(--accent2); font-size: 0.85rem; font-weight: 500; }}
.action-turn {{ padding: 6px 12px; margin: 4px 0; background: rgba(0,0,0,0.2);
    border-radius: 6px; font-size: 0.8rem; font-family: monospace; }}
.turn-badge {{ background: var(--accent); color: white; padding: 1px 6px;
    border-radius: 10px; font-size: 0.7rem; margin-right: 6px; }}
.outcome {{ color: var(--green); font-size: 0.75rem; }}

/* Critic */
.critic-verdict {{ padding: 10px 14px; border-radius: 8px; font-size: 0.85rem; }}
.verdict-pass {{ background: rgba(16,185,129,0.1); border: 1px solid rgba(16,185,129,0.3); color: var(--green); }}
.verdict-fail {{ background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3); color: var(--red); }}

/* Distiller */
.json-block {{ background: rgba(0,0,0,0.3); padding: 12px; border-radius: 8px;
    font-size: 0.8rem; overflow-x: auto; color: var(--accent2); }}
.rationale {{ font-size: 0.8rem; color: var(--text2); margin-top: 6px; font-style: italic; }}

/* Planner */
.plan-rationale {{ font-size: 0.85rem; color: var(--text2); margin-bottom: 8px;
    padding: 8px 12px; background: rgba(124,58,237,0.08); border-radius: 8px; }}
.plan-nodes {{ list-style: none; }}
.plan-nodes li {{ padding: 4px 0; font-size: 0.85rem; border-bottom: 1px solid rgba(255,255,255,0.05); }}

/* Final answer */
.final-answer {{ padding: 20px; background: linear-gradient(135deg, rgba(16,185,129,0.08), rgba(59,130,246,0.08));
    border-radius: 10px; border: 1px solid rgba(16,185,129,0.2);
    font-size: 0.95rem; line-height: 1.8; white-space: pre-wrap; }}

/* Screenshots */
.screenshot-gallery {{ margin-bottom: 20px; }}
.screenshot-gallery h4 {{ color: var(--text2); font-size: 0.9rem; margin-bottom: 8px; }}
.carousel-container {{ position: relative; display: flex; align-items: center; }}
.carousel-track {{ display: flex; overflow: hidden; border-radius: 8px; flex: 1; }}
.slide {{ min-width: 100%; transition: transform 0.3s ease; display: none; }}
.slide.active {{ display: block; }}
.slide img {{ width: 100%; border-radius: 8px; }}
.slide-caption {{ text-align: center; font-size: 0.8rem; color: var(--text2); margin-top: 4px; }}
.carousel-btn {{ position: absolute; z-index: 2; background: rgba(124,58,237,0.7);
    border: none; color: white; font-size: 1.5rem; padding: 8px 14px;
    border-radius: 50%; cursor: pointer; transition: background 0.2s; }}
.carousel-btn:hover {{ background: var(--accent); }}
.carousel-btn.prev {{ left: 8px; }}
.carousel-btn.next {{ right: 8px; }}
.carousel-counter {{ text-align: center; font-size: 0.75rem; color: var(--text2); margin-top: 4px; }}

/* Tabs */
.tabs {{ display: flex; gap: 4px; margin-bottom: 16px; }}
.tab {{ padding: 8px 16px; border-radius: 8px 8px 0 0; border: 1px solid var(--border);
    border-bottom: none; background: transparent; color: var(--text2); cursor: pointer;
    font-family: inherit; font-size: 0.85rem; transition: all 0.2s; }}
.tab.active {{ background: var(--surface); color: var(--accent2); }}
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}
</style>
</head>
<body>
<div class="container">

<div class="hero">
    <div class="session-id">SESSION {sid}</div>
    <h1>🔁 Session Replay Viewer</h1>
    <div class="query">💬 {query}</div>
</div>

<div class="summary-grid">
    <div class="stat-card"><div class="stat-value">{summary['total_nodes']}</div><div class="stat-label">Total Nodes</div></div>
    <div class="stat-card"><div class="stat-value">{summary['total_time']}</div><div class="stat-label">Total Time</div></div>
    <div class="stat-card"><div class="stat-value">{summary['browser_calls']}</div><div class="stat-label">Browser Calls</div></div>
    <div class="stat-card"><div class="stat-value">{summary['total_browser_turns']}</div><div class="stat-label">Browser Turns</div></div>
    <div class="stat-card"><div class="stat-value">{summary['critic_fails']}/{summary['critic_total']}</div><div class="stat-label">Critic Fails</div></div>
    <div class="stat-card"><div class="stat-value">{summary['paths_used']}</div><div class="stat-label">Cascade Paths</div></div>
</div>

<div class="tabs">
    <button class="tab active" onclick="switchTab(event, 'tab-dag')">📊 DAG</button>
    <button class="tab" onclick="switchTab(event, 'tab-timeline')">📜 Timeline</button>
    <button class="tab" onclick="switchTab(event, 'tab-screenshots')">🖼 Screenshots</button>
    <button class="tab" onclick="switchTab(event, 'tab-result')">✅ Result</button>
</div>

<div id="tab-dag" class="tab-content active">
    <div class="section">
        <h2>📊 Planner DAG</h2>
        <div class="mermaid">
{mermaid}
        </div>
    </div>
</div>

<div id="tab-timeline" class="tab-content">
    <div class="section">
        <h2>📜 Node Execution Timeline</h2>
        <p style="color:var(--text2);font-size:0.85rem;margin-bottom:16px;">
            Providers: <ul style="list-style:none;display:inline;padding:0;">{provider_items}</ul>
        </p>
        {node_cards}
    </div>
</div>

<div id="tab-screenshots" class="tab-content">
    <div class="section">
        <h2>🖼 Browser Screenshots</h2>
        {gallery_html if gallery_html else '<p style="color:var(--text2)">No screenshots found.</p>'}
    </div>
</div>

<div id="tab-result" class="tab-content">
    <div class="section">
        <h2>✅ Final Comparison Result</h2>
        {"".join(_node_to_card(n, 0) for n in nodes if n.skill == "formatter" and n.status == "complete")}
    </div>
</div>

</div>

<script>
mermaid.initialize({{ startOnLoad: true, theme: 'dark',
    themeVariables: {{ primaryColor: '#7c3aed', primaryTextColor: '#e2e8f0',
        primaryBorderColor: '#4c1d95', lineColor: '#6366f1',
        secondaryColor: '#1e3a5f', tertiaryColor: '#1a1a2e' }}
}});

function switchTab(e, tabId) {{
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    e.target.classList.add('active');
    document.getElementById(tabId).classList.add('active');
}}

// Carousel logic
document.querySelectorAll('.carousel-track').forEach(track => {{
    const slides = track.querySelectorAll('.slide');
    if (slides.length > 0) slides[0].classList.add('active');
}});

function carouselNext(btn) {{
    const track = btn.parentElement.querySelector('.carousel-track');
    const slides = track.querySelectorAll('.slide');
    let cur = [...slides].findIndex(s => s.classList.contains('active'));
    slides[cur].classList.remove('active');
    slides[(cur + 1) % slides.length].classList.add('active');
}}

function carouselPrev(btn) {{
    const track = btn.parentElement.querySelector('.carousel-track');
    const slides = track.querySelectorAll('.slide');
    let cur = [...slides].findIndex(s => s.classList.contains('active'));
    slides[cur].classList.remove('active');
    slides[(cur - 1 + slides.length) % slides.length].classList.add('active');
}}
</script>
</body>
</html>"""

    return html


def main() -> int:
    args = sys.argv[1:]
    if not args:
        sessions = list_sessions()
        if not sessions:
            print("replay_viewer: no sessions found.", file=sys.stderr)
            return 2
        print("Available sessions:")
        for s in sessions:
            print(f"  {s}")
        print("\nUsage: uv run python replay_viewer.py <session_id>")
        return 0

    sid = args[0]
    print(f"Generating replay for session {sid}...")
    html = generate_html(sid)
    out_path = Path(f"replay_{sid}.html")
    out_path.write_text(html)
    print(f"✅ Replay saved to: {out_path.resolve()}")
    print(f"   Open in browser: file://{out_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
