"""Hebrew text helpers in src/common.py."""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import common  # noqa: E402


def test_he_renders_right_to_left():
    # "מי" = wide mem, then narrow yod. Read right to left, the mem must be on the
    # right, whichever path he() takes (native bidi in matplotlib or python-bidi).
    # Compared with "ימ" (same letters reversed), the mem must sit further right.
    assert common.ink_centre(common.he("מי")) > common.ink_centre(common.he("ימ"))


def test_probe_matches_figure_output():
    # In the Hebrew figures, the first word of a label must be drawn on the right.
    # "מדד" (wide) followed by "י" (narrow): the ink leans right only if RTL works.
    assert common.ink_centre(common.he("מדד י")) > common.ink_centre(common.he("י מדד"))


def test_protocol_text_falls_back_to_english():
    proto = {"title": "English title", "question": " English question\n"}
    assert common.protocol_text(proto, "title") == "English title"
    assert common.protocol_text({**proto, "title_he": "כותרת"}, "title") == "כותרת"
    assert common.protocol_text(proto, "question") == "English question"
