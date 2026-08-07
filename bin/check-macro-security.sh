#!/usr/bin/env bash
#
# Does the extension still load when macro security is at its strictest?
#
# LibreOffice ships at High by default and many managed desktops raise it to
# Very High. That setting governs *document* macros; extension components load
# through a different trust path, so the expectation is that nothing changes.
# But the release checklist says verify rather than assume, and "assume" is how
# you ship something that installs cleanly and silently never registers on the
# machines that matter most — locked-down public-sector desktops being exactly
# the audience for a LibreOffice extension.
#
# The test asserts the level was actually applied before asserting behaviour.
# Without that, a setting LibreOffice quietly ignored would produce a
# confident pass that proves nothing.
#
# That readback is not decoration: **2 (High) is LibreOffice's own default**,
# verified empirically on a profile with no injection at all. So the level-2
# run would pass whether or not the injection worked, and it is the level-3
# run that proves both the mechanism and the behaviour. Keep 3 in the default
# set for that reason -- dropping to "just test High" would quietly turn this
# into a test of nothing.
#
#   bash bin/check-macro-security.sh          # High (2) and Very High (3)
#   bash bin/check-macro-security.sh 3        # one level only
set -uo pipefail

cd "$(dirname "$0")/.."
REPO="$PWD"

VERSION="$(python3 - <<'PY'
import xml.etree.ElementTree as ET
ns = {'d': 'http://openoffice.org/extensions/description/2006'}
print(ET.parse('description.xml').getroot().find('d:version', ns).get('value'))
PY
)"
OXT="signdocs-brasil-${VERSION}.oxt"
[ -f "$OXT" ] || { echo "FAIL: $OXT not found — run bin/build-oxt.sh first" >&2; exit 1; }

LEVELS="${1:-2 3}"
PORT_BASE="${SIGNDOCS_UNO_PORT:-2131}"
FAILED=0

name_for() { case "$1" in 0) echo Low ;; 1) echo Medium ;; 2) echo High ;; 3) echo "Very High" ;; esac; }

for LEVEL in $LEVELS; do
	PORT=$((PORT_BASE + LEVEL))
	PROFILE="$(mktemp -d)"
	PID=""
	cleanup() {
		[ -n "$PID" ] && kill "$PID" 2>/dev/null
		pkill -f "UserInstallation=file://$PROFILE" 2>/dev/null
		rm -rf "$PROFILE"
	}
	trap cleanup EXIT

	echo "── macro security $LEVEL ($(name_for "$LEVEL")) ──"

	# unopkg materialises the profile, including registrymodifications.xcu.
	unopkg add -f -env:UserInstallation="file://$PROFILE" "$REPO/$OXT" >/dev/null 2>&1 \
		|| { echo "  FAIL: install refused at this level"; FAILED=1; cleanup; trap - EXIT; continue; }

	REG="$PROFILE/user/registrymodifications.xcu"
	[ -f "$REG" ] || { echo "  FAIL: no registrymodifications.xcu to modify"; FAILED=1; cleanup; trap - EXIT; continue; }

	python3 - "$REG" "$LEVEL" <<'PY'
import sys
reg, level = sys.argv[1], sys.argv[2]
item = ('<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
        '<prop oor:name="MacroSecurityLevel" oor:op="fuse">'
        '<value>%s</value></prop></item>' % level)
src = open(reg, encoding="utf-8").read()
close = "</oor:items>"
assert close in src, "unexpected registrymodifications.xcu shape"
open(reg, "w", encoding="utf-8").write(src.replace(close, item + close, 1))
PY

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
	if ! (echo > "/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
		echo "  FAIL: office never accepted a UNO connection"
		FAILED=1; cleanup; trap - EXIT; continue
	fi

	# Read the level back from the running office. If LibreOffice ignored the
	# file, everything below would pass while testing nothing.
	APPLIED="$("${SIGNDOCS_UNO_PYTHON:-python3}" - "$PORT" <<'PY'
import sys, uno
from com.sun.star.beans import PropertyValue
ctx_local = uno.getComponentContext()
resolver = ctx_local.ServiceManager.createInstanceWithContext(
    "com.sun.star.bridge.UnoUrlResolver", ctx_local)
ctx = resolver.resolve(
    "uno:socket,host=127.0.0.1,port=%s;urp;StarOffice.ComponentContext" % sys.argv[1])
provider = ctx.ServiceManager.createInstanceWithContext(
    "com.sun.star.configuration.ConfigurationProvider", ctx)
arg = PropertyValue(); arg.Name = "nodepath"
arg.Value = "/org.openoffice.Office.Common/Security/Scripting"
node = provider.createInstanceWithArguments(
    "com.sun.star.configuration.ConfigurationAccess", (arg,))
print(node.getByName("MacroSecurityLevel"))
PY
)"
	if [ "$APPLIED" != "$LEVEL" ]; then
		echo "  FAIL: level did not apply (office reports '${APPLIED:-<none>}', wanted $LEVEL)"
		FAILED=1; cleanup; trap - EXIT; continue
	fi
	echo "  ok  office confirms MacroSecurityLevel=$APPLIED"

	if "${SIGNDOCS_UNO_PYTHON:-python3}" bin/smoke_probe.py "$PORT" >"$PROFILE/probe.log" 2>&1; then
		echo "  ok  extension registers and dispatches at this level"
		grep -cE "^\s+ok " "$PROFILE/probe.log" | xargs -I{} echo "      ({} probe assertions passed)"
	else
		echo "  FAIL: probe failed at this level"
		grep -E "FAIL|Traceback" "$PROFILE/probe.log" | head -5 | sed 's/^/      /'
		FAILED=1
	fi

	cleanup; trap - EXIT
done

echo
[ "$FAILED" = "0" ] && echo "PASS — the extension loads at every level tested" || echo "FAILED"
exit "$FAILED"
