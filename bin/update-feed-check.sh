#!/usr/bin/env bash
#
# Boot a throwaway headless office and have IT read the published update feed.
#
# The URL is compiled into every .oxt and cannot be corrected for anyone who has
# already installed, so a feed the office cannot consume is unrecoverable — and
# it is the only route for shipping a fix without waiting on the TDF moderation
# queue. See bin/update_feed_probe.py for what is asserted and why.
#
# Reads the LIVE published feed by default, because that is the artefact users
# poll. Pass a URL to check a staging copy before publishing it:
#
#   bash bin/update-feed-check.sh
#   bash bin/update-feed-check.sh https://cdn.signdocs.com.br/libreoffice/update.xml
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$PWD"

FEED="${1:-https://cdn.signdocs.com.br/libreoffice/update.xml}"
# Not the smoke test's port: the two are routinely run back to back, and a
# lingering office from one would silently answer for the other.
PORT="${SIGNDOCS_UNO_PORT:-2104}"

PROFILE="$(mktemp -d)"
PID=""
cleanup() {
	[ -n "$PID" ] && kill "$PID" 2>/dev/null || true
	pkill -f "UserInstallation=file://$PROFILE" 2>/dev/null || true
	rm -rf "$PROFILE"
}
trap cleanup EXIT

echo "booting headless office on port $PORT"
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

echo "asking the office to read $FEED"
"${SIGNDOCS_UNO_PYTHON:-python3}" "$REPO/bin/update_feed_probe.py" "$PORT" "$FEED"

# The feed being readable only proves half of it. An update that is offered and
# then fails to install is worse than none: the user gets an error box on a
# working installation, and it repeats on every check. So fetch what the feed
# actually points at and install it, in a second throwaway profile.
HREF="$("${SIGNDOCS_UNO_PYTHON:-python3}" - "$FEED" <<'INNER'
import sys, urllib.request, xml.etree.ElementTree as ET
raw = urllib.request.urlopen(sys.argv[1], timeout=30).read()
root = ET.fromstring(raw)
ns = {"u": "http://openoffice.org/extensions/update/2006"}
src = root.find(".//u:src", ns)
print(src.get("{http://www.w3.org/1999/xlink}href") if src is not None else "")
INNER
)"

[ -n "$HREF" ] || { echo "FAIL: the feed names no download" >&2; exit 1; }

echo
echo "downloading what the feed points at: $HREF"
DL="$PROFILE/from-feed.oxt"
curl -fsS --max-time 120 -o "$DL" "$HREF" \
	|| { echo "FAIL: the .oxt the feed names is not downloadable" >&2; exit 1; }
echo "  $(wc -c <"$DL") bytes"

INSTALL_PROFILE="$(mktemp -d)"
trap 'cleanup; rm -rf "$INSTALL_PROFILE"' EXIT
echo "installing it into a clean profile"
unopkg add -f -env:UserInstallation="file://$INSTALL_PROFILE" "$DL" >/dev/null \
	|| { echo "FAIL: the published .oxt does not install" >&2; exit 1; }

# unopkg list is the office's own view of what got registered — the identifier
# and the version a user would then actually be running.
LISTED="$(unopkg list -env:UserInstallation="file://$INSTALL_PROFILE" 2>/dev/null || true)"
echo "$LISTED" | grep -iE "identifier|version" | head -3 | sed 's/^/  /'

echo "$LISTED" | grep -q "br.com.signdocs.libreoffice" \
	|| { echo "FAIL: installed extension does not carry our identifier" >&2; exit 1; }

echo
echo "PASSOU: o escritório lê o feed e o .oxt que ele indica instala"
