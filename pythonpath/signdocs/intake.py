# SPDX-License-Identifier: MPL-2.0
"""
Turning the open document into the PDF that gets signed.

This is the one place where the LibreOffice channel is simpler than the
ONLYOFFICE one. There, `GetFileToDownload` hands back a *URL* on the
customer's own Document Server which the browser then fetches — which means
checking for a `%PDF-` magic number, because a Document Server error page
arrives as HTTP 200 with HTML in it. Here `storeToURL` writes bytes to a path
we chose, so there is nothing to be lied to about, and the whole export
happens offline.

The export reflects the document as it currently is on screen, unsaved edits
included. That is the intended behaviour: the user is signing what they are
looking at.
"""

import base64
import os
import tempfile
import urllib.parse

from signdocs.config import MAX_BASE64_BYTES

#: Ordered because a Draw document also answers to some Impress services in
#: certain builds; first match wins and the more specific ones come first.
FILTERS = (
    ("com.sun.star.text.TextDocument", "writer_pdf_Export", "writer"),
    ("com.sun.star.sheet.SpreadsheetDocument", "calc_pdf_Export", "calc"),
    ("com.sun.star.presentation.PresentationDocument", "impress_pdf_Export", "impress"),
    ("com.sun.star.drawing.DrawingDocument", "draw_pdf_Export", "draw"),
)

DEFAULT_FILENAME = "documento.pdf"


class UnsupportedDocument(Exception):
    """No PDF export filter for this document type (Base, Math, Start Centre)."""


class DocumentTooLarge(Exception):
    """Over the API's 10MB base64 ceiling."""


class ExportFailed(Exception):
    """LibreOffice refused to write the PDF."""


def _describe(doc):
    for service, filter_name, module in FILTERS:
        try:
            if doc.supportsService(service):
                return filter_name, module
        except Exception:
            # A disposed or otherwise unusable model; treat as unsupported
            # rather than letting an UNO exception escape as a traceback.
            break
    raise UnsupportedDocument(
        "Este tipo de documento não pode ser exportado para PDF. "
        "Abra o arquivo no Writer, Calc, Impress ou Draw."
    )


def filter_for(doc):
    return _describe(doc)[0]


def module_of(doc):
    return _describe(doc)[1]


def filename_for(doc):
    """
    Derive the PDF filename from the document's own URL.

    Parsed with urllib rather than `unohelper.fileUrlToSystemPath` so this
    stays testable without a running office, and so a document that has never
    been saved (empty URL) still gets a sensible name.
    """
    url = ""
    try:
        url = doc.getURL() or ""
    except Exception:
        url = ""

    stem = ""
    if url:
        path = urllib.parse.urlparse(url).path
        base = os.path.basename(urllib.parse.unquote(path))
        stem = os.path.splitext(base)[0]

    if not stem:
        try:
            stem = (getattr(doc, "Title", "") or "").strip()
        except Exception:
            stem = ""
    # A title like "Sem título 1" is still better than nothing, but an empty
    # or path-bearing one is not.
    stem = stem.replace("/", "-").replace("\\", "-").strip()
    if not stem:
        return DEFAULT_FILENAME
    return stem + ".pdf"


def encode(raw):
    """
    Base64-encode, refusing anything the API would reject anyway.

    Checked against the *encoded* length, because that is what the 10MB limit
    in signing-sessions/create.ts actually measures — roughly 7.5MB of PDF.
    Failing here means an immediate, comprehensible message instead of a 400
    after a long upload.
    """
    encoded = base64.b64encode(raw).decode("ascii")
    if len(encoded) > MAX_BASE64_BYTES:
        raise DocumentTooLarge(
            "O documento tem %.1f MB depois da conversão para PDF e o limite é "
            "de %.0f MB. Reduza imagens ou divida o documento."
            % (len(raw) / (1024.0 * 1024.0), MAX_BASE64_BYTES / (1024.0 * 1024.0))
        )
    return encoded


def export_pdf(doc):
    """
    Export the open document to PDF and return
    `{"content": <base64>, "filename": ..., "module": ...}`.

    Blocking and potentially slow on a large document — call it from a worker
    thread, never from the office's dispatch thread.
    """
    # Deferred so this module stays importable without a running office.
    import unohelper
    from com.sun.star.beans import PropertyValue

    filter_name, module = _describe(doc)

    handle, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix="signdocs-")
    os.close(handle)
    try:
        prop = PropertyValue()
        prop.Name = "FilterName"
        prop.Value = filter_name
        try:
            doc.storeToURL(unohelper.systemPathToFileUrl(tmp_path), (prop,))
        except Exception as exc:
            raise ExportFailed(
                "Não foi possível exportar o documento para PDF: {0}".format(exc)
            )

        with open(tmp_path, "rb") as handle:
            raw = handle.read()
    finally:
        # The temp file is a full plaintext copy of the document; it must not
        # outlive this call even when the export failed halfway.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if not raw:
        raise ExportFailed("A exportação para PDF gerou um arquivo vazio.")

    return {
        "content": encode(raw),
        "filename": filename_for(doc),
        "module": module,
    }
