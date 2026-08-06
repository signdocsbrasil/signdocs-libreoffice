#!/usr/bin/env bash
#
# Install the built .oxt into a throwaway profile, boot a headless office on a
# UNO socket, and assert that the UI registration and the dispatch chain
# actually work. See bin/smoke_probe.py for what is asserted and why.
#
# Everything happens in a temp UserInstallation, so the developer's own
# LibreOffice profile is never touched and a running office is not disturbed.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$PWD"

PORT="${SIGNDOCS_UNO_PORT:-2103}"
VERSION="$(python3 - <<'PY'
import xml.etree.ElementTree as ET
ns = {'d': 'http://openoffice.org/extensions/description/2006'}
print(ET.parse('description.xml').getroot().find('d:version', ns).get('value'))
PY
)"
OXT="signdocs-brasil-${VERSION}.oxt"
[ -f "$OXT" ] || { echo "FAIL: $OXT not found — run bin/build-oxt.sh first" >&2; exit 1; }

PROFILE="$(mktemp -d)"
PID=""
cleanup() {
	[ -n "$PID" ] && kill "$PID" 2>/dev/null || true
	# The soffice wrapper forks; kill anything still bound to this profile.
	pkill -f "UserInstallation=file://$PROFILE" 2>/dev/null || true
	rm -rf "$PROFILE"
}
trap cleanup EXIT

echo "installing $OXT into a throwaway profile"
unopkg add -f -env:UserInstallation="file://$PROFILE" "$REPO/$OXT" >/dev/null

echo "booting headless office on port $PORT"
# Keeps the SelfTest command from trying to draw a dialog in a headless office.
export SIGNDOCS_SELFTEST_QUIET=1
soffice --headless --norestore --nologo --nofirststartwizard \
	-env:UserInstallation="file://$PROFILE" \
	--accept="socket,host=127.0.0.1,port=${PORT};urp;" \
	>"$PROFILE/soffice.log" 2>&1 &
PID=$!

for _ in $(seq 1 60); do
	(echo > "/dev/tcp/127.0.0.1/$PORT") 2>/dev/null && break
	sleep 0.5
done
(echo > "/dev/tcp/127.0.0.1/$PORT") 2>/dev/null \
	|| { echo "FAIL: office never accepted a UNO connection" >&2; cat "$PROFILE/soffice.log"; exit 1; }

echo "probing"
# The probe needs `import uno`, which only the office's own interpreter has.
# On Linux python3-uno puts it on the system path, so plain python3 works. On
# macOS everything lives inside the .app and the system python3 cannot see it,
# so the caller points this at Contents/Resources/python instead.
"${SIGNDOCS_UNO_PYTHON:-python3}" bin/smoke_probe.py "$PORT"
