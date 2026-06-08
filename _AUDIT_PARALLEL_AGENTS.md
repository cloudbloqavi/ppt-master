# Audit Report: Parallelizing the PPT Generation Workflow via Subagents

This report provides a detailed audit of the **PPT Master** generation workflow within this codebase. It analyzes the current execution model implemented in [run_agent.py](file:///c:/Users/aviji/repo/ai-builder-engine/run_agent.py) and identifies specific tasks that can be parallelized using subagents under the **Google Antigravity SDK**, while respecting the constraints defined in [SKILL.md](file:///c:/Users/aviji/repo/ai-builder-engine/core-ppt-master-engine/skills/ppt-master/SKILL.md).

---

## 1. Current Architecture & Bottlenecks

Currently, [run_agent.py](file:///c:/Users/aviji/repo/ai-builder-engine/run_agent.py) orchestrates execution by launching a single **Antigravity SDK Agent** running in a sequential loop:
- The agent interprets instructions and executes various pipeline scripts (e.g., `latex_render.py`, `image_gen.py`, `svg_quality_checker.py`, `finalize_svg.py`) as command-line tools.
- Tasks are completed one by one in a serial sequence.
- **Main Bottleneck**: For decks with many slides, long content inputs, or numerous image assets, the single-agent pipeline experiences high latency. In addition, the main agent suffers from context window compression (drift) as it processes more steps.

---

## 2. Step-by-Step Parallelization Audit

Below is a detailed analysis of each stage of the PPT generation pipeline and its suitability for parallel execution via subagents.

### Step 1: Source Content Processing
* **Current State**: If the user provides multiple source files (e.g., three PDFs, an Excel sheet, and web links), the main agent processes them sequentially by running the corresponding script (e.g., `pdf_to_md.py`) one by one.
* **Parallelization Opportunity**: **High (via Subagents)**
* **Implementation**: The main agent can spawn parallel subagents for each source document/link. 
  - Each subagent is tasked with running the script, reading the output, cleaning up noise, and extracting key data (tables, statistics, core arguments) into a standard Markdown format.
  - The subagents run concurrently, and their summaries are returned to the main agent.
* **Benefits**: Significantly reduces wall-clock time for multi-source decks and keeps the main agent’s context clean.

### Steps 2 & 3: Project Init & Template Option
* **Current State**: Very fast and lightweight operations (directory creation, template folder copies).
* **Parallelization Opportunity**: **None (Keep Sequential)**
* **Why**: The overhead of spawning subagents far outweighs the execution time, which takes milliseconds.

### Step 4: Strategist Phase (Planning & Outline)
* **Current State**: The main agent drafts the entire `design_spec.md` and slide-by-slide content outlines sequentially.
* **Parallelization Opportunity**: **Medium (via Subagents for Section Detailing)**
* **Implementation**: 
  - The main Strategist agent establishes the global presentation narrative, slide count, and section divisions.
  - Once the high-level roadmap is set, the main agent can spawn parallel subagents to detail slide contents for each section (e.g., *Subagent A* handles Slides 1–5, *Subagent B* handles Slides 6–10, etc.).
  - Each subagent refines the layout selection, bullet points, and speaker notes for its assigned slides.
  - The main agent aggregates these inputs back into the master outline and `spec_lock.md`.
* **Benefits**: Avoids context window decay during outline creation for large decks (e.g., 20+ slides) and allows richer, more descriptive content planning.

### Step 5: Image Acquisition Phase
* **Current State**: 
  - While `image_gen.py` uses a thread pool to dispatch API calls concurrently, the creation of prompts and the selection of web search keywords are done sequentially.
  - If web image search is used, downloading and verifying results happens in a sequential loop.
* **Parallelization Opportunity**: **High (via Subagents)**
* **Implementation**: 
  - The main agent spawns parallel subagents for each pending image row in the resource list.
  - Each subagent handles the prompt generation, calls the image backend, runs a visual quality check (evaluating style, colors, alignment with the brand guidelines), and automatically regenerates/refines the prompt if the result is suboptimal.
* **Benefits**: Parallelizes the LLM-heavy prompt-refining loops, ensuring that all assets are generated and quality-verified concurrently.

### Step 6: Executor Phase (SVG Page Generation)
* **Current State**: Pages are generated page-by-page in a sequential pass by the main agent.
* **Parallelization Opportunity**: 🚫 **PROHIBITED BY ARCHITECTURE**
* **Why**: The workflow enforces a strict sequential gate on SVG generation. 
  - **Rule 6** (`NO SUB-AGENT SVG GENERATION`) and **Rule 7** (`SEQUENTIAL PAGE GENERATION ONLY`) explicitly forbid parallelizing page generation.
  - *Rationale*: Visual continuity, design rhythm, and contextual slide transitions depend on the agent having the context of all previously generated slides in its history. Splitting slide generation across parallel subagents results in visual drift, layout repetition, and a lack of narrative cohesiveness.

### Step 6 (Auxiliary): Visual Review & Self-Correction
* **Current State**: The `visual-review.md` workflow outlines a team structure where an orchestrator spawns subagents in parallel to check slide batches. However, in non-Claude platforms, this defaults to serial execution.
* **Parallelization Opportunity**: **Very High (via Subagents)**
* **Implementation**:
  - The main agent partitions the $N$ generated pages into batches of $K$ slides (e.g., $K=5$).
  - It spawns a subagent per batch in parallel.
  - Each subagent reviews the slide PNGs, checks them against the design rubric, makes layout adjustments directly in the SVGs, and returns the status.
* **Benefits**: Drastically cuts visual verification time (e.g., a 20-slide review drops from ~5 minutes to less than 1 minute).

---

## 3. Implementation Plan: Native Subagent Execution in Antigravity SDK

Instead of writing a custom Python orchestrator script using `asyncio.gather` and importing the `google.antigravity` classes directly, we can leverage the built-in subagents capability of the Antigravity SDK. 

Under the Antigravity framework, when the main agent reaches a parallelizable step (such as Step 1: Source Ingestion, Step 5: Image Generation, or Step 6: Visual Review), it can invoke parallel subagents of type `self` (clones of itself) using the native `invoke_subagent` tool:

### Spawning Parallel Self-Reviewers via Tool Calls
To perform a parallel visual review, the main agent partitions the slide list into batches and issues concurrent tool calls to spawn subagents:

```json
// Tool Call: invoke_subagent for Batch 1 (Slides 01 to 05)
{
  "subagent_type": "self",
  "task": "Review slides 01 to 05 visually. Pre-rendered PNG previews are at .preview/ and SVGs are in svg_output/. For each slide: 1) Read SVG; 2) Inspect PNG using view_image; 3) Check against the Visual Review Rubric; 4) Back up slide SVG first to .review/backup/<page>.iter1.svg and save any fixes; 5) Write JSON findings report to .review/<page>.json.",
  "wait_for_completion": false
}
```

By calling `invoke_subagent` for each batch with `"wait_for_completion": false`, the subagents execute asynchronously in the background. The main agent can monitor their execution status and automatically receives their reports when they transition back to `Idle`.

This keeps the codebase clean, avoids scripting overhead, and leverages the IDE's built-in subagent management panel.

---

## 4. Key Recommendations & Tradeoffs

| Opportunity | Feasibility | Recommendation | Complexity | Tradeoff |
| :--- | :--- | :--- | :--- | :--- |
| **Source Processing (Step 1)** | High | **Implement** for cases with $\ge 3$ sources. | Low | Spawns multiple API calls; slight increase in token cost for initial ingestion. |
| **Section Content Detailing (Step 4)** | Medium | **Implement** only for large decks ($\ge 15$ slides). | Medium | Requires strict prompt boundaries so subagents don't duplicate slide ideas. |
| **Image Generation & Quality Verification (Step 5)** | High | **Highly Recommended**. | Medium | Maximizes speed of image creation and verification. |
| **SVG Generation (Step 6)** | Low | 🚫 **Do Not Implement**. | N/A | Forbidden by `SKILL.md` rules to prevent visual drift. |
| **Visual Review (Auxiliary Workflow)** | High | **Highly Recommended**. | Low | Requires Playwright for rendering, but fits the existing rubric structure perfectly. |

### Immediate Actions
1. **Visual Review Parallelization**: Modify the `visual-review` workflow script to programmatically dispatch parallel visual check subagents using `asyncio.gather` under the Antigravity SDK.
2. **Step 5 Prompt/Search Parallelization**: Update the image acquisition flow to spawn subagents to write and verify prompts concurrently rather than relying on a serial loop inside the main agent's mind.