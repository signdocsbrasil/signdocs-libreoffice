# SPDX-License-Identifier: MPL-2.0
"""
Standalone health check for a machine we cannot log into.

Runs the extension's *real* networking modules straight out of the .oxt under
whichever interpreter it is given — the point is to run it under LibreOffice's
own bundled Python, because that interpreter is the unknown. On Windows and
macOS the office ships its own build with no pip and, on macOS, no path to the
system keychain; `CERTIFICATE_VERIFY_FAILED` there is the single most likely
first-run failure and it looks identical to "the server is down".

Deliberately does not need a running office or a UNO bridge. The dispatch layer
has its own gate (`bin/smoke_probe.py` via `SelfTest`); this one has to work on
a locked-down desktop where the office may not even start, and anything that
could hang would defeat the purpose.

Reads the .oxt as a zip rather than the installed copy, so it still reports
when installation itself is what failed.

    python.exe bin\\diagnostico.py [--stage hml]
"""

import io
import json
import os
import platform
import shutil
import socket
import sys
import tempfile
import zipfile

REPORT_NAME = "signdocs-diagnostico.json"


def _find_oxt(start):
    for directory in (start, os.path.dirname(start)):
        if not os.path.isdir(directory):
            continue
        names = sorted(
            n for n in os.listdir(directory)
            if n.startswith("signdocs-brasil-") and n.endswith(".oxt")
        )
        if names:
            return os.path.join(directory, names[-1])
    return None


def _probe(url, context, timeout=20):
    """
    Any HTTP status counts as reachable.

    The question is whether DNS, the proxy, TCP and TLS all worked — not
    whether the endpoint liked the request. An unauthenticated call answering
    401 has proved everything being asked here.
    """
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": "SignDocsBrasil-diag"})
    try:
        response = urllib.request.urlopen(request, timeout=timeout, context=context)
        return {"ok": True, "status": response.getcode()}
    except urllib.error.HTTPError as exc:
        return {"ok": True, "status": exc.code}
    except Exception as exc:
        return {"ok": False, "error": "{0}: {1}".format(type(exc).__name__, exc)}


def main(argv):
    stage = "hml"
    if "--stage" in argv:
        stage = argv[argv.index("--stage") + 1]

    here = os.path.dirname(os.path.abspath(__file__))
    report = {
        "stage": stage,
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "is_office_python": "libreoffice" in (sys.executable or "").lower()
        or "openoffice" in (sys.executable or "").lower(),
        "errors": [],
    }

    # A corporate proxy that intercepts TLS is the other classic first-run
    # failure, and it is invisible unless asked for by name.
    report["proxy_env"] = {
        k: v for k, v in os.environ.items()
        if k.lower() in ("http_proxy", "https_proxy", "no_proxy", "all_proxy")
    }

    oxt = _find_oxt(here)
    report["oxt"] = oxt
    if not oxt:
        report["errors"].append(
            "no signdocs-brasil-*.oxt found next to this script"
        )
        _emit(report, here)
        return 1

    workdir = tempfile.mkdtemp(prefix="signdocs-diag-")
    try:
        with zipfile.ZipFile(oxt) as archive:
            archive.extractall(workdir)
        sys.path.insert(0, os.path.join(workdir, "pythonpath"))

        try:
            from signdocs import __version__, config
            from signdocs.httpclient import _cacert_path, ssl_context
        except Exception as exc:
            report["errors"].append("import from .oxt: {0}".format(exc))
            _emit(report, here)
            return 1

        report["extension_version"] = __version__

        try:
            import ssl
            report["openssl"] = ssl.OPENSSL_VERSION
        except Exception as exc:
            report["openssl"] = None
            report["errors"].append("ssl: {0}".format(exc))

        # The vendored bundle is what makes TLS deterministic across platforms.
        # If it is missing the code falls back to the platform store, which is
        # exactly the macOS/Windows case that breaks, so report both facts.
        cafile = _cacert_path()
        report["ca_bundle"] = cafile
        report["ca_bundle_present"] = os.path.exists(cafile)
        try:
            context = ssl_context()
            report["ca_roots"] = len(context.get_ca_certs())
        except Exception as exc:
            context = None
            report["ca_roots"] = None
            report["errors"].append("ca bundle: {0}".format(exc))

        endpoints = config.STAGES.get(stage)
        if endpoints is None:
            report["errors"].append("unknown stage {0!r}".format(stage))
            _emit(report, here)
            return 1
        report["login_host"] = endpoints["login"]
        report["api_host"] = endpoints["api"]

        report["reachability"] = {
            "login": _probe(endpoints["login"], context),
            "api": _probe(
                endpoints["api"] + config.API_PREFIX + "/init-session", context
            ),
        }
        for name, result in report["reachability"].items():
            if not result["ok"]:
                report["errors"].append("{0} unreachable: {1}".format(name, result["error"]))

        # The loopback listener is the one piece that a desktop firewall or a
        # port already in use can break, and it fails at the worst moment —
        # after the user has already typed their password in the browser.
        free = []
        for port in config.LOOPBACK_PORTS:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind((config.LOOPBACK_HOST, port))
                free.append(port)
            except Exception:
                pass
            finally:
                sock.close()
        report["loopback_ports_free"] = free
        if not free:
            report["errors"].append(
                "every loopback port {0} is in use; sign-in cannot complete".format(
                    list(config.LOOPBACK_PORTS)
                )
            )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    _emit(report, here)
    return 1 if report["errors"] else 0


def _emit(report, directory):
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    target = os.path.join(directory, REPORT_NAME)
    try:
        with io.open(target, "w", encoding="utf-8") as handle:
            handle.write(text)
        print("\nRelatorio salvo em: {0}".format(target))
    except Exception as exc:
        print("\n(nao foi possivel salvar o relatorio: {0})".format(exc))

    if report["errors"]:
        print("\n*** {0} PROBLEMA(S) ***".format(len(report["errors"])))
        for error in report["errors"]:
            print("  - {0}".format(error))
    else:
        print("\nTudo certo: TLS, rede e portas de login OK nesta maquina.")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
