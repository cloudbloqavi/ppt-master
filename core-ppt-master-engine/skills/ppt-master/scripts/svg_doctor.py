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

    # Mirrored / inverted geometry: matrix(a b c d e f) with negative x/y scale,
    # or scale() with a negative factor. This is the pyramid-flip class of bug —
    # often a verbatim copy from a raw export that renders inverted. Cannot be
    # auto-fixed: the flip may be intentional, so a human/AI must verify orientation.
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
        out.append(Finding("review", "mirrored_transform", "warning",
                           f"{flips} element(s) use a mirrored/flipped transform "
                           "(matrix with negative scale or scale(-...)). Verify orientation -"
                           "this is the pyramid-inversion class of bug; fix by re-orienting paths, "
                           "not by blind removal.", flips))

    # Raw PowerPoint export markers -filter-laden, hard to adapt/reproduce cleanly.
    raw = sum(1 for _, el in ((_strip_ns(e.tag), e) for e in root.iter())
              if _strip_ns(el.tag) in _RAW_MARKERS)
    n_elems = sum(1 for _ in root.iter())
    if raw and n_elems > 300:
        out.append(Finding("review", "raw_export", "warning",
                           f"Looks like a raw export: {raw} filter primitive(s) and {n_elems} elements. "
                           "May not reproduce cleanly when mimicked -consider a clean redraw.", raw))

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
            out.append(Finding("review", "out_of_bounds", "warning",
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
        out.append(Finding("review", "orphan_baseline", "warning",
                           f"{orphan} text element(s) appear to render from y=0 (orphan baseline) -"
                           "the recurring overlap cause; verify vertical placement.", orphan))

    if n_elems > 1500:
        out.append(Finding("review", "heavy_svg", "warning",
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


def review(path: Path, do_fix: bool) -> tuple[list[Finding], str | None]:
    """Return (findings, fixed_text|None). fixed_text is None unless do_fix changed something."""
    original = path.read_text(encoding="utf-8", errors="replace")
    fixed_text, autofix_findings = _detect_and_fix(original, do_fix)
    # Re-parse the (possibly fixed) text for the review-class structural checks.
    review_findings = _detect_review(fixed_text, _parse(fixed_text))
    findings = autofix_findings + review_findings
    changed = do_fix and fixed_text != original
    return findings, (fixed_text if changed else None)


def _print_report(path: Path, findings: list[Finding], fixed: bool) -> None:
    # ASCII-only output: this runs in Windows cp1252 consoles where box-drawing /
    # check glyphs raise UnicodeEncodeError.
    autofix = [f for f in findings if f.cls == "autofix"]
    rev = [f for f in findings if f.cls == "review"]
    print(f"\nsvg_doctor -- {path.name}")
    print("-" * 64)
    if not findings:
        print("  [OK] clean -- no workflow-affecting issues found.")
        return
    label = "FIXED" if fixed else "AUTO-FIXABLE"
    if autofix:
        print(f"  {label} ({len(autofix)}):")
        for f in autofix:
            mark = "[fixed]" if fixed else "-"
            print(f"    {mark} [{f.severity}] {f.code}: {f.message}")
    if rev:
        print(f"  NEEDS REVIEW -- not auto-fixed ({len(rev)}):")
        for f in rev:
            print(f"    [!] [{f.severity}] {f.code}: {f.message}")
    if autofix and not fixed:
        print("\n  Run again with --fix to apply the auto-fixable items.")


def main(argv: list[str]) -> int:
    # Best-effort UTF-8 stdout so any non-ASCII in messages prints on Windows
    # cp1252 consoles instead of raising UnicodeEncodeError.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Lint/auto-fix a single SVG for PPTX-workflow safety.")
    ap.add_argument("svg", help="path to the .svg file")
    ap.add_argument("--fix", action="store_true", help="apply auto-fixable issues (REVIEW items are never touched)")
    ap.add_argument("-o", "--output", help="write fixed SVG here instead of in place (implies --fix)")
    ap.add_argument("--json", action="store_true", help="emit findings as JSON")
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

    if args.json:
        print(json.dumps({
            "file": str(path),
            "fixed": fixed_text is not None,
            "output": (args.output or str(path)) if fixed_text is not None else None,
            "findings": [f.as_dict() for f in findings],
        }, indent=2))
    else:
        _print_report(path, findings, fixed=fixed_text is not None)

    remaining_review = [f for f in findings if f.cls == "review"]
    return 1 if remaining_review else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
