#!/usr/bin/env bash
#
# Archive-shape gate. The bugs this catches do not raise errors at install
# time — the extension installs cleanly and simply does nothing. Both sibling
# repos shipped exactly that class of defect (the ONLYOFFICE {GUID} directory,
# the Nextcloud composer/ vendor-dir), so the archive gets asserted, not
# assumed.
#
# The last check is a real `unopkg add` into a throwaway user profile. Unit
# tests cannot see registration failures; only the office can.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$PWD"

fail() { echo "FAIL: $*" >&2; exit 1; }
ok()   { echo "  ok  $*"; }

VERSION="$(python3 - <<'PY'
import xml.etree.ElementTree as ET
ns = {'d': 'http://openoffice.org/extensions/description/2006'}
print(ET.parse('description.xml').getroot().find('d:version', ns).get('value'))
PY
)"
IDENTIFIER="$(python3 - <<'PY'
import xml.etree.ElementTree as ET
ns = {'d': 'http://openoffice.org/extensions/description/2006'}
print(ET.parse('description.xml').getroot().find('d:identifier', ns).get('value'))
PY
)"
OXT="signdocs-brasil-${VERSION}.oxt"

echo "checking $OXT  (identifier $IDENTIFIER)"
[ -f "$OXT" ] || fail "$OXT not found — run bin/build-oxt.sh first"

# ---------------------------------------------------------------- 1. version
PYVER="$(python3 -c "
import re,io
src = io.open('pythonpath/signdocs/__init__.py', encoding='utf-8').read()
print(re.search(r'__version__\s*=\s*[\"\']([^\"\']+)', src).group(1))
")"
[ "$PYVER" = "$VERSION" ] \
	|| fail "version drift: description.xml=$VERSION __init__.py=$PYVER"
ok "version $VERSION consistent across description.xml and __init__.py"

# ------------------------------------------------------- 2. archive contents
LISTING="$(mktemp)"; trap 'rm -f "$LISTING"' EXIT
unzip -Z1 "$OXT" > "$LISTING"

for required in description.xml META-INF/manifest.xml Addons.xcu ProtocolHandler.xcu \
                signdocs_addon.py pythonpath/signdocs/__init__.py LICENSE \
                vendor/cacert.pem; do
	grep -qxF "$required" "$LISTING" || fail "missing from archive: $required"
done
ok "required members present"

# Without the bundle, LibreOffice's own Python on macOS has no trust store at
# all and every HTTPS call fails. httpclient falls back to the platform default
# rather than to an unverified connection, but shipping without it silently
# breaks a whole platform.
python3 - <<'PY' || exit 1
import ssl, sys
try:
    ctx = ssl.create_default_context(cafile='vendor/cacert.pem')
except Exception as exc:
    sys.stderr.write('FAIL: vendor/cacert.pem is not a usable CA bundle: %s\n' % exc)
    sys.exit(1)
count = len(ctx.get_ca_certs())
if count < 50:
    sys.stderr.write('FAIL: vendor/cacert.pem holds only %d certs; looks truncated\n' % count)
    sys.exit(1)
print('  ok  vendor/cacert.pem loads (%d roots)' % count)
PY

# description.xml must be at the archive root, not nested one level down.
grep -qE '^[^/]+/description\.xml$' "$LISTING" \
	&& fail "description.xml is nested — .oxt members must sit at the archive root"
ok "members are at the archive root"

# ------------------------------------- 3. every manifest entry really exists
python3 - "$LISTING" <<'PY' || exit 1
import sys, xml.etree.ElementTree as ET
NS = {'m': 'http://openoffice.org/2001/manifest'}
listing = set(open(sys.argv[1]).read().split())
missing = []
for e in ET.parse('META-INF/manifest.xml').getroot().findall('m:file-entry', NS):
    path = e.get('{http://openoffice.org/2001/manifest}full-path')
    if path not in listing:
        missing.append(path)
if missing:
    sys.stderr.write('FAIL: manifest.xml lists files absent from the archive: %s\n' % missing)
    sys.exit(1)
print('  ok  every manifest.xml file-entry exists in the archive')
PY

# ------------------------------------------------ 4. dev artefacts excluded
while read -r entry; do
	case "$entry" in
		bin/*|tests/*|.github/*|CLAUDE.md|pyproject.toml|*/__pycache__/*|*.pyc|.git/*)
			fail "development artefact shipped: $entry" ;;
	esac
done < "$LISTING"
ok "no development artefacts in the archive"

# The extension must have no third-party Python dependencies: LibreOffice ships
# its own interpreter with no pip, so anything not in the stdlib is unavailable
# on a customer's machine no matter what a manifest claims.
python3 - <<'PY' || exit 1
import ast, os, sys

STDLIB_OK = set(sys.stdlib_module_names) if hasattr(sys, 'stdlib_module_names') else None
ALLOWED = {'signdocs', 'uno', 'unohelper', 'com'}
offenders = []
for root, _, files in os.walk('pythonpath'):
    for name in files:
        if not name.endswith('.py'):
            continue
        path = os.path.join(root, name)
        tree = ast.parse(open(path, encoding='utf-8').read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name.split('.')[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module.split('.')[0]]
            else:
                continue
            for mod in mods:
                if mod in ALLOWED:
                    continue
                if STDLIB_OK is not None and mod not in STDLIB_OK:
                    offenders.append('%s: %s' % (path, mod))
if offenders:
    sys.stderr.write('FAIL: non-stdlib import(s): %s\n' % offenders)
    sys.exit(1)
print('  ok  no third-party Python imports')
PY

# ------------------------------------------------------------ 5. air-gap gate
# Every UI asset must resolve inside the extension. A remote icon or dialog
# resource would leave the panel blank on the offline BR-gov installs this
# extension exists to reach. Remote API/auth endpoints are expected and are not
# what this checks.
python3 - <<'PY' || exit 1
import re, sys
bad = []
for f in ('Addons.xcu', 'description.xml'):
    for m in re.finditer(r'<value>\s*(https?://[^<]+)</value>', open(f, encoding='utf-8').read()):
        bad.append((f, m.group(1)))
for m in re.finditer(r'xlink:href="(https?://[^"]+)"', open('description.xml', encoding='utf-8').read()):
    url = m.group(1)
    # publisher homepage and the update feed are metadata, not loaded assets.
    if not url.startswith(('https://signdocs.com.br', 'https://cdn.signdocs.com.br')):
        bad.append(('description.xml', url))
if bad:
    sys.stderr.write('FAIL: remote asset reference(s): %s\n' % bad)
    sys.exit(1)
print('  ok  no remote UI assets (air-gap safe)')
PY

# ------------------------------------------- 6. real install into a temp profile
command -v unopkg >/dev/null || fail "unopkg not on PATH"
PROFILE="$(mktemp -d)"
cleanup() { rm -rf "$LISTING" "$PROFILE"; }
trap cleanup EXIT

unopkg add -f -env:UserInstallation="file://$PROFILE" "$REPO/$OXT" >/dev/null
# Capture before matching: piping into `grep -q` under `set -o pipefail` makes
# the pipeline fail on a *successful* match, because grep exits at the first
# hit and unopkg dies on SIGPIPE.
INSTALLED="$(unopkg list -env:UserInstallation="file://$PROFILE")"
case "$INSTALLED" in
	*"$IDENTIFIER"*) ;;
	*) fail "installed, but '$IDENTIFIER' does not appear in unopkg list" ;;
esac
ok "unopkg add + list round-trip"

# Every bundled package must report "is registered: yes". A component whose
# media-type is wrong installs happily and simply never registers — the failure
# mode this whole script exists to catch.
case "$INSTALLED" in
	*"is registered: no"*) fail "a bundled package failed to register" ;;
esac
ok "all bundled packages registered"

unopkg validate -env:UserInstallation="file://$PROFILE" "$IDENTIFIER" >/dev/null \
	|| fail "unopkg validate rejected the extension"
ok "unopkg validate"

echo "PASS"
