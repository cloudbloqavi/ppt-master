#!/usr/bin/env python3
"""
svg_doctor -lint (and optionally auto-fix) a single SVG for PPTX-workflow safety.

Unlike ``svg_layout_auditor.py`` / ``svg_quality_checker.py`` (which are
project-scoped and need spec_lock context), this works on ONE standalone .svg
file with no project around it -handy for vetting a hand-authored slide, or for
sweeping the chart catalog (``powerslides_infographics/*.svg``) to find fragile
templates before they ship into a deck.

Two modes, by design (see the project discussion on deterministic vs AI fixes):

  python3 svg_doctor.py <file.svg>            # REVIEW: list findings, change nothing
  python3 svg_doctor.py <file.svg> --fix      # FIX:    apply the AUTO-FIXABLE ones in place
  python3 svg_doctor.py <file.svg> --fix -o out.svg   # write fixed copy elsewhere
  python3 svg_doctor.py <file.svg> --json     # machine-readable findings
  python3 svg_doctor.py <file.svg> --ingest   # SANITIZE: untrusted-file gate (see below)
  python3 svg_doctor.py <file.svg> --report r.md      # write a shareable Markdown report

INGESTION / SANITIZATION (untrusted third-party SVGs): when a company hands us an
SVG to add to the catalog, the real risk is not the PPTX profile but *active and
external* content — inline event handlers (``onload=``…), ``javascript:`` URLs,
externally-fetched ``<image>``/``<use href=http…>``, ``data:`` blobs, and DTDs
(``<!DOCTYPE>``/``<!ENTITY>`` → XXE). ``svg_doctor`` always scans for these; the
``--ingest`` flag turns the scan into a *gate*: it fails (exit 1) if ANY such
construct was present — even one that was auto-stripped — so a human signs off
before the asset enters the codebase. Two postures (per the invariant below):
strip-safe constructs that paint nothing (handlers, ``javascript:`` URLs) are
AUTO-FIXED; ones whose removal would change the render (external refs, ``data:``)
or need a security call (DTD) are REVIEW — reported, never silently altered, and
they block the gate until resolved. ``--report PATH`` writes a human-readable
Markdown report (verdict + grouped findings + next steps) to share with eng/UX;
with ``--ingest`` and no ``--report`` the report defaults to this tool's own
``svg_doctor/reports/`` folder (never beside the input SVG), so a catalog sweep
never litters the template folders.

VISUAL-PRESERVING INVARIANT (hard rule): --fix must NEVER change how the SVG
renders. It only repairs internal issues that break the PPTX workflow while
leaving the visible asset pixel-identical. Any repair that could alter appearance
(dropping an alpha channel, deleting a <style>/<foreignObject> that paints
something, removing a class that CSS targets) is therefore NOT auto-applied -- it
is reported as REVIEW so a human/AI can fix it while preserving the look.

Findings are split into two classes:

  * AUTO-FIX  -- repairs that are provably visual no-ops: add missing xmlns/viewBox,
    HTML named entity -> identical Unicode glyph, unescaped '&' -> '&amp;' (renders
    the same), rgba() -> hex PLUS a matching -opacity attribute so the alpha is
    preserved, and stripping non-rendering <script>/<iframe>. --fix rewrites only
    these. AI adds nothing here.
  * REVIEW    -- either an aesthetic/intent issue (mirrored geometry, raw-export
    bloat, out-of-bounds) OR a workflow-breaker whose safe fix is NOT visually
    neutral (<style>/<foreignObject>/<animate>, class attrs, rgba inside style="").
    The tool DESCRIBES these precisely but never auto-edits them.

--fix never touches a REVIEW finding, so it can neither break a slide nor silently
change its appearance.

Exit code: 0 if no findings (or all auto-fixable were fixed and nothing remains
in REVIEW); 1 if REVIEW findings remain. Use in CI to gate the catalog.

The banned-construct list mirrors ``templates/spec_lock_reference.md`` (## forbidden)
and ``references/shared-standards.md`` §1.0 -keep them in sync.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

# ── Canonical forbidden constructs (mirror spec_lock_reference.md ## forbidden) ──
# Banned AND non-rendering: removing them cannot change the visible asset, so they
# are safe to strip on --fix.
_STRIP_ELEMENTS = ("script", "iframe")
# Banned but they (or their removal) DO affect rendering: <style>/<foreignObject>
# paint things; <animate*>/<set> drive visible state. Stripping them could change
# appearance, so per the visual-preserving invariant these are REVIEW-only (a human
# or AI must inline/replace them while keeping the look).
_FLAG_ELEMENTS = ("style", "foreignObject",
                  "animate", "animateTransform", "animateMotion", "animateColor", "set")
# Color attributes whose rgba() value can be losslessly split into hex + *-opacity.
_COLOR_ATTRS = ("fill", "stroke", "stop-color", "flood-color", "lighting-color")
# HTML named entities → raw Unicode (write raw per shared-standards §1.0).
_HTML_ENTITIES = {
    "&nbsp;": " ", "&mdash;": "—", "&ndash;": "–", "&copy;": "©",
    "&reg;": "®", "&hellip;": "…", "&bull;": "•", "&trade;": "™",
    "&deg;": "°", "&times;": "×", "&middot;": "·", "&laquo;": "«",
    "&raquo;": "»", "&ldquo;": "“", "&rdquo;": "”", "&lsquo;": "‘",
    "&rsquo;": "’", "&euro;": "€", "&pound;": "£", "&sect;": "§",
}
# XML entities that are legal and must be preserved (never treated as "stray &").
_LEGAL_XML_ENTITY = re.compile(r"&(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);")
_RAW_MARKERS = ("filter", "feGaussianBlur", "feColorMatrix", "feOffset", "feFlood", "feBlend")
# A standalone SVG over this size is treated as a raw PowerPoint export even with no
# filter primitives (mirrors retheme_enforcement._RAW_BYTES / lint_chart_catalog).
_RAW_BYTES = 20_000

# ── Untrusted-SVG sanitization (the ingestion gate) ──────────────────────────
# When a third party hands us an SVG, the real attack surface is active/external
# content, not the PPTX profile. These mirror the well-known SVG threat list and
# split along the SAME visual-preserving invariant used everywhere else:
#   * strip-safe (AUTO-FIX): the construct paints nothing, so removing it is a
#     guaranteed visual no-op — inline event handlers, javascript: URLs.
#   * not strip-safe (REVIEW): removal WOULD change the render (external
#     <image>/<use>, data: blobs) or it needs a human security call (a DTD →
#     XXE / billion-laughs). Reported precisely, never silently altered; these
#     block the --ingest gate until a human resolves them.
# Namespaces (xmlns="http://www.w3.org/2000/svg") are NOT references and are not
# matched — only real fetch attributes (href / xlink:href / src) and url(http…).
_EVENT_HANDLER_RE = re.compile(r"""\son[a-zA-Z]+\s*=\s*("[^"]*"|'[^']*')""")
_JS_URL_ATTR_RE = re.compile(
    r"""\s(?:xlink:href|href|src)\s*=\s*("[^"]*javascript:[^"]*"|'[^']*javascript:[^']*')""",
    re.I)
_EXTERNAL_REF_RE = re.compile(r"""(?:xlink:href|href|src)\s*=\s*["']\s*https?://""", re.I)
_EXTERNAL_URL_FUNC_RE = re.compile(r"""url\(\s*['"]?\s*https?://""", re.I)
_DATA_URI_RE = re.compile(r"""(?:xlink:href|href|src)\s*=\s*["']\s*data:""", re.I)
_DOCTYPE_RE = re.compile(r"<!DOCTYPE", re.I)
_ENTITY_RE = re.compile(r"<!ENTITY", re.I)


class Finding:
    __slots__ = ("cls", "code", "severity", "message", "count")

    def __init__(self, cls: str, code: str, severity: str, message: str, count: int = 1):
        self.cls = cls            # "autofix" | "review"
        self.code = code
        self.severity = severity  # "error" | "warning"
        self.message = message
        self.count = count

    def as_dict(self) -> dict:
        return {"class": self.cls, "code": self.code, "severity": self.severity,
                "message": self.message, "count": self.count}


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse(text: str):
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        return None


# ── REVIEW detectors (never auto-fixed) ──────────────────────────────────────
def _detect_review(text: str, root) -> list[Finding]:
    out: list[Finding] = []
    if root is None:
        out.append(Finding("review", "parse_error", "error",
                           "SVG is not well-formed XML - cannot parse (this alone will break the workflow)."))
        return out

    # Banned but visually-significant elements: flagged, NOT stripped, because
    # removing them would change the rendered asset (violating the visual-preserving
    # invariant). The safe fix is to inline/replace them while keeping the look.
    for tag in _FLAG_ELEMENTS:
        n = len(re.findall(rf"<{tag}\b", text))
        if n:
            out.append(Finding("review", f"banned_{tag}", "error",
                               f"{n} <{tag}> element(s) - banned in the PPTX SVG profile, but removing them "
                               "may change appearance; inline/replace manually (not auto-fixed)."))
    nclass = len(re.findall(r'\sclass="[^"]*"', text))
    if nclass:
        out.append(Finding("review", "class_attr", "warning",
                           f"{nclass} class attribute(s) - CSS is unsupported in the profile; if a <style> "
                           "targets them, inline the styles as presentation attributes (not auto-removed)."))
    # rgba() inside a style="..." attribute can't be losslessly rewritten by the
    # attribute-level fixer, so flag rather than risk a visual change.
    style_rgba = sum(len(re.findall(r"rgba?\(", m.group(1)))
                     for m in re.finditer(r'style="([^"]*)"', text))
    if style_rgba:
        out.append(Finding("review", "rgba_in_style", "warning",
                           f"{style_rgba} rgba()/rgb() inside style=\"...\" - convert to hex + *-opacity "
                           "manually to preserve appearance (not auto-fixed)."))

    # Raw PowerPoint export fingerprint — computed first because it changes how a
    # mirrored transform is judged (expected in a raw export vs. a bug in a clean one).
    raw = sum(1 for _, el in ((_strip_ns(e.tag), e) for e in root.iter())
              if _strip_ns(el.tag) in _RAW_MARKERS)
    n_elems = sum(1 for _ in root.iter())
    # Canonical raw-export fingerprint (matches retheme_enforcement / lint_chart_catalog):
    # filter primitives in a heavy tree, OR a file over ~20 KB. The size arm catches
    # huge-but-filterless exports (e.g. 16_geo_map) the marker arm alone would miss.
    is_raw_export = bool((raw and n_elems > 300) or len(text) > _RAW_BYTES)

    # Mirrored / inverted geometry: matrix(a b c d e f) with negative x/y scale,
    # or scale() with a negative factor. In a clean hand-authored SVG this is the
    # pyramid-inversion bug (REVIEW — re-orient the paths). In a RAW PowerPoint
    # export, vertical flips are how PowerPoint emits geometry and the DrawingML
    # exporter reproduces them at full fidelity, so it is expected → INFO, not a gate.
    flips = 0
    for el in root.iter():
        tr = el.get("transform", "")
        for m in re.finditer(r"matrix\(\s*([-\d.eE]+)[ ,]+[-\d.eE]+[ ,]+[-\d.eE]+[ ,]+([-\d.eE]+)", tr):
            try:
                a, d = float(m.group(1)), float(m.group(2))
                if a < 0 or d < 0:
                    flips += 1
            except ValueError:
                pass
        if re.search(r"scale\(\s*-|,\s*-", tr) and "scale(" in tr:
            flips += 1
    if flips:
        if is_raw_export:
            out.append(Finding("info", "mirrored_transform", "warning",
                               f"{flips} element(s) use a mirrored/flipped transform inside a raw export — "
                               "expected (PowerPoint emits vertical flips; the exporter reproduces them "
                               "faithfully). Informational: does not block ingestion.", flips))
        else:
            out.append(Finding("review", "mirrored_transform", "warning",
                               f"{flips} element(s) use a mirrored/flipped transform "
                               "(matrix with negative scale or scale(-...)). Verify orientation -"
                               "this is the pyramid-inversion class of bug; fix by re-orienting paths, "
                               "not by blind removal.", flips))

    if is_raw_export:
        out.append(Finding("info", "raw_export", "warning",
                           f"Looks like a raw PowerPoint export ({raw} filter primitive(s), {n_elems} "
                           f"elements, {len(text):,} bytes). This is an ACCEPTED class — the runner copies "
                           "such a template verbatim and re-themes it deterministically "
                           "(retheme_enforcement.py); it is NOT redrawn. Informational: does not block "
                           "ingestion.", raw))

    # Out-of-bounds geometry vs the canvas (viewBox or width/height).
    vb = root.get("viewBox")
    W = H = None
    if vb:
        parts = re.split(r"[ ,]+", vb.strip())
        if len(parts) == 4:
            try:
                W, H = float(parts[2]), float(parts[3])
            except ValueError:
                pass
    if W is None:
        try:
            W = float(re.sub(r"[^\d.]", "", root.get("width", "")) or 0) or None
            H = float(re.sub(r"[^\d.]", "", root.get("height", "")) or 0) or None
        except ValueError:
            pass
    if W and H:
        oob = 0
        tol = 5.0
        for el in root.iter():
            tag = _strip_ns(el.tag)
            try:
                if tag in ("rect", "image"):
                    x, y = float(el.get("x", 0)), float(el.get("y", 0))
                    w, h = float(el.get("width", 0)), float(el.get("height", 0))
                    if x < -tol or y < -tol or x + w > W + tol or y + h > H + tol:
                        oob += 1
                elif tag == "circle":
                    cx, cy, r = float(el.get("cx", 0)), float(el.get("cy", 0)), float(el.get("r", 0))
                    if cx - r < -tol or cy - r < -tol or cx + r > W + tol or cy + r > H + tol:
                        oob += 1
            except (ValueError, TypeError):
                pass
        if oob:
            # On a raw export this is an intrinsic property we accept verbatim → INFO;
            # on a clean SVG it is a real placement bug → REVIEW.
            out.append(Finding("info" if is_raw_export else "review", "out_of_bounds", "warning",
                               f"{oob} element(s) extend outside the {int(W)}x{int(H)} canvas "
                               "(clipped in the deck). In-project, svg_layout_auditor auto-clamps these.", oob))

    # Orphan baseline: multi-line text whose first line sits at y=0 (the recurring
    # overlap bug). Reported, not auto-fixed here (the in-project auditor owns the fix).
    orphan = 0
    for el in root.iter():
        if _strip_ns(el.tag) == "text" and el.get("y", "").strip() in ("0", "0.0"):
            tr = el.get("transform", "")
            if "translate(" not in tr or re.search(r"translate\(\s*[-\d.]+\s*[ ,]\s*0\s*\)", tr):
                orphan += 1
    if orphan:
        out.append(Finding("info" if is_raw_export else "review", "orphan_baseline", "warning",
                           f"{orphan} text element(s) appear to render from y=0 (orphan baseline) -"
                           "the recurring overlap cause; verify vertical placement.", orphan))

    if n_elems > 1500:
        # Heavy is expected for a raw export (accepted verbatim) but a red flag in a
        # clean hand-authored SVG.
        out.append(Finding("info" if is_raw_export else "review", "heavy_svg", "warning",
                           f"Very heavy SVG ({n_elems} elements) -large/slow PPTX export.", n_elems))
    return out


# ── AUTO-FIX detectors + fixers (text-level, formatting-preserving) ───────────
def _detect_and_fix(text: str, do_fix: bool) -> tuple[str, list[Finding]]:
    out: list[Finding] = []

    # Missing root xmlns.
    if re.search(r"<svg\b", text) and 'xmlns="http://www.w3.org/2000/svg"' not in text:
        out.append(Finding("autofix", "missing_xmlns", "error", "Root <svg> missing xmlns declaration."))
        if do_fix:
            text = re.sub(r"<svg\b", '<svg xmlns="http://www.w3.org/2000/svg"', text, count=1)

    # Missing viewBox (add from width/height when present).
    msvg = re.search(r"<svg\b[^>]*>", text)
    if msvg and "viewBox" not in msvg.group(0):
        wm = re.search(r'width="(\d+(?:\.\d+)?)', msvg.group(0))
        hm = re.search(r'height="(\d+(?:\.\d+)?)', msvg.group(0))
        out.append(Finding("autofix", "missing_viewbox", "warning",
                           "Root <svg> has no viewBox" + (" (derivable from width/height)." if wm and hm
                                                          else " and no width/height to derive it from.")))
        if do_fix and wm and hm:
            new = msvg.group(0).replace("<svg", f'<svg viewBox="0 0 {wm.group(1)} {hm.group(1)}"', 1)
            text = text.replace(msvg.group(0), new, 1)

    # Banned NON-rendering elements → strip (paired and self-closing forms). Only
    # <script>/<iframe>: they paint nothing, so removal is a guaranteed visual no-op.
    # Visually-significant banned tags (<style>/<foreignObject>/<animate*>) are
    # REVIEW-only (see _detect_review) to honor the visual-preserving invariant.
    for tag in _STRIP_ELEMENTS:
        paired = re.compile(rf"<{tag}\b[^>]*>.*?</{tag}>", re.DOTALL)
        selfc = re.compile(rf"<{tag}\b[^>]*/>", re.DOTALL)
        n = len(paired.findall(text)) + len(selfc.findall(text))
        if n:
            out.append(Finding("autofix", f"banned_{tag}", "error",
                               f"{n} <{tag}> element(s) - banned and non-rendering; stripped.", n))
            if do_fix:
                text = paired.sub("", text)
                text = selfc.sub("", text)

    # rgba()/rgb() in a color attribute → hex + matching *-opacity, so the alpha is
    # PRESERVED (visual no-op). rgba() inside style="..." is handled as REVIEW.
    rgba_fixed = 0

    def _split_rgba(m):
        nonlocal rgba_fixed
        attr, val = m.group(1), m.group(2)
        nums = re.findall(r"[\d.]+", val)
        if len(nums) < 3:
            return m.group(0)
        r, g, b = (max(0, min(255, int(round(float(nums[i]))))) for i in range(3))
        hexv = f"#{r:02X}{g:02X}{b:02X}"
        rgba_fixed += 1
        if len(nums) >= 4 and float(nums[3]) < 1:
            return f'{attr}="{hexv}" {attr}-opacity="{nums[3]}"'
        return f'{attr}="{hexv}"'

    attr_alt = "|".join(_COLOR_ATTRS)
    rgba_attr_re = re.compile(rf'\b({attr_alt})="\s*(rgba?\([^)]*\))\s*"')
    n_attr_rgba = len(rgba_attr_re.findall(text))
    if n_attr_rgba:
        out.append(Finding("autofix", "rgba_color", "error",
                           f"{n_attr_rgba} rgb(a)() color attribute(s) - banned; converted to hex "
                           "with alpha preserved as a matching -opacity attribute.", n_attr_rgba))
        if do_fix:
            text = rgba_attr_re.sub(_split_rgba, text)

    # HTML named entities → Unicode.
    ent_total = sum(text.count(k) for k in _HTML_ENTITIES)
    if ent_total:
        out.append(Finding("autofix", "html_entities", "error",
                           f"{ent_total} HTML named entity occurrence(s) -write raw Unicode instead.", ent_total))
        if do_fix:
            for k, v in _HTML_ENTITIES.items():
                text = text.replace(k, v)

    # `<g opacity=...>` → REVIEW: group opacity must be pushed to each child, which
    # needs the element tree and can shift compositing; not a guaranteed visual no-op,
    # so it is flagged, never auto-rewritten.
    ngop = len(re.findall(r"<g\b[^>]*\sopacity=", text))
    if ngop:
        out.append(Finding("review", "group_opacity", "warning",
                           f"{ngop} <g opacity=...> - set opacity on each child instead "
                           "(needs the element tree; not auto-rewritten).", ngop))

    # Stray '&' not part of a legal XML entity → escape.
    stray = 0
    for m in re.finditer(r"&", text):
        rest = text[m.start():m.start() + 12]
        if not _LEGAL_XML_ENTITY.match(rest) and not any(rest.startswith(k) for k in _HTML_ENTITIES):
            stray += 1
    if stray:
        out.append(Finding("autofix", "stray_ampersand", "error",
                           f"{stray} unescaped '&' -must be &amp; (breaks XML parse).", stray))
        if do_fix:
            text = re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", text)

    return text, out


# ── SECURITY detectors (untrusted SVG) — always run; gate is opt-in via --ingest ─
def _detect_and_fix_security(text: str, do_fix: bool) -> tuple[str, list[Finding]]:
    """Find (and, for the strip-safe ones, remove) active/external content in an
    SVG. These constructs are never valid in our profile, so the scan always runs;
    ``--ingest`` is what turns the result into a hard gate (see ``main``)."""
    out: list[Finding] = []

    # DTDs — XXE / billion-laughs. Text-level: the parser may reject the file
    # outright, but we still want a precise, human-readable finding either way.
    n_ent = len(_ENTITY_RE.findall(text))
    if n_ent:
        out.append(Finding("review", "sec_entity", "error",
                           f"{n_ent} <!ENTITY> declaration(s) — XXE / billion-laughs vector with no "
                           "legitimate use in this profile. Reject the file outright.", n_ent))
    n_doc = len(_DOCTYPE_RE.findall(text))
    if n_doc:
        out.append(Finding("review", "sec_doctype", "error",
                           f"{n_doc} <!DOCTYPE> declaration(s) — a DTD has no place in a PPTX SVG and "
                           "can carry entity attacks; strip the DOCTYPE before incorporating.", n_doc))

    # Inline event handlers (onload/onclick/…) — executable script, but they paint
    # nothing, so stripping them is a guaranteed visual no-op (AUTO-FIX).
    handlers = _EVENT_HANDLER_RE.findall(text)
    if handlers:
        out.append(Finding("autofix", "sec_event_handler", "error",
                           f"{len(handlers)} inline event handler(s) (on…=) — executable script; "
                           "non-rendering, stripped.", len(handlers)))
        if do_fix:
            text = _EVENT_HANDLER_RE.sub("", text)

    # javascript: URLs in a link/href — active, non-rendering for a static asset, so
    # the offending attribute is dropped (AUTO-FIX); any visible children remain.
    js = _JS_URL_ATTR_RE.findall(text)
    if js:
        out.append(Finding("autofix", "sec_js_url", "error",
                           f"{len(js)} javascript: URL(s) in href/src — script execution; the attribute "
                           "is stripped (visible child content is preserved).", len(js)))
        if do_fix:
            text = _JS_URL_ATTR_RE.sub("", text)

    # External resource references — fetched from a remote server at render time
    # (SSRF / data-exfiltration / phone-home). Removing them WOULD change the render
    # (the asset disappears), so per the visual-preserving invariant they are REVIEW:
    # rehost the asset locally; never ship a remote dependency.
    ext = len(_EXTERNAL_REF_RE.findall(text)) + len(_EXTERNAL_URL_FUNC_RE.findall(text))
    if ext:
        out.append(Finding("review", "sec_external_ref", "error",
                           f"{ext} external http(s) reference(s) (href/src/url()) — loaded from a remote "
                           "server when the slide renders (exfiltration / SSRF risk). Rehost the asset "
                           "locally before incorporating; do not ship the remote URL.", ext))

    # data: URIs — opaque embedded blob; could be a legit base64 image or a smuggled
    # payload. A human must eyeball it (REVIEW), it is not auto-removed.
    dat = len(_DATA_URI_RE.findall(text))
    if dat:
        out.append(Finding("review", "sec_data_uri", "warning",
                           f"{dat} data: URI(s) embedded — opaque blob; confirm it is an expected image "
                           "and not a smuggled payload before incorporating.", dat))

    return text, out


def review(path: Path, do_fix: bool) -> tuple[list[Finding], str | None]:
    """Return (findings, fixed_text|None). fixed_text is None unless do_fix changed something."""
    original = path.read_text(encoding="utf-8", errors="replace")
    fixed_text, autofix_findings = _detect_and_fix(original, do_fix)
    # Untrusted-content scan (always on); strip-safe items are fixed when do_fix.
    fixed_text, sec_findings = _detect_and_fix_security(fixed_text, do_fix)
    # Re-parse the (possibly fixed) text for the review-class structural checks.
    review_findings = _detect_review(fixed_text, _parse(fixed_text))
    # Security first (most important), then the rest.
    findings = sec_findings + autofix_findings + review_findings
    changed = do_fix and fixed_text != original
    return findings, (fixed_text if changed else None)


def _is_security(f: Finding) -> bool:
    return f.code.startswith("sec_")


def _group(findings: list[Finding]) -> dict:
    """Split findings into the report's four buckets (security pulled out first)."""
    sec = [f for f in findings if _is_security(f)]
    return {
        "security": sec,
        "autofix": [f for f in findings if f.cls == "autofix" and not _is_security(f)],
        "review": [f for f in findings if f.cls == "review" and not _is_security(f)],
        "info": [f for f in findings if f.cls == "info"],
    }


def _gate_blocking(findings: list[Finding], ingest: bool) -> list[Finding]:
    """Findings that fail the exit code: every REVIEW item always; under --ingest,
    ALSO any security finding even if it was auto-stripped (forces human sign-off)."""
    blocking = [f for f in findings if f.cls == "review"]
    if ingest:
        blocking += [f for f in findings if _is_security(f) and f.cls != "review"]
    return blocking


def _print_report(path: Path, findings: list[Finding], fixed: bool, ingest: bool = False) -> None:
    # ASCII-only output: this runs in Windows cp1252 consoles where box-drawing /
    # check glyphs raise UnicodeEncodeError.
    g = _group(findings)
    print(f"\nsvg_doctor -- {path.name}" + ("  [INGESTION GATE]" if ingest else ""))
    print("-" * 64)
    if not findings:
        print("  [OK] clean -- no workflow-affecting or security issues found.")
        return
    if g["security"]:
        print(f"  SECURITY ({len(g['security'])}):")
        for f in g["security"]:
            mark = "[stripped]" if fixed and f.cls == "autofix" else "[!]"
            print(f"    {mark} [{f.severity}] {f.code}: {f.message}")
    label = "FIXED" if fixed else "AUTO-FIXABLE"
    if g["autofix"]:
        print(f"  {label} ({len(g['autofix'])}):")
        for f in g["autofix"]:
            mark = "[fixed]" if fixed else "-"
            print(f"    {mark} [{f.severity}] {f.code}: {f.message}")
    if g["review"]:
        print(f"  NEEDS REVIEW -- not auto-fixed ({len(g['review'])}):")
        for f in g["review"]:
            print(f"    [!] [{f.severity}] {f.code}: {f.message}")
    if g["info"]:
        print(f"  INFO -- advisory, does not block ({len(g['info'])}):")
        for f in g["info"]:
            print(f"    [i] [{f.severity}] {f.code}: {f.message}")
    if g["autofix"] and not fixed:
        print("\n  Run again with --fix to apply the auto-fixable items.")


def build_report(path: Path, findings: list[Finding], fixed: bool, ingest: bool) -> str:
    """A shareable Markdown report (verdict + grouped findings + next steps) for the
    eng/UX team reviewing an incoming SVG. Written by --report / --ingest."""
    g = _group(findings)
    blocking = _gate_blocking(findings, ingest)
    verdict = "REJECT" if blocking else "ACCEPT"
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    mode = "Ingestion gate (untrusted file)" if ingest else "Lint review"

    def _rows(items: list[Finding]) -> list[str]:
        out = []
        for f in items:
            msg = f.message.replace("|", "\\|")
            out.append(f"| `{f.code}` | {f.severity} | {f.count} | {msg} |")
        return out

    L: list[str] = []
    L.append(f"# SVG ingestion report — `{path.name}`")
    L.append("")
    L.append(f"- **File:** `{path}`")
    L.append(f"- **Size:** {size:,} bytes")
    L.append(f"- **Scanned:** {ts}")
    L.append(f"- **Mode:** {mode}")
    L.append(f"- **Auto-fixes applied:** {'yes' if fixed else 'no'}")
    L.append("")
    if verdict == "REJECT":
        L.append(f"## ❌ Verdict: REJECT — {len(blocking)} blocking item(s)")
        L.append("")
        L.append("Do **not** add this file to the catalog until the blocking items below "
                 "are resolved (rehost/remove external & active content, clear DTDs, or "
                 "manually inline banned-but-visible elements while preserving the look).")
    else:
        L.append("## ✅ Verdict: ACCEPT")
        L.append("")
        L.append("No blocking security or workflow issues remain. Any AUTO-FIX items were "
                 "applied as visual no-ops; INFO items are advisory only.")
    L.append("")
    L.append("| bucket | count | meaning |")
    L.append("|---|---:|---|")
    L.append(f"| 🔒 Security | {len(g['security'])} | active/external content (gates under --ingest) |")
    L.append(f"| 🔧 Auto-fix | {len(g['autofix'])} | repaired as a guaranteed visual no-op |")
    L.append(f"| 👀 Needs review | {len(g['review'])} | manual fix; would change render if auto-stripped |")
    L.append(f"| ℹ️ Info | {len(g['info'])} | advisory; never blocks |")
    L.append("")

    sections = [
        ("🔒 Security", g["security"],
         "Active or externally-fetched content. Strip-safe items (event handlers, "
         "`javascript:`) were removed automatically; the rest require a human decision."),
        ("👀 Needs review", g["review"],
         "Genuine issues whose safe fix is **not** a visual no-op — fix by hand while "
         "preserving the look (inline a banned `<style>`/`<foreignObject>`, rehost an "
         "external image, re-orient a flipped transform)."),
        ("🔧 Auto-fix", g["autofix"],
         "Mechanical repairs that leave the rendered asset pixel-identical. Already "
         "applied if `--fix`; otherwise re-run with `--fix`."),
        ("ℹ️ Info", g["info"],
         "Advisory only — does not block ingestion (e.g. a raw PowerPoint export, which "
         "is an accepted verbatim+re-theme class)."),
    ]
    for title, items, blurb in sections:
        if not items:
            continue
        L.append(f"### {title} ({len(items)})")
        L.append("")
        L.append(blurb)
        L.append("")
        L.append("| code | severity | count | detail |")
        L.append("|---|---|---:|---|")
        L.extend(_rows(items))
        L.append("")

    L.append("---")
    L.append("")
    L.append("### Recommended next steps")
    L.append("")
    if blocking:
        L.append("1. Resolve every item in **Security** and **Needs review** above.")
        L.append("2. Re-run `svg_doctor.py <file> --ingest --fix` until the verdict is ACCEPT.")
        L.append("3. Only then copy the file into "
                 "`templates/charts/powerslides_infographics/` as a raw template.")
    else:
        L.append("1. File is clear to add to "
                 "`templates/charts/powerslides_infographics/`.")
        L.append("2. The runner takes over from here: verbatim copy → deterministic "
                 "re-theme → layout audit → provenance check.")
    L.append("")
    L.append("_Generated by `svg_doctor.py`._")
    L.append("")
    return "\n".join(L)


def main(argv: list[str]) -> int:
    # Best-effort UTF-8 stdout so any non-ASCII in messages prints on Windows
    # cp1252 consoles instead of raising UnicodeEncodeError.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Lint/auto-fix/sanitize a single SVG for PPTX-workflow safety.")
    ap.add_argument("svg", help="path to the .svg file")
    ap.add_argument("--fix", action="store_true", help="apply auto-fixable issues (REVIEW items are never touched)")
    ap.add_argument("-o", "--output", help="write fixed SVG here instead of in place (implies --fix)")
    ap.add_argument("--json", action="store_true", help="emit findings as JSON")
    ap.add_argument("--ingest", action="store_true",
                    help="untrusted-file gate: fail (exit 1) if ANY active/external construct was "
                         "present — even one auto-stripped — so a human signs off before the file "
                         "enters the catalog. Writes a report into this tool's reports/ folder "
                         "(svg_doctor/reports/<name>.svgdoctor.md) unless --report overrides the path.")
    ap.add_argument("--report", metavar="PATH",
                    help="write a shareable Markdown report (verdict + grouped findings + next steps) to PATH")
    args = ap.parse_args(argv)

    path = Path(args.svg)
    if not path.is_file():
        print(json.dumps({"error": f"not a file: {path}"}) if args.json else f"Not a file: {path}")
        return 2
    do_fix = args.fix or bool(args.output)

    findings, fixed_text = review(path, do_fix)

    if fixed_text is not None:
        out_path = Path(args.output) if args.output else path
        out_path.write_text(fixed_text, encoding="utf-8")

    # Shareable Markdown report — explicit --report, or a default under --ingest.
    # The default lands in this tool's own reports/ folder (NOT next to the input
    # SVG), so a catalog sweep never litters the template folders.
    report_path = args.report
    if args.ingest and not report_path:
        reports_dir = Path(__file__).resolve().parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = str(reports_dir / (path.name + ".svgdoctor.md"))
    if report_path:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(
            build_report(path, findings, fixed_text is not None, args.ingest), encoding="utf-8")

    if args.json:
        print(json.dumps({
            "file": str(path),
            "fixed": fixed_text is not None,
            "output": (args.output or str(path)) if fixed_text is not None else None,
            "ingest": args.ingest,
            "verdict": "reject" if _gate_blocking(findings, args.ingest) else "accept",
            "report": report_path,
            "findings": [f.as_dict() for f in findings],
        }, indent=2))
    else:
        _print_report(path, findings, fixed=fixed_text is not None, ingest=args.ingest)
        if report_path:
            print(f"\n  Report written to: {report_path}")

    return 1 if _gate_blocking(findings, args.ingest) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
