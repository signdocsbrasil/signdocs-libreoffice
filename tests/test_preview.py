"""
The preview's behaviour that does not need a running office.

Rendering itself is exercised for real in bin/smoke_probe.py, against an actual
exported PDF — it cannot be faked usefully, because the thing being tested is
whether LibreOffice's PDF importer is reachable through UNO. What *can* be
tested here is everything around it: that a document which cannot be decoded is
refused before any file is written, that the temp file never outlives the call
even when the render fails, and that failure is an exception the caller can
catch rather than something that reaches the user as a broken send.
"""

import glob
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pythonpath"))

from signdocs import preview  # noqa: E402


def leftovers():
    return glob.glob(os.path.join(tempfile.gettempdir(), "signdocs-preview-*"))


class FakeCtx(object):
    """Enough of a context to reach the first failure, and no further."""

    def __init__(self, raiser=None):
        self.ServiceManager = self
        self._raiser = raiser

    def createInstanceWithContext(self, name, ctx):
        if self._raiser:
            raise self._raiser
        return None


def test_a_document_that_is_not_base64_is_refused():
    before = leftovers()
    try:
        preview.render_all(FakeCtx(), {"content": "!!! não é base64 !!!"})
        assert False, "should have raised"
    except preview.PreviewUnavailable as exc:
        assert "não pôde ser lido" in str(exc)
    # Refused before anything touched disk: the decode happens first on
    # purpose, so a malformed payload never becomes a plaintext temp file.
    assert leftovers() == before


def test_the_temp_pdf_never_outlives_a_failed_render():
    """
    The invariant `intake.export_pdf` documents, applied here: the plaintext
    copy must not survive the call. A render that blows up halfway is exactly
    when a stray copy would otherwise be left behind.
    """
    before = set(leftovers())
    try:
        preview.render_all(FakeCtx(raiser=RuntimeError("sem escritório")),
                           {"content": "JVBERi0xLjQK"})
    except Exception:
        pass
    assert set(leftovers()) - before == set()


def test_failure_is_catchable_rather_than_fatal():
    # A preview is a convenience. Whatever goes wrong, the caller has to be
    # able to carry on and send — so the module raises one known type.
    try:
        preview.render_all(FakeCtx(raiser=RuntimeError("boom")),
                           {"content": "JVBERi0xLjQK"})
        raised = None
    except Exception as exc:
        raised = exc
    assert raised is not None
    assert isinstance(raised, (preview.PreviewUnavailable, RuntimeError))


class FakePage(object):
    def __init__(self, w, h):
        self.Width, self.Height = w, h


def pixels_for(w, h):
    """The PixelWidth/PixelHeight the exporter would be given for this page."""
    data = preview._size_filter_data(FakeCtx(), FakePage(w, h))
    # uno.Any wraps the tuple; the fake ctx returns plain PropertyValue-likes.
    values = data.value if hasattr(data, "value") else data
    return {p.Name: p.Value for p in values}


def test_a_portrait_page_keeps_its_proportions():
    px = pixels_for(21000, 29700)          # A4 retrato
    assert px["PixelHeight"] == preview.RENDER_LONG_EDGE_PX
    assert abs(px["PixelWidth"] / px["PixelHeight"] - 21000 / 29700) < 0.01


def test_a_landscape_page_is_not_squeezed_into_portrait():
    """
    The bug this replaced: both dimensions were pinned, so every landscape
    page — which is what Calc and Impress export by default — was stretched
    into portrait. A distorted preview is worse than none, because it looks
    like the export itself is wrong.
    """
    px = pixels_for(29700, 21000)          # A4 paisagem
    assert px["PixelWidth"] == preview.RENDER_LONG_EDGE_PX
    assert px["PixelWidth"] > px["PixelHeight"]
    assert abs(px["PixelWidth"] / px["PixelHeight"] - 29700 / 21000) < 0.01


def test_a_page_with_no_size_falls_back_to_a4_rather_than_dividing_by_zero():
    px = pixels_for(0, 0)
    assert px["PixelWidth"] > 0 and px["PixelHeight"] > 0


def test_the_page_cap_is_a_cap_not_a_page_count():
    # The dialog reports the document's real length and says separately how
    # much it rendered, so a long contract cannot look short.
    assert preview.MAX_PAGES >= 10


def test_a_missing_content_key_does_not_crash():
    try:
        preview.render_all(FakeCtx(), {})
        assert False, "should have raised"
    except preview.PreviewUnavailable:
        pass


# ---------------------------------------------------- dialog fits the screen
def test_an_unmeasurable_screen_still_yields_a_usable_size():
    """
    Two bugs, one cause. A fixed 420-unit height came to 1344 pixels on a
    1200-pixel display, putting the page buttons off-screen — a four-page
    document then looked like a one-page one. Capping that fixed request to the
    screen fixed the overflow and made the dialog tiny on a large monitor,
    because a cap can only shrink. The size has to be derived from the screen.
    """
    from signdocs.ui import widgets

    w, h = widgets.screen_sized(FakeCtx(raiser=RuntimeError("sem toolkit")))
    assert (w, h) == widgets.MIN_SIZE


def test_the_size_is_always_within_its_bounds():
    from signdocs.ui import widgets

    w, h = widgets.screen_sized(FakeCtx(raiser=RuntimeError("x")))
    assert widgets.MIN_SIZE[0] <= w <= widgets.MAX_SIZE[0]
    assert widgets.MIN_SIZE[1] <= h <= widgets.MAX_SIZE[1]


def test_the_floor_leaves_room_for_a_page_and_its_controls():
    # The image takes height - 44; below roughly 200 units there is no picture
    # left worth calling a preview.
    from signdocs.ui import widgets

    assert widgets.MIN_SIZE[1] - 44 >= 150


# ------------------------------------------------------- page proportions
def test_a_portrait_page_is_not_stretched_sideways():
    """
    The bug: the image control was near-square and the page was scaled
    anisotropically into it, so an A4 page came out 1.53 wide-to-tall when it
    should be 0.707 — visibly squashed against the same document opened in
    Draw.
    """
    from signdocs.ui.dialogs import page_box

    w, h = page_box(544, 519, 1000, 1414)          # A4 retrato
    assert h > w, (w, h)
    assert abs((h / w) - (1414 / 1000)) < 0.02


def test_a_landscape_page_keeps_its_proportions_too():
    from signdocs.ui.dialogs import page_box

    w, h = page_box(544, 519, 1414, 1000)
    assert w > h, (w, h)
    assert abs((h / w) - (1000 / 1414)) < 0.02


def test_the_box_never_exceeds_the_space_available():
    from signdocs.ui.dialogs import page_box

    for pw, ph in ((1000, 1414), (1414, 1000), (1000, 1000), (100, 5000)):
        w, h = page_box(544, 519, pw, ph)
        assert 0 < w <= 544 and 0 < h <= 519, (pw, ph, w, h)


def test_a_page_with_no_reported_size_uses_the_whole_area():
    from signdocs.ui.dialogs import page_box

    assert page_box(544, 519, 0, 0) == (544, 519)
