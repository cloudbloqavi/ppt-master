---
catalog_id: powerslides_infographics
kind: chart_catalog
summary: Company-preferred collection of 30 in-house infographic, roadmap, matrix, and framework visualization templates.
canvas_format: ppt169
template_count: 30
matched_by: company_index.json
precedence: preferred-over-stock
---

# PowerSlides Infographics - Design Specification

> A rich collection of 30 infographics, timelines, strategic roadmaps, calendars, and frameworks mapped for dynamic scene selection.

---

## I. Template Overview

| Property       | Description                                            |
| -------------- | ------------------------------------------------------ |
| **Template Name** | powerslides_infographics                            |
| **Use Cases**  | Business presentations, project reports, comparisons, matrices, flows, roadmaps, organizational cascades, calendars |
| **Design Tone** | Clean, structured, corporate, data-driven, clear hierarchy |
| **Theme Mode** | Light theme (white background, colors decided dynamically) |

---

## II. Canvas Specification

| Property       | Value                         |
| -------------- | ----------------------------- |
| **Format**     | Standard 16:9                 |
| **Dimensions** | 1280 × 720 px                |
| **viewBox**    | `0 0 1280 720`                |

---

## III. Page Types and SVG Page Roster

### 3. Process / Step Flow Page (`03_process_flow.svg`)
- **Role**: content
- **Description**: Linear sequence of 3-7 numbered steps.
- **Match criteria**: Pick for processes, linear steps, workflows, deployment phases.

### 4. Timeline / Roadmap Page (`04_timeline.svg`)
- **Role**: content
- **Description**: Horizontal time axis with milestone markers.
- **Match criteria**: Pick for milestones, roadmaps, timeline events.

### 5. Comparison / Versus Page (`05_comparison.svg`)
- **Role**: content
- **Description**: Side-by-side columns comparing Option A and Option B across consistent attributes.
- **Match criteria**: Pick for pros/cons, two-option comparison, relative evaluations.

### 6. Segmented Pyramid / Hierarchy Page (`06_segmented_pyramid.svg`)
- **Role**: content
- **Description**: Upright **segmented pyramid** hierarchy (narrow apex → wide base) built from **inverted-trapezoid tiers** — each tier is a trapezoid wider at its top than its bottom, leaving chevron notches between tiers. This boat/inverted-trapezoid tier styling is a deliberate design choice, NOT a rendering defect; the overall silhouette still tapers correctly. Do not "correct" the trapezoid tier orientation.
- **Match criteria**: Pick for ranking, stratification, layer definitions, maturity models.

### 7. Cycle / Circular Flow Page (`07_cycle.svg`)
- **Role**: content
- **Description**: Closed loop circular sequence (PDCA, Attract-Engage-Delight).
- **Match criteria**: Pick for iterative steps, flywheels, continuous loops, feedback cycles.

### 8. 2x2 Matrix Page (`08_matrix_2x2.svg`)
- **Role**: content
- **Description**: 2x2 grid sorting items across two axes (High/Low).
- **Match criteria**: Pick for SWOT, BCG, prioritizing items based on two independent values.

### 9. Pillars / Pillar Diagram Page (`09_pillars.svg`)
- **Role**: content
- **Description**: Foundation and columns showing vertical strategy pillars.
- **Match criteria**: Pick for core strategic pillars, corporate tenets, organizational foundations.

### 10. Funnel Page (`10_funnel.svg`)
- **Role**: content
- **Description**: Conversion stages highlighting progressive drop-off count and rate.
- **Match criteria**: Pick for conversion funnels, sales pipelines, monotonic stage loss.

### 11. Org Chart / Tree Diagram Page (`11_org_tree.svg`)
- **Role**: content
- **Description**: Node-hierarchy representing parent-child relationships.
- **Match criteria**: Pick for org charts, OKR cascades, work breakdown structures (WBS).

### 12. Venn Diagram Page (`12_venn.svg`)
- **Role**: content
- **Description**: Overlapping circles illustrating intersections and set differences.
- **Match criteria**: Pick for set overlays, relationships, core overlapping areas.

### 13. Statistical / KPI Highlight Page (`13_kpi_highlight.svg`)
- **Role**: content
- **Description**: High-impact statistic cards showing numbers and direction metrics.
- **Match criteria**: Pick for financial summary, performance KPI summary, key metrics dashboard.

### 14. Gantt Chart / Project Plan Page (`14_gantt.svg`)
- **Role**: content
- **Description**: Tasks mapped across horizontal ranges grouped by swimlanes.
- **Match criteria**: Pick for project plans, tasks schedules with durations and phases.

### 15. Mind Map / Radial Diagram Page (`15_mind_map.svg`)
- **Role**: content
- **Description**: Core hub radiating outward to branch details.
- **Match criteria**: Pick for brainstorm concepts, product modules, non-linear categories.

### 16. Geographic / Map Infographic Page (`16_geo_map.svg`)
- **Role**: content
- **Description**: Spatial coordinate map with legend values.
- **Match criteria**: Pick for geographic regions, local office locations, global scale maps.

### 17. Waterfall / Bridge Chart Page (`17_waterfall.svg`)
- **Role**: content
- **Description**: Stepwise changes starting from initial state and ending at final total.
- **Match criteria**: Pick for budget allocations, additive/subtractive financial variances.

### 18. SWOT Analysis Page (`18_swot.svg`)
- **Role**: content
- **Description**: 4 quadrants presenting Strengths, Weaknesses, Opportunities, Threats.
- **Match criteria**: Pick for SWOT matrices, internal/external positive/negative assessments.

### 19. Fishbone / Ishikawa Diagram Page (`19_fishbone.svg`)
- **Role**: content
- **Description**: Cause-and-effect bone diagram mapping causes to a problem statement.
- **Match criteria**: Pick for root cause analysis, Ishikawa diagrams, quality assessments.

### 20. Gauge / Speedometer Page (`20_gauge.svg`)
- **Role**: content
- **Description**: Dial gauge highlighting percentage goal achievement rate.
- **Match criteria**: Pick for single KPI performance, goal indicator, speedometer metrics.

### 21. Heat Map Page (`21_heat_map.svg`)
- **Role**: content
- **Description**: Grid table depicting value intensities across column and row headers.
- **Match criteria**: Pick for risk matrices, monthly activity matrices, cohort retentions.

### 22. Sankey / Flow Diagram Page (`22_sankey.svg`)
- **Role**: content
- **Description**: Flow diagram depicting magnitudes branching from sources to targets.
- **Match criteria**: Pick for resource flows, energy distributions, complex source-sink mapping.

### 23. Quarterly Product Roadmap (`23_quarterly_product_roadmap.svg`)
- **Role**: content
- **Description**: A 4-quarter roadmap (Q1-Q4) grouped by streams or focus areas.
- **Match criteria**: Pick for quarterly product roadmaps, phased program maps, streams milestones.

### 24. Monthly Strategic Roadmap (`24_monthly_strategic_roadmap.svg`)
- **Role**: content
- **Description**: Detailed phased roadmap showing monthly activities and outcomes mapped to phases.
- **Match criteria**: Pick for short-term strategic execution, monthly actions and deliverables maps.

### 25. Yearly Strategic Goals Roadmap (`25_yearly_strategic_goals_roadmap.svg`)
- **Role**: content
- **Description**: Maps multiple strategic goals to specific milestone years or targets.
- **Match criteria**: Pick for high-level annual goal targets, multi-year objectives roadmap.

### 26. Annual Roles and Targets Roadmap (`26_annual_roles_targets_roadmap.svg`)
- **Role**: content
- **Description**: A multi-year strategic roadmap organized by core execution pillars (roles, action plans, targets).
- **Match criteria**: Pick for structural annual program alignment, team roles and metrics roadmaps.

### 27. Three-Year Project Lifecycle (`27_three_year_project_lifecycle.svg`)
- **Role**: content
- **Description**: A 3-year project lifecycle roadmap mapping major phases (e.g. Planning, Execution, Monitoring).
- **Match criteria**: Pick for 3-year lifecycles, project lifecycle stages, multi-year phase tracks.

### 28. Monthly Marketing Calendar (`28_monthly_marketing_calendar.svg`)
- **Role**: content
- **Description**: A monthly calendar grid view showing campaign events or social schedules.
- **Match criteria**: Pick for calendar events, editorial scheduling, monthly sprint planners.

### 29. Cross-Functional Status Board (`29_cross_functional_status_board.svg`)
- **Role**: content
- **Description**: A 4-column status board, task tracker, or Kanban board layout.
- **Match criteria**: Pick for project boards, task tracking columns, Kanban flows, cross-functional status.

### 30. Marketing Milestones Matrix (`30_marketing_milestones_matrix.svg`)
- **Role**: content
- **Description**: A 3x3 matrix layout or 9-step grid grouped under 3 categories.
- **Match criteria**: Pick for 9-item grids, grouped marketing milestone cards, 3x3 framework matrices.

### 31. Maturity Transformation Roadmap (`31_maturity_transformation_roadmap.svg`)
- **Role**: content
- **Description**: A 4-stage maturity curve, capability growth progression, or strategic transformation roadmap.
- **Match criteria**: Pick for maturity progressions, transformation curves, evolution roadmap.

### 32. Multi-Year Growth Strategy (`32_multi_year_growth_strategy.svg`)
- **Role**: content
- **Description**: A 5-year or 5-phase growth strategy roadmap with stacked key objectives.
- **Match criteria**: Pick for long-term growth, 5-year strategies, stacked strategic projections.

---

## IV. SVG Page Roster File List

| File | Role | Description |
|------|------|-------------|
| `03_process_flow.svg` | content | Process / Step Flow Page |
| `04_timeline.svg` | content | Timeline / Roadmap Page |
| `05_comparison.svg` | content | Comparison / Versus Page |
| `06_segmented_pyramid.svg` | content | Segmented Pyramid / Hierarchy Page (inverted-trapezoid tiers) |
| `07_cycle.svg` | content | Cycle / Circular Flow Page |
| `08_matrix_2x2.svg` | content | 2x2 Matrix Page |
| `09_pillars.svg` | content | Pillars / Pillar Diagram Page |
| `10_funnel.svg` | content | Funnel Page |
| `11_org_tree.svg` | content | Org Chart / Tree Diagram Page |
| `12_venn.svg` | content | Venn Diagram Page |
| `13_kpi_highlight.svg` | content | Statistical / KPI Highlight Page |
| `14_gantt.svg` | content | Gantt Chart / Project Plan Page |
| `15_mind_map.svg` | content | Mind Map / Radial Diagram Page |
| `16_geo_map.svg` | content | Geographic / Map Infographic Page |
| `17_waterfall.svg` | content | Waterfall / Bridge Chart Page |
| `18_swot.svg` | content | SWOT Analysis Page |
| `19_fishbone.svg` | content | Fishbone / Ishikawa Diagram Page |
| `20_gauge.svg` | content | Gauge / Speedometer Page |
| `21_heat_map.svg` | content | Heat Map Page |
| `22_sankey.svg` | content | Sankey / Flow Diagram Page |
| `23_quarterly_product_roadmap.svg` | content | Quarterly Product Roadmap |
| `24_monthly_strategic_roadmap.svg` | content | Monthly Strategic Roadmap |
| `25_yearly_strategic_goals_roadmap.svg` | content | Yearly Strategic Goals Roadmap |
| `26_annual_roles_targets_roadmap.svg` | content | Annual Roles and Targets Roadmap |
| `27_three_year_project_lifecycle.svg` | content | Three-Year Project Lifecycle |
| `28_monthly_marketing_calendar.svg` | content | Monthly Marketing Calendar |
| `29_cross_functional_status_board.svg` | content | Cross-Functional Status Board |
| `30_marketing_milestones_matrix.svg` | content | Marketing Milestones Matrix |
| `31_maturity_transformation_roadmap.svg` | content | Maturity Transformation Roadmap |
| `32_multi_year_growth_strategy.svg` | content | Multi-Year Growth Strategy |

---

## V. Usage Instructions

This is a **company-preferred visualization catalog**, not an opt-in layout. No explicit folder path is required in the prompt — it is consulted automatically on every run.

1. During the Strategist phase (§VII visualization matching), each page's content shape is matched against [`company_index.json`](./company_index.json) **first**, before the stock `charts/charts_index.json`.
2. When a company entry's `Pick for …` clause fits a page, that infographic is selected (its path recorded in design-spec §VII) and the stock catalog is skipped for that page — the company variant wins on ties.
3. Pages with **no** company match fall through to the stock chart catalog, then to the standard fallback chain (table layout / AI-generated image / custom layout).
