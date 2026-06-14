Here is a technical specification and summary formatted explicitly for a coding agent to understand the system architecture, constraints, and assignment requirements to begin implementation.

### **System Context & Objective**

You are integrating a **Browser Skill** into an existing multi-agent DAG orchestrator (Session 8 architecture). The goal is to build an autonomous web-browsing agent capable of interacting with dynamic web pages (JavaScript, filters, multi-page workflows) to perform a real-world comparison task.

---

### **Core Architecture: The 4-Layer Cascade**

The browser skill uses a cost-optimized, 4-layer escalation cascade. It must attempt the cheapest/fastest method first and escalate only upon failure.

* **Precondition Check:** Detect CAPTCHAs, login walls, and rate limits. If blocked, return `error_code="gateway_blocked"` to trigger orchestrator recovery.
* **Layer 1 (Extract - Static):** Use `httpx` and `trafilatura` to download and extract markdown text. (Zero LLM cost, no browser).
* **Layer 2a (Deterministic - Headless Browser):** Use `Playwright` with hand-written CSS selectors to extract JSON. Apply anti-bot mitigations (real user-agent, `java_script_enabled=True`, undefined `navigator.webdriver`). (Zero LLM cost).
* **Layer 2b (Accessibility/a11y Tree - Dynamic):** Use `Playwright` to fetch the a11y tree. Pass the compact a11y summary to a cheap text-only LLM to determine the next action.
* *Rule:* Max 2 actions per turn.
* *Fence Rule:* If an action targets a dropdown/popover trigger (elements ending with `▾`, `:`, or starting with `Sort:`), it **must be the only action** in that turn, forcing a state re-read before the next interaction.


* **Layer 3 (Vision / Set-of-Marks):** Fallback for empty a11y trees (e.g., `<canvas>` elements). Use `Playwright` for a screenshot and `Pillow` to draw numbered bounding boxes over clickable elements (adjusting for Device Pixel Ratio / DPR). Pass the image to a Vision-Language Model (VLM) to select the target box.

---

### **Data Models & Integration**

The skill plugs into the system via `agent_config.yaml` and does not require orchestrator modifications.

```text
browser:
  prompt: prompts/browser.md
  description: |
    Fetches and interacts with web pages through a four-layer cascade
    (extract, deterministic, a11y, vision). Input metadata accepts url
    (required) and goal (required). Returns BrowserOutput with the
    chosen layer surfaced as output.path. Use when the Researcher
    skill's fetch_url is insufficient: JavaScript-rendered content,
    interactive widgets, multi-page workflows.
  provider_pin: null
```

**Schema (`BrowserOutput`)**

```python
class BrowserOutput(BaseModel):
    url: str
    goal: str
    path: Literal["extract", "deterministic", "a11y", "vision"]
    turns: int
    content: str | None = None
    actions: list[dict] = []
    final_url: str | None = None

```

**Known Orchestrator Behaviors to account for:**

* **Recovery Amnesia:** The orchestrator handles failure by re-planning. It passes completed sibling IDs (`prior_complete`) into the prompt to avoid re-running successful nodes.
* **Critic Splicing:** The orchestrator automatically splices a Critic node between the `Distiller` and its successor to check for hallucinations. The Critic evaluates based on both the `Distiller` output and the `USER_QUERY`.

---

## Glossary: terms and libraries used in this session

### **Development Constraints**

* **Allowed Libraries:** `httpx`, `trafilatura`, `Playwright` (Python), `Pillow`, `Pydantic`, `NetworkX` (for DAGs), `FAISS`,`SQLite`
* **Forbidden Libraries:** No third-party agentic frameworks (LangChain, LlamaIndex, CrewAI, AutoGen).
* **Orchestrator Limit:** Do not modify the core orchestrator. Add logic via the skill catalogue or Browser skill extensions.


### Protocol and Standards
MCP,CDP (Chrome DevTools Protocol),ARIA (Accessible Rich Internet Applications),DOM (Document Object Model).

### Concepts
Accessibility tree (a11y tree),Set-of-marks,VLM (Vision-Language Model),LLM (Large Language Model),DPR (Device Pixel Ratio),Headless browser,CSS selectors,CAPTCHA,Popover& dropdown,DAG (Directed Acyclic Graph)

### Sites and applications mentioned
Hugging Face,Excalidraw,tldraw, Photopea, Piskel, OpenProcessing,Redfin

---


### **Assignment: Browser Comparison Agent + Replay Viewer**

Build a browser-capable agent that completes a real comparison task on the web and produces a replay view of the run.

The goal is to demonstrate work that *Session 8’s* `web_search` + `fetch_url` *cannot reliably do* : interacting with dynamic pages, filters, dropdowns, tabs, search forms, product cards, pricing pages, or multi-step workflows. `web_search` and `fetch_url` are useful for static pages, but they fail on JavaScript-rendered pages, click-revealed widgets, multi-page flows, and sites where useful data appears only after filtering or sorting.

Students must choose one comparison task, such as:

* Compare 3 laptops under ₹80,000.
* Compare 5 AI coding tools by free plan and paid plan.
* Compare top 3 Hugging Face text-generation models sorted by likes.
* Compare 5 CNC/VMC training institutes in Bangalore.

The agent must perform at least *three visible browser actions* , such as search, filter, sort, open product/detail pages, switch tabs, expand hidden content, or submit a form. Passive scraping from search snippets is not accepted.

The final output must include a structured comparison table and a replay viewer/report showing:

1. Original user goal
2. Planner DAG
3. Browser path chosen: extract / deterministic / a11y / vision / blocked
4. Browser actions taken
5. Screenshots or page-state logs
6. Extracted data
7. Final comparison table
8. Turn count and cost summary

The orchestrator must not be modified. Any new behavior must plug in through the skill catalogue or as a Browser skill extension.

*Submission:* YouTube demo, GitHub repo, replay trace/log, final comparison output, and a short architecture note. *Code:* `llm_gatewayV9` | `Session9Code`












