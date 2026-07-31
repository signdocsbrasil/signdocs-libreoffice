# SPDX-License-Identifier: MPL-2.0
"""
Command router. `signdocs_addon.py` resolves a dispatch URL to a bare command
name and hands it here.

Every entry point is a placeholder in 0.1.0 — the scaffold exists so the
registration chain (Addons.xcu → ProtocolHandler.xcu → Python component) can be
proven on a real LibreOffice before any logic is written on top of it. Silent
registration failures are the dominant failure mode for office extensions, so
they get validated first.
"""

import json
import os
import sys

from signdocs import __version__, paths
from signdocs.ui import msgbox

_TODO = (
    "Ainda não implementado nesta versão de desenvolvimento ({v}).\n\n"
    "Comando: {cmd}"
)


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
    doc = frame.getController().getModel() if frame else None
    if doc is None:
        msgbox.error(ctx, frame, "Nenhum documento aberto.")
        return

    title = getattr(doc, "Title", "") or "(sem título)"
    msgbox.info(
        ctx,
        frame,
        "Documento: {0}\n\n{1}".format(
            title, _TODO.format(v=__version__, cmd="Enviar")
        ),
    )


def _historico(ctx, frame):
    msgbox.info(ctx, frame, _TODO.format(v=__version__, cmd="Historico"))


def _configurar(ctx, frame):
    msgbox.info(ctx, frame, _TODO.format(v=__version__, cmd="Configurar"))


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
    from signdocs import config, oauth
    from signdocs.httpclient import _cacert_path, ssl_context
    report["ca_bundle"] = _cacert_path()
    report["ca_bundle_present"] = os.path.exists(_cacert_path())
    try:
        report["ca_roots"] = len(ssl_context().get_ca_certs())
    except Exception as exc:
        report["ca_roots"] = None
        report["errors"].append("ca bundle: {0}".format(exc))

    endpoints = config.STAGES[config.current_stage(_store_or_none(ctx))]
    report["stage"] = config.current_stage(_store_or_none(ctx))
    report["auth_host"] = endpoints["auth"]
    try:
        metadata = oauth.discover(endpoints)
        report["auth_reachable"] = True
        report["auth_issuer"] = (metadata or {}).get("issuer")
    except Exception as exc:
        report["auth_reachable"] = False
        report["auth_error"] = "{0}: {1}".format(type(exc).__name__, exc)

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
