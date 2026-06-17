"""Regression tests for leaf-<path> transform handling in svg_to_pptx.

convert_path historically honored only translate()/rotate() and silently dropped
matrix()/scale(), collapsing flipped/scaled geometry to the origin (the "broken
pyramid in PPTX" bug — the powerslides boat-tier pyramids use matrix(1 0 0 -1 e f)).
These assert the full affine is now baked into the path coordinates.
"""
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

_SCRIPTS = (Path(__file__).resolve().parents[2]
            / "core-ppt-master-engine" / "skills" / "ppt-master" / "scripts")
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

pytestmark = pytest.mark.skipif(
    not (_SCRIPTS / "svg_to_pptx").is_dir(), reason="svg_to_pptx package not available")

NS = "http://www.w3.org/2000/svg"
EMU = 9525.0  # EMU per pixel


def _bounds_px(path_xml: str):
    from svg_to_pptx import drawingml_elements as E
    from svg_to_pptx.drawingml_context import ConvertContext
    res = E.convert_path(ET.fromstring(path_xml), ConvertContext())
    assert res is not None and res.bounds_emu is not None
    x0, y0, x1, y1 = res.bounds_emu
    return (x0 / EMU, y0 / EMU, x1 / EMU, y1 / EMU)


def test_vertical_flip_matrix_is_applied():
    # apex trapezoid of 06_segmented_pyramid: matrix(1 0 0 -1 370.5 294.5)
    # raw band y∈[0,102] flips+translates to y∈[192.5,294.5]; x→[370.5,494.5]
    xml = (f'<path xmlns="{NS}" d="M0 102 25.5 0 98.5 0 124 102Z" '
           f'transform="matrix(1 0 0 -1 370.5 294.5)"/>')
    x0, y0, x1, y1 = _bounds_px(xml)
    assert abs(x0 - 370.5) < 1 and abs(x1 - 494.5) < 1
    assert abs(y0 - 192.5) < 1 and abs(y1 - 294.5) < 1


def test_flip_not_collapsed_to_origin():
    # The pre-fix bug: a flipped path rendered at the origin. Guard against regress.
    xml = (f'<path xmlns="{NS}" d="M0 102 25.5 0 98.5 0 124 102Z" '
           f'transform="matrix(1 0 0 -1 370.5 294.5)"/>')
    x0, y0, _, _ = _bounds_px(xml)
    assert x0 > 100 and y0 > 100  # clearly NOT at (0,0)


def test_scale_matrix_is_applied():
    xml = f'<path xmlns="{NS}" d="M0 0 10 0 10 10Z" transform="scale(3)"/>'
    x0, y0, x1, y1 = _bounds_px(xml)
    assert abs(x0) < 1 and abs(y0) < 1 and abs(x1 - 30) < 1 and abs(y1 - 30) < 1


def test_translate_only_fast_path_unchanged():
    xml = f'<path xmlns="{NS}" d="M0 0 10 0 10 10Z" transform="translate(100 50)"/>'
    x0, y0, _, _ = _bounds_px(xml)
    assert abs(x0 - 100) < 1 and abs(y0 - 50) < 1


def test_no_transform_stays_at_raw_coords():
    xml = f'<path xmlns="{NS}" d="M5 5 15 5 15 15Z"/>'
    x0, y0, _, _ = _bounds_px(xml)
    assert abs(x0 - 5) < 1 and abs(y0 - 5) < 1
