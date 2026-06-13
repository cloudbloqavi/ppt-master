#!/usr/bin/env python3
"""
Chart Catalog Lint — enforces the "clean, adaptable starting point" contract.

The company catalog (`templates/charts/powerslides_infographics/`) is consumed by
the Executor, which must batch-read each referenced template into context and
*adapt* it (executor-base.md §1.0 / §5). Raw PowerPoint→SVG exports break that
contract: they are huge, single-line, and packed with `<filter>`/`feGaussianBlur`
constructs that (a) blow the context budget, (b) are banned by `svg_quality_checker`,
and (c) are too complex for the model to faithfully reproduce — so it silently
falls back to free design and the distinctive infographic is lost.

This linter rejects those fingerprints so a raw export can never re-enter the
catalog unnoticed. Run standalone or via `run_agent.py --self-test`.

Exit code: 0 = clean, 1 = at least one ERROR.
"""
import re
import sys
from pathlib import Path

# Hard size ceiling. Clean authored templates sit at 6–12 KB; anything materially
# larger is either a raw export or too token-heavy to adapt faithfully.
MAX_BYTES_ERROR = 20_000
MAX_BYTES_WARN = 15_000

# Raw-export fingerprints — any hit is a hard error.
_BANNED_CONSTRUCTS = (
    "<filter",          # PPTX export drop-shadows/glows; banned by quality checker
    "feGaussianBlur",
    "feComponentTransfer",
    "data:image",       # embedded base64 raster — never belongs in a vector template
    "<foreignObject",
    "<style",
)


def _default_catalog_dir() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "templates" / "charts" / "powerslides_infographics"
    )


def lint_catalog(catalog_dir: Path | None = None) -> tuple[list[str], list[str]]:
    """Lint every *.svg in the catalog. Returns (errors, warnings)."""
    catalog_dir = catalog_dir or _default_catalog_dir()
    errors: list[str] = []
    warnings: list[str] = []

    if not catalog_dir.exists():
        return ([f"catalog dir not found: {catalog_dir}"], [])

    svgs = sorted(catalog_dir.glob("*.svg"))
    if not svgs:
        return ([f"no SVG templates found in {catalog_dir}"], [])

    for svg in svgs:
        name = svg.name
        raw = svg.read_bytes()
        size = len(raw)
        text = raw.decode("utf-8", errors="ignore")

        # 1. Banned raw-export constructs (the precise raw-PPTX-export fingerprint;
        #    every catalog SVG is minified single-line, so line count is NOT a
        #    discriminator — filter/blur/base64 constructs are).
        for token in _BANNED_CONSTRUCTS:
            if token in text:
                errors.append(
                    f"{name}: contains banned construct '{token}' - looks like a raw "
                    f"PowerPoint export; re-author as a clean vector template."
                )

        # 2. Missing viewBox.
        if "viewBox" not in text:
            errors.append(f"{name}: missing viewBox attribute.")

        # 3. Size budget — token-heavy templates the Executor can't adapt faithfully.
        if size > MAX_BYTES_ERROR:
            errors.append(
                f"{name}: {size} bytes exceeds hard limit {MAX_BYTES_ERROR} - too "
                f"token-heavy for the Executor to adapt faithfully."
            )
        elif size > MAX_BYTES_WARN:
            warnings.append(f"{name}: {size} bytes exceeds soft limit {MAX_BYTES_WARN}.")

    return (errors, warnings)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    catalog_dir = Path(argv[0]).resolve() if argv else None
    errors, warnings = lint_catalog(catalog_dir)

    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  ERROR {e}")

    if errors:
        print(f"\nChart catalog lint FAILED: {len(errors)} error(s), {len(warnings)} warning(s).")
        return 1
    print(f"Chart catalog lint passed ({len(warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
