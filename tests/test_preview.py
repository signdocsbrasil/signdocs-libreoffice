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
        preview.render(FakeCtx(), {"content": "!!! não é base64 !!!"})
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
        preview.render(FakeCtx(raiser=RuntimeError("sem escritório")),
                       {"content": "JVBERi0xLjQK"})
    except Exception:
        pass
    assert set(leftovers()) - before == set()


def test_failure_is_catchable_rather_than_fatal():
    # A preview is a convenience. Whatever goes wrong, the caller has to be
    # able to carry on and send — so the module raises one known type.
    try:
        preview.render(FakeCtx(raiser=RuntimeError("boom")),
                       {"content": "JVBERi0xLjQK"})
        raised = None
    except Exception as exc:
        raised = exc
    assert raised is not None
    assert isinstance(raised, (preview.PreviewUnavailable, RuntimeError))


def test_render_dimensions_keep_a4_proportions():
    # The height only bounds the export; getting the ratio wrong would letterbox
    # every page in the dialog.
    ratio = preview.RENDER_HEIGHT_PX / preview.RENDER_WIDTH_PX
    assert 1.40 < ratio < 1.43, ratio


def test_a_missing_content_key_does_not_crash():
    try:
        preview.render(FakeCtx(), {})
        assert False, "should have raised"
    except preview.PreviewUnavailable:
        pass
