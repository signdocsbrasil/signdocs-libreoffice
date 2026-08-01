# SPDX-License-Identifier: MPL-2.0
"""
Command router. `signdocs_addon.py` resolves a dispatch URL to a bare command
name and hands it here.

The `ui` package is imported lazily inside each handler rather than at module
scope. That keeps this module importable without a running office, which is
what lets the dispatch chain be tested before any dialog exists — and it means
a failure while building a dialog surfaces as an error box from
`signdocs_addon.dispatch`, not as an import error nobody sees.
"""

import json
import os
import sys

from signdocs import __version__, paths
from signdocs.ui import msgbox


def run(ctx, frame, command):
    if command == "Enviar":
        _enviar(ctx, frame)
    elif command == "Historico":
        _historico(ctx, frame)
    elif command == "Configurar":
        _configurar(ctx, frame)
    elif command == "SelfTest":
        _selftest(ctx, frame)
    else:
        msgbox.error(
            ctx, frame, "Comando desconhecido: {0!r}".format(command)
        )


def _enviar(ctx, frame):
    from signdocs.ui import dialogs

    dialogs.run_send(ctx, frame, dialogs.store_for(ctx))


def _historico(ctx, frame):
    from signdocs.ui import dialogs

    dialogs.run_history(ctx, frame, dialogs.store_for(ctx))


def _configurar(ctx, frame):
    from signdocs.ui import dialogs

    dialogs.run_settings(ctx, frame, dialogs.store_for(ctx))


def _store_or_none(ctx):
    """
    The profile-backed store, or an empty in-memory one if the profile is
    unreadable. The self-test must survive exactly the conditions it exists to
    diagnose, so it never lets a broken profile stop the report.
    """
    from signdocs.store import JsonStore

    try:
        return JsonStore(paths.state_file(ctx))
    except Exception:
        return JsonStore()


def _probe(url):
    """
    Touch a URL and treat any HTTP response as success.

    The question this answers is "can this machine reach SignDocs at all" —
    DNS, proxy, TLS — not "is the endpoint happy". An unauthenticated call
    returning 401 proves everything this is checking.
    """
    import urllib.request

    from signdocs.httpclient import USER_AGENT, ssl_context

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        urllib.request.urlopen(request, timeout=15, context=ssl_context()).read(1)
    except urllib.error.HTTPError:
        return  # a status is an answer
    return


def _selftest(ctx, frame):
    """
    Headless-safe health check. Writes its result to the user profile instead
    of showing a dialog, because it has two jobs and neither can pop UI:

      * CI asserts the whole chain end to end — dispatch reached Python, the
        pythonpath/ package imported, and the profile directory resolved and is
        writable. queryDispatch alone proves none of that.
      * Support can ask a customer to run it on a locked-down desktop where the
        interesting failures (no pyuno, read-only profile, missing stdlib TLS)
        happen before any dialog could be drawn.

    Deliberately not in Addons.xcu: dispatch-only, so it adds no UI surface.
    """
    report = {
        "extension_version": __version__,
        "python_version": sys.version,
        "user_dir": None,
        "modules": {},
        "errors": [],
    }

    for name in ("ssl", "urllib.request", "http.server", "webbrowser",
                 "secrets", "hashlib", "base64", "json", "threading"):
        try:
            __import__(name)
            report["modules"][name] = True
        except Exception as exc:  # pragma: no cover - platform dependent
            report["modules"][name] = False
            report["errors"].append("import {0}: {1}".format(name, exc))

    try:
        import ssl
        report["openssl"] = ssl.OPENSSL_VERSION
    except Exception:
        report["openssl"] = None

    # Reach the authorization server for real. On a corporate desktop the
    # first thing that breaks is TLS — a bundled Python with no trust store
    # (macOS), or an intercepting proxy presenting its own root — and it
    # breaks identically for every SignDocs call afterwards. Recording the
    # exact error here saves a support round-trip.
    #
    # Never fatal: a machine that is simply offline still gets a report.
    from signdocs import config
    from signdocs.httpclient import _cacert_path, ssl_context
    report["ca_bundle"] = _cacert_path()
    report["ca_bundle_present"] = os.path.exists(_cacert_path())
    try:
        report["ca_roots"] = len(ssl_context().get_ca_certs())
    except Exception as exc:
        report["ca_roots"] = None
        report["errors"].append("ca bundle: {0}".format(exc))

    stage = config.current_stage(_store_or_none(ctx))
    report["stage"] = stage
    report["login_host"] = config.COGNITO["domain"]
    report["api_host"] = config.STAGES[stage]["api"]

    # Any HTTP status means DNS, TCP and TLS all worked, which is what this is
    # actually diagnosing. A 401 or 404 is a perfectly good answer here — only
    # the absence of a response tells us something is wrong.
    for label, url in (("login", report["login_host"]),
                       ("api", report["api_host"] + config.API_PREFIX + "/init-session")):
        try:
            _probe(url)
            report[label + "_reachable"] = True
        except Exception as exc:
            report[label + "_reachable"] = False
            report[label + "_error"] = "{0}: {1}".format(type(exc).__name__, exc)

    try:
        report["user_dir"] = paths.user_dir(ctx)
        target = paths.selftest_file(ctx)
        # Set before the dump, not after: the flag has to be inside the file,
        # which is the only thing a caller ever sees.
        report["profile_writable"] = True
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    except Exception as exc:
        report["profile_writable"] = False
        report["errors"].append("write profile: {0}".format(exc))
        # Nowhere to persist the result, so this one has to be spoken aloud.
        msgbox.error(ctx, frame, "Autoteste falhou: {0}".format(exc))
        return

    if frame is not None and os.environ.get("SIGNDOCS_SELFTEST_QUIET") != "1":
        msgbox.info(
            ctx,
            frame,
            "Autoteste concluído.\n\nRelatório: {0}".format(target),
        )
