# SPDX-License-Identifier: MPL-2.0
"""
Render a page of the exported PDF, so the sender sees the bytes rather than a
filename.

The review screen used to name the document and list the signers, which catches
a wrong recipient but never a wrong *document*. The failure it could not catch
is the one the export path makes possible: each module reaches PDF by its own
filter (`intake.FILTERS`), and a spreadsheet can paginate across sheets or a
drawing can export the wrong area, silently. By then the invitations are out and
the quota is spent.

## Why it renders through the office rather than a library

`bin/check-oxt.sh` asserts the package imports nothing third-party, so pypdfium
and PyMuPDF are out. The office already has a PDF importer, and it is reached
through UNO like everything else here.

## Why it goes via a temp file

Loading `private:stream` with `draw_pdf_import` **crashes the office** — an
assertion failure on a null `SvStream` inside LibreOffice, not an exception this
code could catch. Measured on 25.8; feeding it a file URL instead works.

Writing the PDF out is not a new exposure: `intake.export_pdf` already writes
exactly these bytes to a temp file and deletes them inside the same call. The
rule is that the plaintext copy must not outlive the call, and it does not — the
`finally` here removes it before the caller sees a result. The rendered page
travels back as an in-memory `XGraphic`, so nothing derived from the document
stays on disk either.

## Why it may be unavailable

The PDF importer is a separate package on some distributions
(`libreoffice-pdfimport` on Fedora, `libreoffice-draw` elsewhere). A preview is
a convenience: when the importer is missing, the caller says so and the send
continues. It must never become a reason a document cannot be sent.
"""

import base64
import os
import tempfile

#: Longest edge of a rendered page. Applied to whichever edge is longer so a
#: landscape page is not squeezed into portrait — forcing both dimensions
#: stretched every Calc and Impress export, which are routinely landscape.
RENDER_LONG_EDGE_PX = 1400

#: Pages rendered in one pass. A preview exists to catch a wrong export, and
#: that is visible in the first pages; rendering a 200-page contract in full
#: would stall the dialog for no added confidence. The dialog says when it has
#: stopped short rather than pretending the document ends here.
MAX_PAGES = 25


class PreviewUnavailable(Exception):
    """No preview is possible here. Never fatal to a send."""


def _prop(ctx, name, value):
    from com.sun.star.beans import PropertyValue
    p = PropertyValue()
    p.Name = name
    p.Value = value
    return p


def _drain(pipe):
    """Read a com.sun.star.io.Pipe to the end as bytes."""
    chunks = []
    while True:
        read, chunk = pipe.readBytes(None, 65536)
        if read <= 0:
            break
        chunks.append(bytes(chunk.value if hasattr(chunk, "value") else chunk))
    return b"".join(chunks)


def render_all(ctx, document, limit=MAX_PAGES):
    """
    Render up to `limit` pages, importing the PDF exactly once.

    Returns `(graphics, page_count)` — `graphics` is a list of XGraphic, one per
    rendered page, and `page_count` is how many pages the document really has,
    which may be larger.

    One import for the whole document, not one per page. The previous shape
    re-imported and re-parsed the entire PDF on every page turn, which is both
    slow and pointless: the expensive half is the import. Paging then costs
    nothing, so the dialog does not need a progress dialog nested inside its own
    modal loop to turn a page.

    Blocking and slow — worker thread only, never the office's dispatch thread.
    """
    try:
        raw = base64.b64decode(document["content"])
    except Exception:
        raise PreviewUnavailable("O PDF exportado não pôde ser lido.")

    # Imported after the decode, not before: refusing a malformed payload is
    # pure logic and must not depend on a live UNO bridge. `unohelper` exists
    # only inside the office's own Python, so importing it first made the
    # refusal path — and its tests — require a running office to reach.
    #
    # A missing bridge is reported as the preview being unavailable, which is
    # what it is. Letting ImportError escape would make the one failure the
    # caller is written to absorb arrive as a type it does not catch.
    try:
        import unohelper
    except ImportError:
        raise PreviewUnavailable(
            "A pré-visualização não está disponível nesta instalação.")

    smgr = ctx.ServiceManager
    handle, path = tempfile.mkstemp(suffix=".pdf", prefix="signdocs-preview-")
    os.close(handle)
    doc = None
    try:
        with open(path, "wb") as fh:
            fh.write(raw)

        desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        try:
            doc = desktop.loadComponentFromURL(
                unohelper.systemPathToFileUrl(path), "_blank", 0,
                (_prop(ctx, "FilterName", "draw_pdf_import"),
                 _prop(ctx, "Hidden", True),
                 _prop(ctx, "ReadOnly", True)))
        except Exception as exc:
            raise PreviewUnavailable(str(exc))
        if doc is None:
            # What a missing PDF importer looks like: no exception, no document.
            raise PreviewUnavailable("O visualizador de PDF não está instalado.")

        pages = doc.DrawPages
        count = pages.Count
        if count < 1:
            raise PreviewUnavailable("O PDF exportado não tem páginas.")

        graphics = []
        for index in range(min(count, max(1, int(limit)))):
            page = pages.getByIndex(index)
            png = _page_png(ctx, smgr, page)
            graphics.append(_graphic_from_png(ctx, png))
        return graphics, count
    finally:
        # Close before unlinking: the importer holds the file open, and on
        # Windows a delete underneath it fails outright.
        if doc is not None:
            try:
                doc.close(False)
            except Exception:
                pass
        try:
            os.unlink(path)
        except OSError:
            pass


def _page_png(ctx, smgr, page):
    """One page to PNG bytes, at the page's own proportions."""
    pipe = smgr.createInstanceWithContext("com.sun.star.io.Pipe", ctx)
    exporter = smgr.createInstanceWithContext(
        "com.sun.star.drawing.GraphicExportFilter", ctx)
    exporter.setSourceDocument(page)
    exporter.filter((
        _prop(ctx, "FilterName", "PNG"),
        _prop(ctx, "OutputStream", pipe),
        _prop(ctx, "FilterData", _size_filter_data(ctx, page)),
    ))
    png = _drain(pipe)
    if not png.startswith(b"\x89PNG"):
        raise PreviewUnavailable("A página não pôde ser convertida em imagem.")
    return png


def _size_filter_data(ctx, page):
    """
    Pixel size for this page, keeping its own proportions.

    `page.Width`/`page.Height` are in 1/100 mm and describe the real page, so
    the ratio comes from the document rather than from an assumption about A4.
    Setting both dimensions to fixed values — which this used to do — stretches
    anything that is not portrait A4, and Calc and Impress export landscape as
    a matter of course.
    """
    import uno
    px_w, px_h = render_pixels(getattr(page, "Width", 0), getattr(page, "Height", 0))
    return uno.Any("[]com.sun.star.beans.PropertyValue", (
        _prop(ctx, "PixelWidth", px_w),
        _prop(ctx, "PixelHeight", px_h),
    ))


def render_pixels(width, height):
    """
    (PixelWidth, PixelHeight) for a page of `width` x `height` (1/100 mm).

    Separate from `_size_filter_data` because this is the part that can be
    wrong: the ratio arithmetic decides whether a landscape page comes out
    landscape. Welded to the `uno.Any` call it could only be tested inside a
    running office, so it was never checked by CI — which is exactly where a
    silent regression to "pin both dimensions" would reappear.

    A page reporting no size falls back to A4 rather than dividing by zero.
    """
    width = int(width) or 21000
    height = int(height) or 29700
    if width >= height:
        px_w = RENDER_LONG_EDGE_PX
        px_h = max(1, int(round(RENDER_LONG_EDGE_PX * height / float(width))))
    else:
        px_h = RENDER_LONG_EDGE_PX
        px_w = max(1, int(round(RENDER_LONG_EDGE_PX * width / float(height))))
    return px_w, px_h


def page_box(max_w, max_h, page_w, page_h):
    """
    The largest box inside `max_w` x `max_h` with the page's proportions.

    Falls back to the whole area when the page reports no size, which is no
    worse than before and never returns something with a zero edge.

    Lives here rather than in `ui.dialogs` for the same reason as
    `render_pixels`: it is pure geometry, and the `ui` package imports `uno` at
    module scope, so anything inside it can only be tested with a live office.
    This is the arithmetic that decides whether a page is drawn in proportion —
    getting it wrong is what squashed A4 into a near-square control — so it
    belongs where the test suite can actually reach it.
    """
    if page_w > 0 and page_h > 0:
        ratio = float(page_h) / float(page_w)
        box_h = min(max_h, int(round(max_w * ratio)))
        box_w = min(max_w, int(round(box_h / ratio)) if ratio else max_w)
        return max(1, box_w), max(1, box_h)
    return max_w, max_h


def _graphic_from_png(ctx, png):
    """
    PNG bytes -> XGraphic, in memory.

    An image control can be given a `Graphic` directly, so the picture never
    needs a URL and therefore never needs a file. Writing the rendered page out
    would put a readable copy of the document back on disk, which is the thing
    this module is careful not to do.
    """
    import uno
    smgr = ctx.ServiceManager
    stream = smgr.createInstanceWithContext(
        "com.sun.star.io.SequenceInputStream", ctx)
    stream.initialize((uno.ByteSequence(png),))
    provider = smgr.createInstanceWithContext(
        "com.sun.star.graphic.GraphicProvider", ctx)
    graphic = provider.queryGraphic((_prop(ctx, "InputStream", stream),))
    if graphic is None:
        raise PreviewUnavailable("A imagem da página não pôde ser carregada.")
    return graphic
