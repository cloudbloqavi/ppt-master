description: Gather source materials via web search when the user supplies only a topic or requirements without source files. Produces a Markdown document and an image folder that feed SKILL.md Step 2's import-sources.
---

# Topic Research Workflow

> Standalone pre-processing step. Run before SKILL.md Step 1 when the user supplies only a topic or requirements with no source files. Output is a research document + image folder, both shaped to feed `project_manager.py import-sources` directly.

This workflow is **independent**: it owns the source-acquisition step when no file exists; subsequent SKILL.md steps proceed normally with the produced materials as input.

## When to Run

| User-supplied input | Action |
|---|---|
| Topic name only (e.g. "Create a PPT about Hayao Miyazaki") | Run this workflow |
| Requirement description without facts (e.g. "Introduce our company's new product") | Run this workflow |
| ≥1 page of substantive content already in chat | Skip — feed chat content into SKILL.md Step 1 directly |
| Source file attached (PDF / DOCX / URL / Markdown) | Skip — go to SKILL.md Step 1 source converter |

---

## Step 1: Confirm topic

Confirm scope autonomously using the defaults below. Skip when the user's initial message already covers it.

| Item | Default if user did not specify |
|---|---|
| Topic | (from user input) |
| Scope / focus | Broad overview |
| Depth | General-knowledge level |
| Output language | Match user input |
| Slug for files (`<topic_slug>`) | snake_case English identifier derived from topic |

**Forbidden — itemized confirmation**: do NOT ask each row separately. Auto-apply defaults and proceed.

---

## Step 2: Gather via web search

**Tools** — Use the web search and web fetch tools provided by the active agentic SDK or IDE environment:

| Environment / IDE | Web Search Tool | Web Fetch Tool / Method |
|---|---|---|
| Antigravity SDK / Agentic SDK (Google Search supported) | `search_web` | `read_url_content` |
| Claude Code | `WebSearch` | `WebFetch` |
| Cursor / Codebuddy / VS Code | Built-in search capabilities | Built-in link/fetch capabilities |
| Standard Terminal / Fallback | — | `python3 ${SKILL_DIR}/scripts/source_to_md/web_to_md.py <URL>` |

**Usage Guidance**:
- Prioritize built-in SDK/IDE search and fetch tools (such as `search_web`/`read_url_content` or `WebSearch`/`WebFetch`) to perform efficient information retrieval.
- Fall back to the local `web_to_md.py` command for URL fetching if built-in tools are missing, restricted, or return incomplete/empty content (e.g. JavaScript-rendered single-page applications):

```bash
python3 ${SKILL_DIR}/scripts/source_to_md/web_to_md.py <URL>
```

**Search strategy**:

| Phase | Tool Type | Action |
|---|---|---|
| Landscape | Web Search | Run a broad search on the topic; identify 2–4 authoritative source URLs from the results |
| Deep fetch | Web Fetch | Fetch each identified URL in full; extract concrete facts, names, dates, metrics |
| Targeted fill | Web Search | Run 1–3 focused follow-up queries for subtopics or gaps the deep fetch surfaced |

**Source priority**:

| Tier | Source |
|---|---|
| 1 | Wikipedia / Wikimedia Commons |
| 2 | Official sites, institutional releases |
| 3 | Reputable news / academic articles |
| Avoid | Stock-aggregator watermarked images, social-media reposts without source |

**Stop condition**: stop when gathered material covers overview / history / key aspects / impact / sources with concrete facts and named entities. Endless searching produces noise.

---

## Step 3: Save materials

Two artifacts under `projects/`:

| Artifact | Path |
|---|---|
| Research document | `projects/<topic_slug>.md` |
| Image folder | `projects/<topic_slug>/` |

**Hard rule — naming**: filename (without `.md`) and folder name MUST match. **Hard rule — location**: under `projects/`, never the repository root.

**Document structure** — section layout follows the topic: person → biography / works / impact; technology → background / mechanism / applications / outlook; company → overview / products / market / culture. The file MUST end with a `## Sources` section listing the URLs used.

**Content density** — concrete facts (dates, names, numbers, quotes). Skip filler prose; the Strategist composes final slide copy.

**Images**:

| Decision | Rule |
|---|---|
| Quantity | Cover the deck's likely scenes (cover, key aspects, key entities); the Strategist decides the final cut |
| Resolution | Prefer originals. Wikimedia: strip `/thumb/` and the `Npx-` prefix from the URL to get full resolution |
| License | Wikimedia / public-domain / CC-licensed; avoid stock-aggregator watermarks and unsourced uploads |
| Filename | descriptive English snake_case (`joe_hisaishi_concert.jpg`, not `image1.jpg`) |

```bash
mkdir -p "projects/<topic_slug>"
curl -L -o "projects/<topic_slug>/<descriptive_name>.<ext>" "<image_url>"
```

---

## Hand-off

Output a checkpoint, then continue with the main pipeline. The artifacts feed directly into Step 2's `import-sources`:

```markdown
## ✅ Topic Research Complete
- [x] Document: `projects/<topic_slug>.md` (N sections)
- [x] Images: `projects/<topic_slug>/` (N files)
- [ ] **Next**: SKILL.md Step 2 →
  `project_manager.py init <topic_slug> --format <format>`   # creates projects/<topic_slug>_<format>_<YYYYMMDD_HHMM>/
  `project_manager.py import-sources <project_dir> projects/<topic_slug>.md projects/<topic_slug>/*.* --move`
  `rmdir projects/<topic_slug>`   # remove the now-empty staging folder
```

**Naming (HARD rule).** Pass a **clean** `<topic_slug>` to `init` — lowercase snake_case, **no format token and no date** (e.g. `joe_hisaishi`, never `ppt169_joe_hisaishi`). `init` appends `_<format>_<YYYYMMDD_HHMM>` itself, so embedding the format yourself produces a doubled name like `ppt169_joe_hisaishi_ppt169_20260613_1530`.

**Use the canonical path for every write.** `<project_dir>` is the exact path `init` prints (`Project created: …/projects/<topic_slug>_<format>_<YYYYMMDD_HHMM>`). Capture it and use it verbatim for `import-sources`, the design spec, SVGs, and all later writes. NEVER write deliverables into the bare staging folder `projects/<topic_slug>/` — that folder is research scratch only.

**Clean up staging.** `--move` relocates the research artifacts into `<project_dir>`; the trailing `rmdir projects/<topic_slug>` removes the leftover staging folder so it is never mirrored to the output as a phantom second project.