#!/usr/bin/env python3
# SPDX-License-Identifier: MPL-2.0
"""
Ask LibreOffice's own update machinery to read our published feed.

Every installed .oxt polls the URL baked into its `description.xml`, and that
URL cannot be corrected afterwards for anyone who already installed — so the
feed being consumable is the one thing that has to be right before the first
user exists. It is also the only way to ship a fix without waiting on the
extensions.libreoffice.org moderation queue, which has no published SLA.

Nothing about that is provable by fetching the URL with curl and reading the
XML by eye. What matters is whether `UpdateInformationProvider` — the exact
service the Extension Manager's "Check for Updates" drives — can fetch it,
parse it, and hand back an entry for OUR identifier. A malformed document, the
wrong namespace, a TLS chain the office rejects, or an identifier that does not
match all fail here and are invisible to a human reading the file.

Run through bin/update-feed-check.sh, which boots the office for it.

Usage: update_feed_probe.py <uno-port> [feed-url] [extension-id]
"""

import sys
import xml.etree.ElementTree as ET

import uno
from com.sun.star.connection import NoConnectException

DEFAULT_FEED = "https://cdn.signdocs.com.br/libreoffice/update.xml"
DESCRIPTION_NS = {"d": "http://openoffice.org/extensions/description/2006"}

failures = []


def check(label, condition, detail=""):
    mark = "ok " if condition else "FAIL"
    print("  %s %s%s" % (mark, label, ("  -- %s" % detail) if detail else ""))
    if not condition:
        failures.append(label)


def connect(port):
    ctx = uno.getComponentContext()
    resolver = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", ctx)
    url = ("uno:socket,host=127.0.0.1,port=%s;urp;"
           "StarOffice.ComponentContext" % port)
    return resolver.resolve(url)


def local_description():
    """The identifier and version this working tree would build."""
    root = ET.parse("description.xml").getroot()
    return (root.find("d:identifier", DESCRIPTION_NS).get("value"),
            root.find("d:version", DESCRIPTION_NS).get("value"))


def text_of(element, tag):
    """
    Read one child of the update entry.

    The feed is in the 2006 update namespace, but the DOM the office hands back
    is a plain XElement tree, so children are matched by local name rather than
    by a namespace-qualified lookup — the namespace has already done its job by
    the time the document parses.
    """
    children = element.getElementsByTagName(tag)
    if not children.getLength():
        return ""
    node = children.item(0)
    # Both `identifier` and `version` carry their payload in a `value`
    # attribute, exactly as description.xml does — not as text content. Reading
    # them as text yields an empty string, which looks like "the feed omits a
    # version" rather than "the probe looked in the wrong place".
    value = node.getAttribute("value")
    if value:
        return value
    first = node.getFirstChild()
    return (first.getNodeValue() or "").strip() if first else ""


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "2104"
    feed = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_FEED

    ident, local_version = local_description()
    extension_id = sys.argv[3] if len(sys.argv) > 3 else ident

    print("feed:      %s" % feed)
    print("extensão:  %s" % extension_id)
    print("versão local: %s" % local_version)
    print()

    try:
        ctx = connect(port)
    except NoConnectException:
        print("FAIL: nenhum escritório na porta %s" % port)
        return 1

    smgr = ctx.ServiceManager
    provider = smgr.createInstanceWithContext(
        "com.sun.star.deployment.UpdateInformationProvider", ctx)
    check("o escritório expõe UpdateInformationProvider", provider is not None)
    if provider is None:
        return 1

    # This is the call the Extension Manager makes. It performs the fetch, the
    # parse and the identifier match in one step, which is why it is worth
    # more than any amount of reading the XML.
    try:
        entries = provider.getUpdateInformation((feed,), extension_id)
    except Exception as exc:                       # noqa: BLE001
        check("o escritório busca e interpreta o feed", False,
              "%s: %s" % (type(exc).__name__, exc))
        return 1

    check("o escritório busca e interpreta o feed", True)
    check("o feed traz uma entrada para esta extensão",
          entries is not None and len(entries) > 0,
          "%d entrada(s)" % (len(entries) if entries else 0))
    if not entries:
        # An empty result is the silent failure this whole script exists for:
        # the URL answered, the XML parsed, and the identifier did not match,
        # so every installed copy would poll forever and never see an update.
        return 1

    element = entries[0]
    published_id = text_of(element, "identifier")
    published_version = text_of(element, "version")
    href = ""
    downloads = element.getElementsByTagName("src")
    if downloads.getLength():
        href = downloads.item(0).getAttribute("xlink:href") \
            or downloads.item(0).getAttribute("href")

    check("o identificador publicado é o desta extensão",
          published_id == extension_id,
          "%r vs %r" % (published_id, extension_id))
    check("o feed declara uma versão", bool(published_version),
          published_version)
    # Rule 1 from the feed's own header: <version> must equal description.xml's.
    # Higher than what is downloadable makes every client offer an update that
    # then fails to install.
    check("a versão do feed é a mesma do description.xml",
          published_version == local_version,
          "feed=%s description=%s" % (published_version, local_version))
    check("o feed aponta para um .oxt", href.endswith(".oxt"), href)
    # Rule 2: the .oxt must already be uploaded. A feed naming a file that is
    # not there is an error message on every desktop.
    check("o .oxt nomeado tem a versão anunciada",
          published_version in href, href)

    print()
    if failures:
        print("FALHOU: %d verificação(ões)" % len(failures))
        return 1
    print("PASSOU")
    return 0


if __name__ == "__main__":
    sys.exit(main())
