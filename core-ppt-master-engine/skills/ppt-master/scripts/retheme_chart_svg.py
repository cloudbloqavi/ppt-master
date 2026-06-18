#!/usr/bin/env python3
"""
Deterministic chart-SVG re-theme — adapt a *verbatim* template to a project's
theme (colors AND typography) without redrawing it.

Some company catalog templates (``powerslides_infographics/``) are raw PowerPoint
exports: polished, but filter-laden and far too complex for the model to redraw
faithfully (it gives up and free-designs, losing the distinctive infographic — see
``lint_chart_catalog.py``). The reliable path is to keep such a template **pixel-for-
pixel verbatim** (executor copies it and edits only ``<text>`` content) and let the
*runner* re-theme it mechanically here — so the slide both looks like the original
AND adopts the project palette + fonts.

This is a pure find-and-map over the SVG's fixed, tiny style vocabulary: a raw
export typically uses < 10 distinct hex colors and a handful of font families. It
never moves geometry, never edits text, never rescales (sizes stay verbatim so
nothing reflows), and is deterministic — same input + theme ⇒ same output. That is
the whole point: the previous "let the model re-skin it" attempt was unreliable; a
script over a dozen tokens is not.

Mapping strategy (role-based, palette-agnostic):

  Colors — split into **neutrals** (low saturation) and **chromatics**.
    * Neutrals map onto the theme neutral ramp by **luminance** (white→bg, light
      grey→surface/border, mid grey→muted, near-black→ink): lightness, and thus
      contrast, is preserved rather than reshuffled.
    * Chromatics map onto the theme accents by **prominence** (most-used template
      color → primary accent, next → secondary…): the template's hierarchy is kept.

  Fonts — classify each family and map to the matching typography role:
    * monospace  → code_family
    * serif      → title_family (the deck's display face)
    * sans-serif → body_family  (the deck's default)
    ``font-weight`` attributes are left untouched, so a "Lato Black"→body swap still
    renders bold via its explicit weight; the visual hierarchy survives.

CLI (prototyping / validation / runner use):
    python3 retheme_chart_svg.py in.svg out.svg --spec-lock <project>/spec_lock.md
    python3 retheme_chart_svg.py in.svg out.svg --colors bg=#FFF,primary=#0F2942,... \
                                                --fonts body_family="Inter,sans-serif",...

Prints a JSON report (color + font mappings) so the re-theme is auditable.
"""
from __future__ import annotations

import argparse
import colorsys
import json
import re
import sys
from collections import Counter
from pathlib import Path

# ───────────────────────────── colors ─────────────────────────────

# Any hex color, 3- or 6-digit, wherever it appears (fill/stroke/stop-color/style).
_HEX_RE = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")

# Saturation at/above which a color is "chromatic" (a brand hue) vs a neutral
# (white/grey/black). 0.18 keeps off-whites and warm-greys neutral while catching
# real brand colors.
_SAT_CHROMATIC = 0.18

# Theme role → ordering. Neutral ramp is matched by luminance; chromatic ramp by
# template-color prominence. Missing roles are skipped, so any spec_lock subset works.
_NEUTRAL_ROLES = ["bg", "secondary_bg", "border", "text_secondary", "text", "primary"]
_CHROMATIC_ROLES = ["accent", "secondary_accent", "primary"]


def _norm_hex(h: str) -> str:
    h = h.lstrip("#").lower()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h


def _rgb(h: str) -> tuple[float, float, float]:
    h = _norm_hex(h).lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _luminance(h: str) -> float:
    r, g, b = _rgb(h)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _saturation(h: str) -> float:
    r, g, b = _rgb(h)
    return colorsys.rgb_to_hsv(r, g, b)[1]


def collect_colors(svg_text: str) -> Counter:
    counts: Counter = Counter()
    for m in _HEX_RE.finditer(svg_text):
        counts[_norm_hex(m.group(0))] += 1
    return counts


def build_color_mapping(template_colors: Counter, theme: dict[str, str]) -> dict[str, str]:
    """Map each template color → a theme color, by role (see module docstring).

    Pure function of (colors, theme): testable, deterministic, and it never invents
    a color — absent roles are skipped and empty ramps leave colors unchanged.
    """
    neutrals: list[str] = []
    chromatics: list[tuple[int, str]] = []
    for color, n in template_colors.items():
        if _saturation(color) >= _SAT_CHROMATIC:
            chromatics.append((n, color))
        else:
            neutrals.append(color)

    def ramp(roles: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for r in roles:
            hexv = theme.get(r)
            if hexv and hexv not in seen:
                seen.add(hexv)
                out.append(hexv)
        return out

    neutral_ramp = ramp(_NEUTRAL_ROLES)
    chromatic_ramp = ramp(_CHROMATIC_ROLES)
    mapping: dict[str, str] = {}

    # Neutrals → nearest theme neutral by luminance (preserves lightness/contrast).
    if neutral_ramp and neutrals:
        for color in neutrals:
            lum = _luminance(color)
            mapping[color] = min(neutral_ramp, key=lambda h: abs(_luminance(h) - lum))

    # Chromatics → theme accents by prominence (most-used first), cycling.
    if chromatic_ramp and chromatics:
        chromatics.sort(key=lambda t: t[0], reverse=True)
        for i, (_n, color) in enumerate(chromatics):
            mapping[color] = chromatic_ramp[i % len(chromatic_ramp)]

    return {k: v for k, v in mapping.items() if k != v}


# ─────────────────────────── typography ───────────────────────────

# font-family in either attribute (font-family="...") or style (font-family:...;) form.
_FONT_ATTR_RE = re.compile(r'font-family\s*=\s*"([^"]*)"')
_FONT_STYLE_RE = re.compile(r'font-family\s*:\s*([^;"\']+)')

_MONO_HINTS = ("mono", "consolas", "courier", "menlo", "monaco", "lucida console", "source code")
_SERIF_HINTS = ("serif", "georgia", "times", "garamond", "cambria", "merriweather",
                "playfair", "pt serif", "noto serif")


def classify_font(value: str) -> str:
    """Return 'code' | 'title' | 'body' for a font-family stack value."""
    v = value.lower()
    if any(h in v for h in _MONO_HINTS):
        return "code"
    # A stack ending in 'sans-serif' is sans even though it contains the substring
    # 'serif' — check sans-serif first.
    if "sans-serif" in v or "sans serif" in v:
        return "body"
    if any(h in v for h in _SERIF_HINTS):
        return "title"
    return "body"


def collect_fonts(svg_text: str) -> Counter:
    counts: Counter = Counter()
    for m in _FONT_ATTR_RE.finditer(svg_text):
        counts[m.group(1).strip()] += 1
    for m in _FONT_STYLE_RE.finditer(svg_text):
        counts[m.group(1).strip()] += 1
    return counts


def _role_stack(role: str, typo: dict[str, str]) -> str | None:
    """Resolve a classified role to a concrete theme stack, with sensible fallbacks."""
    fallbacks = {
        "code": ("code_family", "font_family", "body_family"),
        "title": ("title_family", "emphasis_family", "font_family", "body_family"),
        "body": ("body_family", "font_family"),
    }[role]
    for key in fallbacks:
        if typo.get(key):
            return typo[key]
    return None


def build_font_mapping(template_fonts: Counter, typo: dict[str, str]) -> dict[str, str]:
    """Map each template font-family value → the project's stack for its role."""
    mapping: dict[str, str] = {}
    for value in template_fonts:
        stack = _role_stack(classify_font(value), typo)
        if stack:
            # Emit family names with single quotes: the SVG embeds these in a
            # double-quoted font-family="..." attribute, so internal double quotes
            # ("Microsoft YaHei") would prematurely close the attribute.
            stack = stack.replace('"', "'")
            if stack != value:
                mapping[value] = stack
    return mapping


def apply_color_mapping(svg_text: str, mapping: dict[str, str]) -> str:
    def repl(m: re.Match) -> str:
        return mapping.get(_norm_hex(m.group(0)), m.group(0))
    return _HEX_RE.sub(repl, svg_text)


def apply_font_mapping(svg_text: str, mapping: dict[str, str]) -> str:
    def attr_repl(m: re.Match) -> str:
        return f'font-family="{mapping.get(m.group(1).strip(), m.group(1))}"'

    def style_repl(m: re.Match) -> str:
        cur = m.group(1).strip()
        return f"font-family:{mapping.get(cur, cur)}"

    out = _FONT_ATTR_RE.sub(attr_repl, svg_text)
    return _FONT_STYLE_RE.sub(style_repl, out)


# ─────────────────────────── orchestration ───────────────────────────

def retheme_svg(svg_text: str, colors: dict[str, str],
                typo: dict[str, str]) -> tuple[str, dict]:
    """Return (rethemed_svg, report). Either of colors/typo may be empty."""
    color_map = build_color_mapping(collect_colors(svg_text), colors) if colors else {}
    font_map = build_font_mapping(collect_fonts(svg_text), typo) if typo else {}
    out = apply_color_mapping(svg_text, color_map) if color_map else svg_text
    out = apply_font_mapping(out, font_map) if font_map else out
    return out, {"color_mapping": color_map, "font_mapping": font_map,
                 "colors_remapped": len(color_map), "fonts_remapped": len(font_map)}


def retheme_file(svg_in: Path, svg_out: Path, colors: dict[str, str],
                 typo: dict[str, str]) -> dict:
    text = svg_in.read_text(encoding="utf-8")
    rethemed, report = retheme_svg(text, colors, typo)
    svg_out.write_text(rethemed, encoding="utf-8")
    report.update({"input": str(svg_in), "output": str(svg_out)})
    return report


# ─────────────────────────── spec_lock parsing ───────────────────────────

def _parse_block(text: str, header: str, key_re: str) -> dict[str, str]:
    out: dict[str, str] = {}
    in_block = False
    pat = re.compile(key_re)
    for line in text.splitlines():
        s = line.strip()
        if s.lower().startswith(header):
            in_block = True
            continue
        if in_block:
            if s.startswith("## "):
                break
            m = pat.match(s)
            if m:
                # Keep the value verbatim (no quote stripping): font stacks contain
                # internal quotes ("Microsoft YaHei", ...) that must be preserved.
                out[m.group(1).lower()] = m.group(2).strip()
    return out


def parse_spec_lock(spec_lock_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return (colors, typography) from a spec_lock.md. Missing file ⇒ ({}, {})."""
    try:
        text = spec_lock_path.read_text(encoding="utf-8")
    except OSError:
        return {}, {}
    colors_raw = _parse_block(text, "## colors", r"-\s*([A-Za-z0-9_]+)\s*:\s*(#[0-9a-fA-F]{3,6})")
    colors = {k: _norm_hex(v) for k, v in colors_raw.items()}
    # typography: only the *_family / font_family rows are stacks we remap.
    typo_all = _parse_block(text, "## typography", r"-\s*([A-Za-z0-9_]+)\s*:\s*(.+)")
    typo = {k: v for k, v in typo_all.items() if k.endswith("family")}
    return colors, typo


def _parse_kv_arg(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in raw.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Deterministically re-theme a chart SVG "
                                             "(colors + typography) without redrawing.")
    ap.add_argument("svg_in", type=Path)
    ap.add_argument("svg_out", type=Path)
    ap.add_argument("--spec-lock", type=Path, help="project spec_lock.md (## colors + ## typography)")
    ap.add_argument("--colors", type=str, help="role=hex,... overrides/supplies colors")
    ap.add_argument("--fonts", type=str, help="role=stack,... overrides/supplies typography")
    args = ap.parse_args(argv)

    colors: dict[str, str] = {}
    typo: dict[str, str] = {}
    if args.spec_lock:
        colors, typo = parse_spec_lock(args.spec_lock)
    if args.colors:
        colors.update({k: _norm_hex(v) for k, v in _parse_kv_arg(args.colors).items()})
    if args.fonts:
        typo.update(_parse_kv_arg(args.fonts))

    if not colors and not typo:
        print("retheme: no theme resolved (need --spec-lock/--colors/--fonts).", file=sys.stderr)
        return 1

    report = retheme_file(args.svg_in, args.svg_out, colors, typo)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
