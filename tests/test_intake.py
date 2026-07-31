# SPDX-License-Identifier: MPL-2.0
"""
Document export.

`export_pdf` itself needs a running office and is covered by the smoke test;
everything around it — filter selection, filename derivation, the size
ceiling — is pure and is covered here, because those are the parts that decide
whether the API call succeeds at all.
"""

import base64

import pytest

from signdocs import intake
from signdocs.config import MAX_BASE64_BYTES


class StubDoc(object):
    def __init__(self, services=(), url="", title=""):
        self._services = set(services)
        self._url = url
        self.Title = title

    def supportsService(self, name):  # noqa: N802 - UNO API name
        return name in self._services

    def getURL(self):  # noqa: N802 - UNO API name
        return self._url


WRITER = "com.sun.star.text.TextDocument"
CALC = "com.sun.star.sheet.SpreadsheetDocument"
IMPRESS = "com.sun.star.presentation.PresentationDocument"
DRAW = "com.sun.star.drawing.DrawingDocument"


@pytest.mark.parametrize("service,expected_filter,expected_module", [
    (WRITER, "writer_pdf_Export", "writer"),
    (CALC, "calc_pdf_Export", "calc"),
    (IMPRESS, "impress_pdf_Export", "impress"),
    (DRAW, "draw_pdf_Export", "draw"),
])
def test_each_module_maps_to_its_pdf_filter(service, expected_filter, expected_module):
    doc = StubDoc([service])
    assert intake.filter_for(doc) == expected_filter
    assert intake.module_of(doc) == expected_module


def test_impress_wins_over_draw_when_a_document_answers_to_both():
    # An Impress document also supports the drawing service; the more
    # specific filter has to be chosen or slides export as a Draw page.
    doc = StubDoc([IMPRESS, DRAW])
    assert intake.filter_for(doc) == "impress_pdf_Export"


def test_a_document_with_no_pdf_filter_is_refused():
    # Base and Math reach the menu only if Context is wrong, but a clear
    # message beats an UNO traceback either way.
    with pytest.raises(intake.UnsupportedDocument):
        intake.filter_for(StubDoc(["com.sun.star.sdb.OfficeDatabaseDocument"]))


def test_a_disposed_document_is_refused_not_crashed():
    class Disposed(object):
        def supportsService(self, name):  # noqa: N802
            raise RuntimeError("disposed")

    with pytest.raises(intake.UnsupportedDocument):
        intake.filter_for(Disposed())


# ------------------------------------------------------------- filenames
def test_filename_comes_from_the_document_url():
    doc = StubDoc([WRITER], url="file:///home/ana/Contratos/contrato.odt")
    assert intake.filename_for(doc) == "contrato.pdf"


def test_filename_unescapes_percent_encoding():
    doc = StubDoc([WRITER], url="file:///home/ana/contrato%20de%20presta%C3%A7%C3%A3o.odt")
    assert intake.filename_for(doc) == "contrato de prestação.pdf"


def test_unsaved_document_falls_back_to_its_title():
    doc = StubDoc([WRITER], url="", title="Sem título 1")
    assert intake.filename_for(doc) == "Sem título 1.pdf"


def test_unsaved_and_untitled_document_gets_a_default_name():
    assert intake.filename_for(StubDoc([WRITER])) == "documento.pdf"


def test_separators_never_survive_into_the_filename():
    # The filename is echoed back by the API and shown in e-mails; a path
    # fragment in it is at best confusing.
    doc = StubDoc([WRITER], url="", title="a/b\\c")
    assert "/" not in intake.filename_for(doc)
    assert "\\" not in intake.filename_for(doc)


def test_a_url_with_no_basename_falls_back():
    assert intake.filename_for(StubDoc([WRITER], url="file:///")) == "documento.pdf"


# ------------------------------------------------------------------ size
def test_encode_returns_base64():
    assert base64.b64decode(intake.encode(b"%PDF-1.7 hello")) == b"%PDF-1.7 hello"


def test_encode_refuses_a_document_over_the_api_ceiling():
    # The limit is measured on the *encoded* length, which is what
    # signing-sessions/create.ts checks — about 7.5MB of actual PDF.
    raw = b"x" * (int(MAX_BASE64_BYTES * 3 / 4) + 1024)
    with pytest.raises(intake.DocumentTooLarge) as excinfo:
        intake.encode(raw)
    # The message has to be actionable, not just "too large".
    assert "MB" in str(excinfo.value)


def test_encode_accepts_a_document_just_under_the_ceiling():
    raw = b"x" * (int(MAX_BASE64_BYTES * 3 / 4) - 1024)
    assert len(intake.encode(raw)) <= MAX_BASE64_BYTES
