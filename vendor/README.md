# vendor/

## cacert.pem

Mozilla's CA root bundle, as distributed by the curl project.

- Source: <https://curl.se/ca/cacert.pem>
- Licence: MPL-2.0 — the same licence as this extension
- Refresh: `curl -fsSL https://curl.se/ca/cacert.pem -o vendor/cacert.pem`

### Why this is vendored

LibreOffice bundles its own Python on Windows and macOS. That interpreter has
no `certifi`, and on macOS its OpenSSL has no path to the system keychain, so
`ssl.create_default_context()` can come up with an empty trust store and every
HTTPS call fails with `CERTIFICATE_VERIFY_FAILED`. It is one of the
best-documented sharp edges in desktop Python.

Shipping the bundle makes TLS verification deterministic and identical on
Linux, Windows and macOS, instead of depending on how a particular office
build was assembled. `signdocs/httpclient.py` passes it as `cafile` explicitly.

**This never disables verification.** If the bundle is somehow missing,
`httpclient` falls back to the platform default context — it does not fall
back to an unverified connection.

### Keeping it current

A stale bundle fails *closed*: a newly cross-signed root simply is not trusted
yet, so the call errors rather than silently accepting a bad certificate.
Refresh it when a release is cut, and note the "Certificate data from Mozilla
as of" date at the top of the file in the release notes.
