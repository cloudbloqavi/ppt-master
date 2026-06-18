#!/usr/bin/env python3
"""
Presentation Builder - Deterministic SVG Layout Auditor

A *deterministic* visual-QA engine for slide SVGs. Unlike the eyeball-rubric
visual-review (a model looking at a rendered PNG), this computes element geometry
mathematically and flags layout defects with no model judgement in the loop:

  - text <-> text overlap          (two text blocks' boxes intersect)
  - text overflow                  (text box extends past its container rect/image)
  - text <-> border/stroke collision (text box crosses a shape's stroke band)
  - out-of-bounds                  (box falls outside 0,0,1280,720)
  - element / shape collision      (opaque shapes overlap with z-order issues)
  - orphan baseline (static)       (multi-line <text> whose first positional
                                    <tspan> has dy but neither it nor the <text>
                                    sets an absolute y -> the whole block renders
                                    from y=0 and floats into the header. This is
                                    the #1 cause of the "random" overlap bug.)

Detection is always deterministic. For the unambiguous geometric cases this tool
also AUTO-FIXES the SVG in place (option-a scope: fix what is unambiguous, report
the rest for a model/human), then re-audits and rolls back any fix that fails to
clear its finding or introduces a new hard hit.

Geometry backends (auto-selected, graceful degradation):
  1. chromium getBBox (exact)  - used when playwright + chromium are importable.
  2. python estimator (approx) - dependency-light fallback; font-metric heuristics.
     Precise enough for gross structural errors (y=0 origin, out-of-bounds, large
     overflow); slightly conservative for tight near-adjacent overlaps.

Usage:
    python3 scripts/svg_layout_auditor.py <project_path> [--pages 02 05]
                                          [--no-autofix] [--backend auto|estimator|chromium]
                                          [--canvas WxH]

Outputs:
    <project>/.review/<page>.audit.json   per-page findings (machine readable)
    JSON summary to stdout

Exit codes:
    0 - ran; no unresolved HARD findings remain
    1 - ran; one or more unresolved HARD findings remain (see JSON)
    2 - could not run (bad project path / no svg_output)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from xml.etree import ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
DEFAULT_CANVAS = (1280, 720)

# Serialize SVG elements without an "ns0:" prefix — register the SVG namespace as
# the default so ElementTree writes <rect>/<text>, not <ns0:rect>. Without this,
# every auto-fixed SVG would be corrupted for browsers and the PPTX exporter.
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")

# Font-metric heuristics for the estimator backend. Average glyph advance as a
# fraction of font-size; deliberately mid-range for proportional Latin fonts.
_CHAR_W_NORMAL = 0.52
_CHAR_W_BOLD = 0.56
_ASCENT = 0.80   # top of glyph box above baseline, as fraction of font-size
_DESCENT = 0.22  # below baseline
# A char that is visibly wider/narrower than average — coarse correction only.
_WIDE_CHARS = set("WMHKQGOD@%&")
_NARROW_CHARS = set("ilIjt.,;:'!| ")

# Overlap must exceed this many px in BOTH axes to count as a real text collision
# (guards against hairline touching that the estimator can't resolve precisely).
_OVERLAP_MIN_PX = 6.0
# CJK glyphs are ~full-em wide; detect to widen the advance estimate.
_CJK_RE = re.compile(r"[　-鿿＀-￯]")


def _localname(tag) -> str:
    # Comment / processing-instruction nodes have a callable tag, not a string —
    # return "" so they're transparently skipped by every kind check.
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _svg_parser() -> ET.XMLParser:
    """Parser that preserves comments so auto-fixes produce minimal diffs."""
    try:
        return ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    except TypeError:
        # insert_comments unsupported on very old Pythons — fall back (drops comments).
        return ET.XMLParser()


def _to_float(v, default=None):
    if v is None:
        return default
    try:
        return float(str(v).strip().replace("px", ""))
    except (ValueError, AttributeError):
        return default


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    def intersection(self, other: "Box") -> tuple[float, float]:
        """Return (overlap_w, overlap_h); zero/negative means no overlap."""
        ox = min(self.x2, other.x2) - max(self.x, other.x)
        oy = min(self.y2, other.y2) - max(self.y, other.y)
        return ox, oy

    def overlaps(self, other: "Box", min_px: float = 0.0) -> bool:
        ox, oy = self.intersection(other)
        return ox > min_px and oy > min_px


@dataclass
class Elem:
    """A measured element: its source node, geometry, and salient style."""
    kind: str                      # text | rect | image | circle | line | path | other
    node: ET.Element
    parent: ET.Element | None
    box: Box | None
    text: str = ""
    font_size: float = 0.0
    has_fill: bool = False
    stroke_w: float = 0.0
    idx: int = 0                   # document order (z-order proxy)
    x_anchor: str = "start"


@dataclass
class Finding:
    rule: str
    severity: str                  # "hard" | "soft"
    message: str
    elements: list[str] = field(default_factory=list)
    autofix: str = "none"          # none | applied | reverted | suggested
    detail: dict = field(default_factory=dict)


# ─────────────────────────── geometry: estimator ───────────────────────────

def _est_text_advance(s: str, font_size: float, bold: bool, letter_spacing: float) -> float:
    if not s:
        return 0.0
    base = _CHAR_W_BOLD if bold else _CHAR_W_NORMAL
    total = 0.0
    for ch in s:
        if _CJK_RE.match(ch):
            total += font_size * 1.0
        elif ch in _WIDE_CHARS:
            total += font_size * (base + 0.20)
        elif ch in _NARROW_CHARS:
            total += font_size * (base - 0.22)
        else:
            total += font_size * base
    total += letter_spacing * max(0, len(s) - 1)
    return total


def _style_lookup(node: ET.Element, parent: ET.Element | None, attr: str, default=None):
    """Resolve a presentation attribute from node then parent (one level)."""
    v = node.get(attr)
    if v is not None:
        return v
    if parent is not None:
        return parent.get(attr, default)
    return default


def estimate_text_box(node: ET.Element, parent: ET.Element | None) -> tuple[Box | None, str, float, str]:
    """Estimate the union bounding box of a <text> element and its tspans.

    Returns (box, concatenated_text, primary_font_size, text_anchor).
    Mirrors the SVG text-positioning algorithm closely enough to surface gross
    placement errors (the y=0 origin bug, out-of-bounds, large overflow).
    """
    text_fs = _to_float(_style_lookup(node, parent, "font-size"), 16.0) or 16.0
    anchor = _style_lookup(node, parent, "text-anchor", "start") or "start"
    text_ls = _to_float(node.get("letter-spacing"), 0.0) or 0.0

    # Current pen position; initial per SVG spec is the text's x/y or 0.
    cx = _to_float(node.get("x"), 0.0) or 0.0
    cy = _to_float(node.get("y"), 0.0) or 0.0

    children = [c for c in list(node) if _localname(c.tag) == "tspan"]
    boxes: list[Box] = []
    all_text: list[str] = []

    def add_run(s: str, bx: float, by: float, fs: float, bold: bool, ls: float, anc: str):
        s = (s or "").strip()
        if not s:
            return
        w = _est_text_advance(s, fs, bold, ls)
        if anc == "middle":
            left = bx - w / 2.0
        elif anc == "end":
            left = bx - w
        else:
            left = bx
        boxes.append(Box(left, by - _ASCENT * fs, w, (_ASCENT + _DESCENT) * fs))
        all_text.append(s)

    # Text directly inside <text> (no tspans) — rare in this codebase but valid.
    direct = (node.text or "").strip()
    if not children and direct:
        bold = "bold" in (str(_style_lookup(node, parent, "font-weight", "")) or "") \
            or _to_float(_style_lookup(node, parent, "font-weight"), 0) and _to_float(_style_lookup(node, parent, "font-weight"), 0) >= 600
        add_run(direct, cx, cy, text_fs, bool(bold), text_ls, anchor)

    for c in children:
        fs = _to_float(c.get("font-size"), text_fs) or text_fs
        ls = _to_float(c.get("letter-spacing"), text_ls) or text_ls
        fw = str(c.get("font-weight", "") or "")
        bold = "bold" in fw or (_to_float(fw, 0) or 0) >= 600
        anc = c.get("text-anchor", anchor) or anchor

        # Absolute x/y reset the pen; dx/dy shift it (SVG positioning algorithm).
        ax = _to_float(c.get("x"))
        ay = _to_float(c.get("y"))
        if ax is not None:
            cx = ax
        if ay is not None:
            cy = ay
        cx += _to_float(c.get("dx"), 0.0) or 0.0
        cy += _to_float(c.get("dy"), 0.0) or 0.0
        add_run(c.text or "", cx, cy, fs, bold, ls, anc)

    if not boxes:
        return None, "", text_fs, anchor

    left = min(b.x for b in boxes)
    top = min(b.y for b in boxes)
    right = max(b.x2 for b in boxes)
    bottom = max(b.y2 for b in boxes)
    return Box(left, top, right - left, bottom - top), " ".join(all_text), text_fs, anchor


def shape_box(node: ET.Element) -> Box | None:
    k = _localname(node.tag)
    if k == "rect":
        x = _to_float(node.get("x"), 0.0); y = _to_float(node.get("y"), 0.0)
        w = _to_float(node.get("width")); h = _to_float(node.get("height"))
        if w is None or h is None:
            return None
        return Box(x, y, w, h)
    if k == "image":
        x = _to_float(node.get("x"), 0.0); y = _to_float(node.get("y"), 0.0)
        w = _to_float(node.get("width")); h = _to_float(node.get("height"))
        if w is None or h is None:
            return None
        return Box(x, y, w, h)
    if k == "circle":
        cx = _to_float(node.get("cx"), 0.0); cy = _to_float(node.get("cy"), 0.0)
        r = _to_float(node.get("r"))
        if r is None:
            return None
        return Box(cx - r, cy - r, 2 * r, 2 * r)
    if k == "ellipse":
        cx = _to_float(node.get("cx"), 0.0); cy = _to_float(node.get("cy"), 0.0)
        rx = _to_float(node.get("rx")); ry = _to_float(node.get("ry"))
        if rx is None or ry is None:
            return None
        return Box(cx - rx, cy - ry, 2 * rx, 2 * ry)
    if k == "line":
        x1 = _to_float(node.get("x1"), 0.0); y1 = _to_float(node.get("y1"), 0.0)
        x2 = _to_float(node.get("x2"), 0.0); y2 = _to_float(node.get("y2"), 0.0)
        return Box(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
    if k == "path":
        nums = re.findall(r"-?\d+\.?\d*", node.get("d", "") or "")
        coords = [float(n) for n in nums]
        xs = coords[0::2]; ys = coords[1::2]
        if not xs or not ys:
            return None
        return Box(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    return None


# ─────────────────────────── parse & measure ───────────────────────────

def _has_visible_fill(node: ET.Element, parent: ET.Element | None) -> bool:
    fill = _style_lookup(node, parent, "fill", "#000000")
    if fill in ("none", "transparent", None):
        return False
    op = _to_float(_style_lookup(node, parent, "fill-opacity"), 1.0)
    return (op or 0) > 0.05


def measure_elements(root: ET.Element, canvas: tuple[int, int]) -> list[Elem]:
    elems: list[Elem] = []
    idx = 0
    # Walk with parent tracking so tspan/text inheritance resolves one level up.
    stack: list[tuple[ET.Element, ET.Element | None]] = [(root, None)]
    # We need document order; do an explicit pre-order traversal.
    order: list[tuple[ET.Element, ET.Element | None]] = []

    def walk(n: ET.Element, parent: ET.Element | None):
        order.append((n, parent))
        for ch in list(n):
            walk(ch, n)

    walk(root, None)

    for node, parent in order:
        k = _localname(node.tag)
        if k == "text":
            box, txt, fs, anc = estimate_text_box(node, parent)
            elems.append(Elem(
                kind="text", node=node, parent=parent, box=box, text=txt,
                font_size=fs, has_fill=_has_visible_fill(node, parent),
                stroke_w=_to_float(_style_lookup(node, parent, "stroke-width"), 0.0) or 0.0,
                idx=idx, x_anchor=anc,
            ))
            idx += 1
        elif k in ("rect", "image", "circle", "ellipse", "line", "path"):
            box = shape_box(node)
            elems.append(Elem(
                kind=k, node=node, parent=parent, box=box,
                has_fill=_has_visible_fill(node, parent) if k != "image" else True,
                stroke_w=_to_float(_style_lookup(node, parent, "stroke-width"), 0.0) or 0.0,
                idx=idx,
            ))
            idx += 1
    return elems


# ─────────────────────────── geometry: chromium (exact) ───────────────────────────

# JS run inside the rendered page: every measured element carries a
# data-audit-idx attribute (injected before rendering); return each one's
# bounding box in canvas coordinates (relative to the SVG's own client rect,
# which renders 1:1 with the 1280x720 viewBox). getBoundingClientRect is
# post-layout and transform-aware, so it captures real font shaping and any
# <g transform> — strictly more accurate than the estimator.
_EXTRACT_JS = """
() => {
  const svg = document.querySelector('svg');
  if (!svg) return {};
  const sr = svg.getBoundingClientRect();
  const out = {};
  for (const el of document.querySelectorAll('[data-audit-idx]')) {
    const r = el.getBoundingClientRect();
    out[el.getAttribute('data-audit-idx')] =
      [r.left - sr.left, r.top - sr.top, r.width, r.height];
  }
  return out;
}
"""


class ChromiumMeasurer:
    """Exact-geometry backend backed by a single headless-chromium session.

    Lazily launches one browser reused across all pages. On any failure (no
    playwright, no chromium, launch/render error) it degrades to ``ok = False``
    and the caller keeps the estimator boxes — the auditor never hard-depends on
    a browser. Built for the Linux/WSL runtime where playwright+chromium are
    installed; on Windows dev boxes without them it simply stays inactive.
    """

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._page = None
        self.ok = False

    def start(self) -> bool:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return False
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            ctx = self._browser.new_context(
                viewport={"width": DEFAULT_CANVAS[0], "height": DEFAULT_CANVAS[1]},
                device_scale_factor=1,
            )
            self._page = ctx.new_page()
            self._page.set_default_timeout(15000)
            self.ok = True
        except Exception as exc:
            _safe_print(f"chromium backend unavailable, using estimator: {exc}")
            self.close()
            self.ok = False
        return self.ok

    def measure(self, svg_str: str) -> dict | None:
        """Render an SVG string and return {idx_str: [x, y, w, h]} or None."""
        if not self.ok or self._page is None:
            return None
        html = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>*{margin:0;padding:0;border:0}html,body{background:#fff}</style>"
            f"</head><body>{svg_str}</body></html>"
        )
        try:
            self._page.set_content(html, wait_until="load")
            # Let web fonts settle so text shaping matches the live preview.
            try:
                self._page.evaluate("async () => { await document.fonts.ready; }")
            except Exception:
                pass
            return self._page.evaluate(_EXTRACT_JS)
        except Exception as exc:  # noqa: BLE001 — never let a render error abort the audit
            _safe_print(f"chromium render failed (page kept via estimator): {exc}")
            return None

    def close(self) -> None:
        for closer in (
            lambda: self._browser and self._browser.close(),
            lambda: self._pw and self._pw.stop(),
        ):
            try:
                closer()
            except Exception:
                pass
        self._browser = self._pw = self._page = None


def _apply_chromium_geometry(tree: ET.ElementTree, elems: list[Elem],
                             measurer: "ChromiumMeasurer") -> bool:
    """Overwrite estimator boxes with exact chromium boxes where available.

    Tags each measured node with data-audit-idx, renders once, maps boxes back by
    idx, then strips the temporary attribute so the tree stays pristine for the
    writer. Returns True if exact geometry was applied to at least one element.
    """
    tagged: list[ET.Element] = []
    for e in elems:
        e.node.set("data-audit-idx", str(e.idx))
        tagged.append(e.node)
    try:
        svg_str = ET.tostring(tree.getroot(), encoding="unicode")
        boxes = measurer.measure(svg_str)
    finally:
        for n in tagged:
            n.attrib.pop("data-audit-idx", None)
    if not boxes:
        return False
    by_idx = {e.idx: e for e in elems}
    applied = 0
    for idx_str, bb in boxes.items():
        try:
            e = by_idx.get(int(idx_str))
        except (TypeError, ValueError):
            e = None
        if e is None:
            continue
        x, y, w, h = bb
        if w > 0 and h > 0:
            e.box = Box(float(x), float(y), float(w), float(h))
            applied += 1
    return applied > 0


def _elem_label(e: Elem) -> str:
    nid = e.node.get("id")
    if nid:
        return f"{e.kind}#{nid}"
    if e.kind == "text" and e.text:
        return f"text[{e.text[:24]!r}]"
    if e.box:
        return f"{e.kind}@({int(e.box.x)},{int(e.box.y)})"
    return e.kind


# ─────────────────────────── detectors ───────────────────────────

def detect_orphan_baseline(node: ET.Element, parent: ET.Element | None) -> bool:
    """Static check: multi-line <text> whose baseline originates at y=0.

    Fires when the <text> has no absolute y, AND its first positional <tspan>
    (the one carrying x) supplies dy but no absolute y. The SVG renders such a
    block from y=0, floating it into the header band. No geometry needed.
    """
    if node.get("y") is not None:
        return False
    tspans = [c for c in list(node) if _localname(c.tag) == "tspan"]
    if len(tspans) < 2:
        return False
    first = tspans[0]
    if first.get("y") is not None:
        return False
    # Must actually rely on dy for vertical advance (else it's just y=0 baseline,
    # a different, single-line case we don't touch here).
    any_dy = any(_to_float(t.get("dy")) for t in tspans)
    return bool(any_dy) and first.get("dy") is not None


def audit_page(svg_path: Path, canvas: tuple[int, int],
               measurer: "ChromiumMeasurer | None" = None
               ) -> tuple[list[Finding], ET.ElementTree]:
    tree = ET.parse(svg_path, parser=_svg_parser())
    root = tree.getroot()
    elems = measure_elements(root, canvas)
    # Upgrade estimator boxes to exact chromium geometry when the backend is live.
    if measurer is not None and measurer.ok:
        _apply_chromium_geometry(tree, elems, measurer)
    findings: list[Finding] = []
    cw, ch = canvas

    texts = [e for e in elems if e.kind == "text" and e.box and e.has_fill]
    # Grid/card cells are often exported as filled <path> rects (e.g. calendar
    # day cells), not <rect> — D4's container match must see those too, or
    # text overflowing a path-drawn cell is silently never checked.
    shapes = [e for e in elems if e.box and (
        e.kind in ("rect", "image") or (e.kind == "path" and e.has_fill))]

    # D1 — orphan baseline (static, hard)
    for e in texts:
        if detect_orphan_baseline(e.node, e.parent):
            findings.append(Finding(
                rule="D1_orphan_baseline", severity="hard",
                message="multi-line <text> has no absolute y; first tspan uses dy "
                        "from y=0 origin — block renders into the header band",
                elements=[_elem_label(e)],
                detail={"box": asdict(e.box) if e.box else None},
            ))

    # D2 — text <-> text overlap (geometry, hard)
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            a, b = texts[i], texts[j]
            if a.box.overlaps(b.box, _OVERLAP_MIN_PX):
                ox, oy = a.box.intersection(b.box)
                findings.append(Finding(
                    rule="D2_text_overlap", severity="hard",
                    message=f"text boxes overlap by ~{int(ox)}x{int(oy)}px",
                    elements=[_elem_label(a), _elem_label(b)],
                    detail={"overlap_px": [round(ox, 1), round(oy, 1)]},
                ))

    # D3 — out-of-bounds (geometry, hard)
    canvas_box = Box(0, 0, cw, ch)
    for e in texts:
        ox, oy = e.box.intersection(canvas_box)
        inside_w = max(0.0, ox); inside_h = max(0.0, oy)
        if inside_w < e.box.w - 1 or inside_h < e.box.h - 1:
            # Some part is outside the canvas.
            over_left = max(0.0, -e.box.x)
            over_right = max(0.0, e.box.x2 - cw)
            over_top = max(0.0, -e.box.y)
            over_bottom = max(0.0, e.box.y2 - ch)
            worst = max(over_left, over_right, over_top, over_bottom)
            if worst > 2:
                findings.append(Finding(
                    rule="D3_out_of_bounds", severity="hard",
                    message=f"text extends ~{int(worst)}px outside the {cw}x{ch} canvas",
                    elements=[_elem_label(e)],
                    detail={"over": {"l": over_left, "r": over_right,
                                     "t": over_top, "b": over_bottom}},
                ))

    # D4 — text overflow past a containing rect/image (geometry, soft→reported)
    for t in texts:
        container = _enclosing_container(t, shapes)
        if container is None:
            continue
        pad = 4.0
        cb = container.box
        spill = max(t.box.x2 - (cb.x2 - pad), (cb.x + pad) - t.box.x,
                    t.box.y2 - (cb.y2 - pad), (cb.y + pad) - t.box.y)
        if spill > 8:
            findings.append(Finding(
                rule="D4_text_overflow", severity="soft",
                message=f"text spills ~{int(spill)}px past its container "
                        f"{_elem_label(container)}",
                elements=[_elem_label(t), _elem_label(container)],
                detail={"spill_px": round(spill, 1)},
            ))

    return findings, tree


def _enclosing_container(text: Elem, shapes: list[Elem]) -> Elem | None:
    """Find the smallest rect/image whose box mostly contains the text's center.

    Used for overflow detection. Conservative: requires the text center to sit
    inside the shape and the shape to be a plausible 'card' (both dims > text).
    """
    tc_x = text.box.x + text.box.w / 2
    tc_y = text.box.y + text.box.h / 2
    best = None
    best_area = None
    for s in shapes:
        b = s.box
        if not (b.x <= tc_x <= b.x2 and b.y <= tc_y <= b.y2):
            continue
        if b.w < text.box.w * 0.6 or b.h < text.box.h * 0.6:
            continue
        area = b.w * b.h
        if best_area is None or area < best_area:
            best, best_area = s, area
    return best


# ─────────────────────────── auto-fix (option a) ───────────────────────────

def fix_orphan_baseline(tree: ET.ElementTree, canvas: tuple[int, int]) -> int:
    """Repair every orphan-baseline <text> by anchoring its first line below the
    nearest header element in its column. Deterministic, intent-preserving.

    Returns the number of text blocks repaired.
    """
    root = tree.getroot()
    elems = measure_elements(root, canvas)
    cw, ch = canvas
    fixed = 0

    text_elems = [e for e in elems if e.kind == "text" and e.box]
    for e in text_elems:
        if not detect_orphan_baseline(e.node, e.parent):
            continue
        tspans = [c for c in list(e.node) if _localname(c.tag) == "tspan"]
        first = tspans[0]
        first_fs = _to_float(first.get("font-size"),
                             _to_float(_style_lookup(e.node, e.parent, "font-size"), 16.0)) or 16.0
        first_dy = _to_float(first.get("dy"), 0.0) or 0.0

        # Column band = the orphan block's horizontal extent.
        band_x1, band_x2 = e.box.x, e.box.x2
        canvas_area = cw * ch
        anchor_bottom = None
        for other in elems:
            if other is e or other.box is None:
                continue
            if other.kind not in ("text", "rect", "image", "line"):
                continue
            # Same column: x-ranges overlap meaningfully.
            ox = min(band_x2, other.box.x2) - max(band_x1, other.box.x)
            if ox <= 5:
                continue
            # Header zone only: sits in the upper half and is not the footer.
            if other.box.y > ch * 0.5:
                continue
            # Ignore other orphan-bugged text (also floating at y~0).
            if other.kind == "text" and detect_orphan_baseline(other.node, other.parent):
                continue
            # Skip background / large container shapes (full-canvas backdrop, tall
            # cards, side images). Anchoring to a backdrop's bottom (y=720) would
            # shove the text off-canvas — titles/subtitles/dividers are the real
            # anchors. Text and thin lines are always eligible.
            if other.kind in ("rect", "image"):
                b = other.box
                if (b.h > ch * 0.40 or b.w > cw * 0.60
                        or b.w * b.h > canvas_area * 0.15):
                    continue
            anchor_bottom = max(anchor_bottom or 0.0, other.box.y2)

        gap = max(1.3 * first_fs, 18.0)
        if anchor_bottom is None:
            new_y = 150.0  # no header above → safe top margin
        else:
            new_y = anchor_bottom + gap

        # Apply: pin first line to an absolute y, drop the now-redundant dy so the
        # cumulative dy chain flows downward from the corrected origin.
        first.set("y", f"{new_y:.0f}")
        if first.get("dy") is not None:
            del first.attrib["dy"]
        fixed += 1
        _ = first_dy  # retained for clarity; dy folded into the gap
    return fixed


def _shift_text_node(node: ET.Element, dx: float, dy: float) -> None:
    """Translate a <text> element (and any absolutely-positioned tspans) by
    (dx, dy). Only attributes already present are rewritten — dx/dy on tspans
    are relative and keep working unchanged since the pen position they offset
    from moves with the absolute x/y they're chained from."""
    if dx:
        cur = _to_float(node.get("x"), 0.0) or 0.0
        node.set("x", f"{cur + dx:.2f}")
    if dy:
        cur = _to_float(node.get("y"), 0.0) or 0.0
        node.set("y", f"{cur + dy:.2f}")
    for c in list(node):
        if _localname(c.tag) != "tspan":
            continue
        if dx and c.get("x") is not None:
            cur = _to_float(c.get("x"), 0.0) or 0.0
            c.set("x", f"{cur + dx:.2f}")
        if dy and c.get("y") is not None:
            cur = _to_float(c.get("y"), 0.0) or 0.0
            c.set("y", f"{cur + dy:.2f}")


def fix_out_of_bounds(tree: ET.ElementTree, canvas: tuple[int, int]) -> int:
    """Translate every off-canvas <text> block back inside the canvas.

    Shifts the whole block (its x/y and any absolute tspan x/y) by the exact
    overage plus a small margin, on whichever axis(es) it overflows. This is a
    rigid translation — internal line spacing and anchoring are untouched — so
    it cannot itself introduce a new D1/D4-style defect, only move the block.
    """
    root = tree.getroot()
    elems = measure_elements(root, canvas)
    cw, ch = canvas
    margin = 4.0
    fixed = 0

    for e in elems:
        if e.kind != "text" or e.box is None:
            continue
        b = e.box
        over_left = max(0.0, -b.x)
        over_right = max(0.0, b.x2 - cw)
        over_top = max(0.0, -b.y)
        over_bottom = max(0.0, b.y2 - ch)
        if max(over_left, over_right, over_top, over_bottom) <= 2:
            continue

        shift_x = 0.0
        if over_left > 2 and over_left >= over_right:
            shift_x = over_left + margin
        elif over_right > 2:
            shift_x = -(over_right + margin)
        shift_y = 0.0
        if over_top > 2 and over_top >= over_bottom:
            shift_y = over_top + margin
        elif over_bottom > 2:
            shift_y = -(over_bottom + margin)
        if not shift_x and not shift_y:
            continue

        _shift_text_node(e.node, shift_x, shift_y)
        fixed += 1
    return fixed


def fix_text_overlap(tree: ET.ElementTree, canvas: tuple[int, int]) -> int:
    """Separate overlapping <text> pairs by the minimum translation needed.

    For each overlapping pair, moves apart along whichever axis has the
    *smaller* penetration depth (the shorter, lower-risk separation) — pushing
    the element with the larger coordinate on that axis further away. Each
    text node is moved at most once per pass so independent rows (the common
    case: a label crowding its adjacent badge/value) never fight each other;
    any pair still touching afterward simply remains a reported finding rather
    than being forced apart riskily.
    """
    root = tree.getroot()
    elems = measure_elements(root, canvas)
    margin = 6.0
    fixed = 0
    moved: set[int] = set()

    texts = [e for e in elems if e.kind == "text" and e.box and e.has_fill]
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            a, b = texts[i], texts[j]
            if id(a.node) in moved or id(b.node) in moved:
                continue
            if not a.box.overlaps(b.box, _OVERLAP_MIN_PX):
                continue
            ox, oy = a.box.intersection(b.box)
            if ox <= oy:
                mover, shift = (b, ox + margin) if b.box.x >= a.box.x else (a, ox + margin)
                _shift_text_node(mover.node, shift, 0.0)
            else:
                mover, shift = (b, oy + margin) if b.box.y >= a.box.y else (a, oy + margin)
                _shift_text_node(mover.node, 0.0, shift)
            moved.add(id(mover.node))
            fixed += 1
    return fixed


def _scale_text_font(node: ET.Element, parent: ET.Element | None, scale: float) -> None:
    """Shrink a <text> element's font-size (and any tspan that overrides it)
    by ``scale``, writing the resolved size explicitly onto the node so the
    shrink takes effect even when the size was only inherited from a parent
    group — siblings sharing that parent are left untouched."""
    fs = _to_float(_style_lookup(node, parent, "font-size"), 16.0) or 16.0
    node.set("font-size", f"{fs * scale:.2f}")
    for c in list(node):
        if _localname(c.tag) != "tspan":
            continue
        cfs = _to_float(c.get("font-size"))
        if cfs is not None:
            c.set("font-size", f"{cfs * scale:.2f}")


_D4_FIXED_MARKER = "data-d4fix"


def fix_text_overflow(tree: ET.ElementTree, canvas: tuple[int, int]) -> int:
    """Shrink <text> that spills past its enclosing card/cell to fit inside it.

    Unlike D1-D3's rigid translations, this changes the text's visual size —
    riskier, so the shrink is capped at _MIN_SCALE (never below 60% of the
    original size) and skipped entirely if that floor still wouldn't fit,
    leaving an honest unresolved finding rather than shrinking text to
    illegibility.

    Marks each shrunk node with _D4_FIXED_MARKER and never touches it again:
    as a box shrinks its center can drift over a *different* neighboring
    cell (the content's pen-position already straddled two cells before any
    fix ran), which would otherwise relitigate the same element against a
    new container on every re-run and shrink it further with no floor —
    compounding indefinitely across repeated audits instead of converging.
    """
    root = tree.getroot()
    elems = measure_elements(root, canvas)
    shapes = [e for e in elems if e.box and (
        e.kind in ("rect", "image") or (e.kind == "path" and e.has_fill))]
    texts = [e for e in elems if e.kind == "text" and e.box and e.has_fill]
    pad = 4.0
    _MIN_SCALE = 0.6
    fixed = 0

    for t in texts:
        if t.node.get(_D4_FIXED_MARKER) is not None:
            continue
        container = _enclosing_container(t, shapes)
        if container is None:
            continue
        cb = container.box
        spill = max(t.box.x2 - (cb.x2 - pad), (cb.x + pad) - t.box.x,
                    t.box.y2 - (cb.y2 - pad), (cb.y + pad) - t.box.y)
        if spill <= 8:
            continue
        # Anchor-relative fit: shrinking scales the text about its anchor point,
        # so the fittable width is measured from that anchor to the container edge
        # on the spilling side — NOT the full container width. The old box-vs-
        # container ratio missed *positional* spill (text narrower than the cell
        # but offset past its edge, e.g. a longer replacement label anchored where
        # a short one was), yielding scale≈1.0 and declining the fix.
        if t.x_anchor == "middle":
            cx = t.box.x + t.box.w / 2
            half = max(1.0, t.box.w / 2)
            avail_w = max(1.0, min(cx - (cb.x + pad), (cb.x2 - pad) - cx))
            scale_w = avail_w / half
        elif t.x_anchor == "end":
            scale_w = max(1.0, t.box.x2 - (cb.x + pad)) / (t.box.w or 1.0)
        else:  # start
            scale_w = max(1.0, (cb.x2 - pad) - t.box.x) / (t.box.w or 1.0)
        avail_h = max(1.0, cb.h - 2 * pad)
        scale_h = avail_h / t.box.h if t.box.h else 1.0
        scale = max(_MIN_SCALE, min(1.0, scale_w, scale_h))
        t.node.set(_D4_FIXED_MARKER, "1")
        if scale >= 0.98:
            continue
        _scale_text_font(t.node, t.parent, scale)
        fixed += 1
    return fixed


# ─────────────────────────── driver ───────────────────────────

def _hard(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "hard"]


# Rules attempted in this order: D1 untangles the y=0 header-band float first
# (it can dwarf every other measurement on the page), D3 then pulls anything
# off-canvas back in, and D2 resolves remaining text/text crowding last, once
# positions are otherwise sane.
_FIXERS: list[tuple[str, "callable"]] = [
    ("D1_orphan_baseline", fix_orphan_baseline),
    ("D3_out_of_bounds", fix_out_of_bounds),
    ("D2_text_overlap", fix_text_overlap),
    ("D4_text_overflow", fix_text_overflow),
]


def _run_one_fixer(rule: str, fix_fn, svg_path: Path, review_dir: Path,
                   canvas: tuple[int, int], findings: list[Finding],
                   measurer: "ChromiumMeasurer | None") -> tuple[list[Finding], Path | None, str | None]:
    """Backup -> apply -> re-audit -> commit/rollback for one rule.

    Commits whenever the fix reduced or held steady the HARD finding count —
    partial progress (e.g. 8 of 9 overlaps resolved) is kept rather than
    discarded, since the all-or-nothing bar would throw away real fixes over
    one stubborn remaining instance. Only a regression (more hard findings
    than before) triggers a full rollback to the pre-fix SVG.
    """
    if not any(f.rule == rule for f in findings):
        return findings, None, None
    before_hard = len(_hard(findings))
    backup_dir = review_dir / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{svg_path.stem}.{rule}.preaudit.svg"
    shutil.copy2(svg_path, backup_path)

    tree = ET.parse(svg_path, parser=_svg_parser())
    n = fix_fn(tree, canvas)
    if not n:
        return findings, None, None

    with open(svg_path, "w", encoding="utf-8", newline="\n") as fh:
        tree.write(fh, encoding="unicode", xml_declaration=False)
        fh.write("\n")
    post_findings, _ = audit_page(svg_path, canvas, measurer)
    after_hard = len(_hard(post_findings))

    if after_hard > before_hard:
        shutil.copy2(backup_path, svg_path)
        for f in findings:
            if f.rule == rule:
                f.autofix = "reverted"
        return findings, None, None

    for f in post_findings:
        if f.rule == rule:
            f.autofix = "applied"
    return post_findings, backup_path, f"{rule} x{n}"


def process_page(svg_path: Path, review_dir: Path, canvas: tuple[int, int],
                 autofix: bool, measurer: "ChromiumMeasurer | None" = None) -> dict:
    findings, _tree = audit_page(svg_path, canvas, measurer)
    page = svg_path.name
    backup_path = None
    fixes_applied: list[str] = []

    # Verbatim raw-template pages (stamped by the runner's re-theme stage) carry a
    # professionally-authored, dense flattened layout. D1/D2/D3 relocation fixers
    # misread that density as overlaps/out-of-bounds and would scramble the design,
    # so on these pages only the gentle text-shrink (D4) is allowed, and the
    # relocation *findings* are dropped as false positives.
    verbatim = False
    try:
        verbatim = _tree is not None and _tree.getroot().get("data-verbatim-template") is not None
    except Exception:  # noqa: BLE001
        verbatim = False
    active_fixers = ([(r, fn) for r, fn in _FIXERS if r == "D4_text_overflow"]
                     if verbatim else _FIXERS)

    if autofix:
        for rule, fix_fn in active_fixers:
            findings, bp, label = _run_one_fixer(
                rule, fix_fn, svg_path, review_dir, canvas, findings, measurer)
            if bp:
                backup_path = bp
            if label:
                fixes_applied.append(label)

    if verbatim:
        findings = [f for f in findings if f.rule.startswith("D4")]

    hard = _hard(findings)
    soft = [f for f in findings if f.severity == "soft"]
    result = {
        "page": page,
        "status": "ok" if not hard else "issues",
        "hard": len(hard),
        "soft": len(soft),
        "fixes_applied": fixes_applied,
        "backup": str(backup_path) if backup_path else None,
        "findings": [asdict(f) for f in findings],
    }
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / f"{svg_path.stem}.audit.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Deterministic SVG layout auditor + auto-fixer.")
    ap.add_argument("project_path")
    ap.add_argument("--pages", nargs="+", default=None,
                    help="Page tokens to audit (default: all svg_output/*.svg).")
    ap.add_argument("--no-autofix", action="store_true",
                    help="Detect and report only; never edit SVGs.")
    ap.add_argument("--canvas", default=None, help="Canvas WxH (default 1280x720).")
    ap.add_argument("--backend", choices=["auto", "estimator", "chromium"], default="auto",
                    help="Geometry backend: 'auto' uses exact chromium when available "
                         "(Linux/WSL with playwright) and falls back to the estimator; "
                         "'estimator' forces the dependency-light heuristic; 'chromium' "
                         "requires playwright and errors out if unavailable.")
    args = ap.parse_args()

    project = Path(args.project_path).resolve()
    svg_dir = project / "svg_output"
    if not svg_dir.is_dir():
        print(f"[auditor] no svg_output/ in {project}", file=sys.stderr)
        return 2

    canvas = DEFAULT_CANVAS
    if args.canvas:
        try:
            w, h = args.canvas.lower().split("x")
            canvas = (int(w), int(h))
        except Exception:
            print(f"[auditor] bad --canvas {args.canvas!r}; using {DEFAULT_CANVAS}", file=sys.stderr)

    all_svgs = sorted(svg_dir.glob("*.svg"))
    if args.pages:
        sel = []
        for tok in args.pages:
            m = next((p for p in all_svgs if p.name.startswith(tok) or p.name == tok), None)
            if m:
                sel.append(m)
        all_svgs = sel
    if not all_svgs:
        print(f"[auditor] no SVG pages matched in {svg_dir}", file=sys.stderr)
        return 2

    # Select geometry backend. 'chromium' is a hard requirement; 'auto' tries it
    # and silently falls back; 'estimator' never launches a browser.
    measurer: ChromiumMeasurer | None = None
    if args.backend in ("auto", "chromium"):
        measurer = ChromiumMeasurer()
        if not measurer.start():
            measurer = None
            if args.backend == "chromium":
                _safe_print("--backend chromium requested but playwright/chromium is "
                            "unavailable; install with 'pip install playwright && "
                            "python3 -m playwright install chromium'.")
                return 2
    backend = "chromium" if (measurer and measurer.ok) else "estimator"

    review_dir = project / ".review"
    try:
        results = [process_page(p, review_dir, canvas,
                                autofix=not args.no_autofix, measurer=measurer)
                   for p in all_svgs]
    finally:
        if measurer is not None:
            measurer.close()

    total_hard = sum(r["hard"] for r in results)
    total_soft = sum(r["soft"] for r in results)
    total_fixed = sum(len(r["fixes_applied"]) for r in results)
    summary = {
        "project": str(project),
        "pages_audited": len(results),
        "pages_with_hard_issues": sum(1 for r in results if r["hard"] > 0),
        "total_hard_findings": total_hard,
        "total_soft_findings": total_soft,
        "total_fixes_applied": total_fixed,
        "backend": backend,
        "pages": results,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if total_hard == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
