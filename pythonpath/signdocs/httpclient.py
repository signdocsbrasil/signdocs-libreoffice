# SPDX-License-Identifier: MPL-2.0
"""
HTTP over the standard library only.

LibreOffice ships its own Python with no pip, so `requests` is not an option
and neither is the official signdocs-brasil SDK that depends on it. This is
the whole networking layer: urllib plus a vendored CA bundle.

Nothing here retries. The two calls this module was written for — the OAuth
token exchange and the refresh — both consume single-use credentials, and a
retry after an ambiguous failure would burn a code or a rotated refresh token
that the server has already invalidated. Retry policy belongs with the
callers that can afford it, on idempotent requests, with an idempotency key.
"""

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_TIMEOUT = 30
USER_AGENT = "SignDocsBrasil-LibreOffice"

_ssl_context = None


def _cacert_path():
    """vendor/cacert.pem, relative to this file inside the extension."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "vendor", "cacert.pem"))


def ssl_context():
    """
    Verifying context built on the vendored Mozilla bundle.

    Falls back to the platform default when the bundle is missing — never to
    an unverified context. A missing bundle should degrade to "works wherever
    the platform trust store works", not to "trusts anything".
    """
    global _ssl_context
    if _ssl_context is None:
        cafile = _cacert_path()
        if os.path.exists(cafile):
            _ssl_context = ssl.create_default_context(cafile=cafile)
        else:
            _ssl_context = ssl.create_default_context()
    return _ssl_context


class HttpError(Exception):
    """Non-2xx response. `payload` is the decoded JSON body when there is one."""

    def __init__(self, status, message, payload=None, url=None):
        Exception.__init__(self, message)
        self.status = status
        self.message = message
        self.payload = payload or {}
        self.url = url

    def error_code(self):
        return self.payload.get("error") or self.payload.get("code")


class NetworkError(Exception):
    """The request never got a response: DNS, TLS, timeout, proxy."""


def _decode(raw):
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def _message_from(payload, fallback):
    if not isinstance(payload, dict):
        return fallback
    for key in ("message", "error_description", "error", "detail"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return fallback


def request(url, method="GET", body=None, headers=None, timeout=DEFAULT_TIMEOUT):
    """
    Perform one request. Returns the decoded JSON body, or None for an empty
    response. Raises HttpError on a non-2xx and NetworkError on no response.
    """
    all_headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    all_headers.update(headers or {})

    req = urllib.request.Request(url, data=body, method=method)
    for name, value in all_headers.items():
        req.add_header(name, value)

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
            return _decode(resp.read())
    except urllib.error.HTTPError as exc:
        payload = _decode(exc.read())
        raise HttpError(
            exc.code,
            _message_from(payload, "HTTP %s" % exc.code),
            payload,
            url,
        )
    except urllib.error.URLError as exc:
        raise NetworkError(str(getattr(exc, "reason", exc)))
    except (ssl.SSLError, OSError) as exc:
        raise NetworkError(str(exc))


def post_json(url, payload, headers=None, timeout=DEFAULT_TIMEOUT):
    body = json.dumps(payload).encode("utf-8")
    merged = {"Content-Type": "application/json"}
    merged.update(headers or {})
    return request(url, "POST", body, merged, timeout)


def post_form(url, fields, headers=None, timeout=DEFAULT_TIMEOUT):
    """
    Form-encoded POST.

    The token endpoint enforces application/x-www-form-urlencoded and rejects
    JSON, so this is not interchangeable with post_json.
    """
    body = urllib.parse.urlencode(fields).encode("utf-8")
    merged = {"Content-Type": "application/x-www-form-urlencoded"}
    merged.update(headers or {})
    return request(url, "POST", body, merged, timeout)


def get_json(url, headers=None, timeout=DEFAULT_TIMEOUT):
    return request(url, "GET", None, headers, timeout)
