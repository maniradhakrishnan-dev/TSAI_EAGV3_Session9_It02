# Session 9 — Browser-Capable Autonomous Agent

> EAGV3 Session 9 Assignment: A browser-capable agent built on the Session 8 DAG orchestrator, performing real-world comparison tasks on Amazon with a full replay viewer and web dashboard.

---

## 🎯 What This Does

Enter a natural-language comparison query (e.g., *"Compare 3 laptops under ₹80,000 on Amazon"*) and the agent:

1. **Plans** a multi-step DAG using the Planner skill
2. **Browses Amazon** autonomously — searches, clicks filters, opens product pages, scrolls, extracts specs
3. **Distills** raw page data into structured fields (brand, processor, RAM, hard disk)
4. **Self-corrects** via a Critic that rejects hallucinated or incomplete results, triggering automatic replanning
5. **Formats** a final comparison table
6. **Generates** an interactive HTML replay of the entire run

All orchestrated through a growing-graph DAG — no human intervention required.

---

## 🏗 Architecture

### 4-Layer Browser Cascade

The browser skill uses a cost-optimized escalation cascade — cheapest layer first, escalating only on failure:

```
┌─────────────────────────────────────────────────┐
│              Precondition Check                  │
│    Detect CAPTCHAs, login walls, rate limits     │
└──────────────┬──────────────────────────────────┘
               ▼
┌──────────────────────────┐  Zero LLM cost
│  Layer 1: Extract        │  httpx + trafilatura
│  (static HTML → markdown)│  (fastest, cheapest)
└──────────┬───────────────┘
           ▼ (if insufficient)
┌──────────────────────────┐  Zero LLM cost
│  Layer 2a: Deterministic │  Playwright + CSS selectors
│  (headless browser)      │  (anti-bot mitigations)
└──────────┬───────────────┘
           ▼ (if insufficient)
┌──────────────────────────┐  Low LLM cost
│  Layer 2b: a11y Tree     │  Playwright a11y tree →
│  (accessibility-driven)  │  cheap LLM picks actions
└──────────┬───────────────┘
           ▼ (if empty a11y / canvas)
┌──────────────────────────┐  High LLM cost
│  Layer 3: Vision / SoM   │  Screenshot + bounding
│  (set-of-marks)          │  boxes → VLM selects target
└──────────────────────────┘
```

### DAG Orchestrator (Session 8 Core)

```
User Query → Planner → [browser ×N] → Distiller → Critic ─┬─ pass → Formatter → Answer
                                                            └─ fail → Replan → ...
```

- **Planner**: Emits a DAG of skill nodes; fan-out for parallel browser calls
- **Browser**: Navigates Amazon, performs search/filter/sort/click actions
- **Distiller**: Extracts structured fields from raw page text
- **Critic**: Validates output against user query; rejects hallucinations
- **Formatter**: Produces the final user-facing answer
- **Recovery**: On critic-fail, the Planner is re-invoked with prior successes wired in (avoids redoing completed work)

### Key Design Decisions

- **No orchestrator modifications** — Browser skill plugs in via `agent_config.yaml`
- **No forbidden frameworks** — No LangChain, LlamaIndex, CrewAI, or AutoGen
- **Allowed libraries only** — httpx, trafilatura, Playwright, Pillow, Pydantic, NetworkX, FAISS, SQLite
- **Fence rule** — Dropdown/popover triggers are isolated to single-action turns to prevent stale-state bugs
- **Cross-session memory** — FAISS-indexed memory from prior runs informs new sessions

---

## 📂 Project Structure

```
S9SharedCode/code/
├── flow.py              # DAG orchestrator (Session 8 core)
├── skills.py            # Skill registry and execution
├── schemas.py           # Pydantic models (NodeState, AgentResult, BrowserOutput)
├── persistence.py       # Session storage (atomic writes, JSON serialization)
├── recovery.py          # Failure policy and critic-fail recovery
├── memory.py            # FAISS vector memory (cross-session)
├── gateway.py           # LLM gateway connection
├── agent_config.yaml    # Skill catalogue configuration
│
├── browser/             # Browser skill (Session 9 addition)
│   ├── skill.py         # 4-layer cascade orchestration
│   ├── client.py        # Playwright browser client
│   ├── driver.py        # Action execution engine
│   ├── dom.py           # DOM processing
│   └── highlight.py     # Set-of-marks bounding box overlay
│
├── replay_viewer.py     # HTML replay generator
├── replay.py            # CLI replay (step-through)
├── web_app.py           # FastAPI web dashboard
├── static/index.html    # Dashboard frontend
│
├── prompts/             # Skill prompt templates
├── state/sessions/      # Persisted session data
│   └── s8-XXXXXXXX/
│       ├── query.txt
│       ├── graph.json
│       ├── replay.html   # Auto-generated after each run
│       ├── nodes/        # Per-node JSON traces
│       └── browser/      # Screenshots + a11y legends
│
└── llm_gatewayV9/       # LLM gateway server
```

---

## 🚀 Setup & Run

### Prerequisites
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- LLM Gateway running (Gemini/Groq keys in `.env`)

### 1. Install Dependencies
```bash
cd S9SharedCode/code
cp .env.example .env
# Add your API keys to .env
uv sync
uv run playwright install chromium
```

### 2. Start the LLM Gateway
```bash
cd llm_gatewayV9
uv run main.py
```

### 3. Run via CLI
```bash
cd S9SharedCode/code
uv run flow.py "Compare 3 laptops under 80000 on Amazon with brand, processor, RAM, hard disk details"
```
The replay HTML is auto-generated in the session folder.

### 4. Run via Web Dashboard
```bash
cd S9SharedCode/code
uv run python web_app.py
# Open http://localhost:8000
```

---

## 🔁 Replay Viewer

Every run automatically generates a self-contained HTML replay showing all 8 required elements:

| # | Element | Implementation |
|---|---------|----------------|
| 1 | Original user goal | Hero section with query text |
| 2 | Planner DAG | Interactive Mermaid.js graph |
| 3 | Browser path chosen | `a11y` / `extract` / `vision` badge per node |
| 4 | Browser actions taken | Expandable turn-by-turn action log |
| 5 | Screenshots | Carousel galleries with embedded PNGs |
| 6 | Extracted data | Structured JSON fields from distiller |
| 7 | Final comparison table | Formatted answer in Result tab |
| 8 | Turn count & cost summary | Summary dashboard (nodes, time, turns, critic fails) |

### Web Dashboard Features
- **Live progress** — WebSocket streaming of node execution
- **Session history** — Sidebar listing all past runs
- **Embedded replay** — Click any session to view its full replay inline
- **New queries** — Run agent directly from the browser

---

## 📊 Sample Runs

### Run 1: Laptops under ₹70,000 (Session `s8-fcb6ba4e`)
- **Nodes**: 15 | **Browser calls**: 3 | **Critic fails**: 2/3
- **Result**: ASUS Vivobook 16, Acer Swift Lite, HP Laptop 15s
- **Browser actions**: Search → filter Price Low→High → click product pages → extract specs

### Run 2: Laptops under ₹1,00,000 (Session `s8-3c950bad`)
- **Nodes**: 41 | **Browser calls**: 12 (parallel fan-out) | **Critic fails**: 6/7
- **Result**: Apple MacBook Air M2, ASUS Vivobook Pro 15, HP Pavilion 15
- **Browser actions**: Search → sort → open 3 product pages in parallel → extract specs → critic rejects → replan with different pages → repeat until all specs verified

### Visible Browser Actions (≥3 required ✓)
- `type` "laptops under 100000" into Amazon search bar
- `click` search button / sort dropdown
- `click` product page links
- `scroll` down to view product details
- `click` filter categories
- `done` with extracted specifications

---

## 🔧 Technical Details

### BrowserOutput Schema
```python
class BrowserOutput(BaseModel):
    url: str                                          # entry URL
    goal: str                                         # what to do
    path: Literal["extract", "deterministic", "a11y", "vision"]
    turns: int                                        # interaction turns
    content: str | None = None                        # extracted text
    actions: list[dict] = []                          # action log
    final_url: str | None = None                      # landing URL
```

### Orchestrator Behaviors
- **Recovery Amnesia Fix**: Prior successful node IDs passed to recovery Planner to avoid re-running completed work
- **Critic Splicing**: Auto-inserted between Distiller and Formatter
- **Critic-Fail Cap**: Prevents infinite recovery loops (max 1 recovery per branch)
- **Cross-Session Memory**: FAISS-indexed queries visible to all skills

### Key Files Changed from Session 8
- `browser/` — New skill module (entire directory)
- `agent_config.yaml` — Added browser skill entry
- `flow.py` — Added auto replay generation (lines 344-352)
- `replay_viewer.py` — New: HTML replay generator
- `web_app.py` — New: FastAPI web dashboard
- `static/index.html` — New: Dashboard frontend

---

## 📦 Submission Checklist

- [x] Working browser agent with 4-layer cascade
- [x] Real comparison task on Amazon (not passive scraping)
- [x] ≥3 visible browser actions (search, filter, sort, click, scroll)
- [x] Structured comparison output with brand, processor, RAM, hard disk
- [x] Replay viewer with all 8 required elements
- [x] Web dashboard UI (FastAPI + WebSocket)
- [x] Session trace data (node JSONs, graph.json, screenshots)
- [x] No orchestrator core modifications (browser via skill catalogue)
- [x] No forbidden frameworks
- [x] Architecture note (this README)
- [x] YouTube demo video
- [x] GitHub repo push

---
## Working Video
https://youtu.be/DjODk-rg4fY

### More Working Examples
https://youtu.be/neKu3UCUnOA

## 📝 License

Educational project for EAGV3 Session 9.
