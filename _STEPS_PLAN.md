# Pipeline Steps and Status Logging Mapping

This document provides a reference mapping of the PPT Master agent runner pipeline steps, the corresponding tool actions or script executions, and the clean, user-friendly status progress messages written to the progress logs.

| Pipeline Step | Tool Action / Event | User-Facing Progress Status Message |
| :--- | :--- | :--- |
| **Step 1: Source Content Ingestion** | Run `pdf_to_md.py`, `web_to_md.py`, `ppt_to_md.py`, `doc_to_md.py`, `excel_to_md.py` | `"Converting source document/URL to editable Markdown format..."` |
| | Tool result (Success) | `"Source content successfully converted to editable Markdown."` |
| | Spawning conversion subagent | `"Spawning a parallel subagent to convert and ingest source content..."` |
| **Step 2: Project Init & Import** | Run `project_manager.py init` | `"Initializing new presentation project workspace..."` |
| | Run `project_manager.py import-sources` | `"Importing converted source files and assets into project workspace..."` |
| | Tool result (Success) | `"Project workspace successfully initialized."` |
| **Step 3: Template Integration** | Read/Apply visual brand / layout templates | `"Applying template guidelines and brand presets..."` |
| **Step 4: Design Spec & Spec Lock** | Edit `design_spec.md` | `"Drafting design specification and structural outline..."` |
| | Edit `spec_lock.md` | `"Creating visual parameter lock for page layout construction..."` |
| **Step 5: Image & Math Asset Gen** | Run `image_gen.py` | `"Generating tailored AI images for the presentation slides..."` |
| | Tool result (Success) | `"AI images generated successfully."` |
| | Run `latex_render.py` | `"Rendering LaTeX mathematical equations to high-resolution images..."` |
| | Tool result (Success) | `"LaTeX mathematical formulas rendered successfully."` |
| **Step 6: Executor (Slide Design & Quality)** | Edit `svg_output/<page>.svg` | `"Designing slide {slide_num} of {total_pages} ({filename})..."` |
| | Run `svg_quality_checker.py` | `"Verifying SVG syntax and style rules for generated slides..."` |
| | Tool result (Success) | `"Slide quality check completed successfully: all SVGs verified."` |
| | Tool result (Failure) | `"Slide quality check completed: identified formatting/visual errors that need correction."` |
| | Run `visual_review.py` | `"Rendering visual review previews..."` |
| | Spawning visual-review subagents | `"Spawning a parallel subagent to perform visual review on slides..."` |
| **Step 7: Post-Processing & Export** | Run `total_md_split.py` | `"Aligning and splitting speaker notes to individual slides..."` |
| | Edit/Write `svg_final/<page>.svg` | `"Optimizing styles and embedding icons for slide {slide_num} of {total_pages} ({filename})..."` |
| | Run finalize_svg.py | `"Optimizing slide SVG files and embedding font/icon assets..."` |
| | Tool result (Success) | `"SVG post-processing completed: embedded icons and optimized layout styles."` |
| | Run `svg_to_pptx.py` | `"Assembling and exporting final slides into native PowerPoint format (.pptx)..."` |
| | Tool result (Success) | `"PowerPoint presentation (.pptx) successfully assembled and exported!"` |