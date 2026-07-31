#!/usr/bin/env bash
#
# Build the distributable extension archive.
#
# An .oxt is a plain zip whose members sit at the ARCHIVE ROOT — description.xml
# and META-INF/manifest.xml must be top-level. (This is the opposite of the
# ONLYOFFICE .plugin, which requires exactly one {GUID} root directory. Getting
# either one wrong fails silently.)
#
# With --ref <tag> the tree comes from `git archive`, so a release build is
# reproducible and ignores whatever is dirty in the working copy. Without it,
# only git-tracked files are used — same discipline as signdocs-nextcloud.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$PWD"

REF=""
while [ $# -gt 0 ]; do
	case "$1" in
		--ref) REF="$2"; shift 2 ;;
		*) echo "usage: $0 [--ref <git-ref>]" >&2; exit 2 ;;
	esac
done

VERSION="$(python3 - <<'PY'
import xml.etree.ElementTree as ET
ns = {'d': 'http://openoffice.org/extensions/description/2006'}
print(ET.parse('description.xml').getroot().find('d:version', ns).get('value'))
PY
)"

OUT="signdocs-brasil-${VERSION}.oxt"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

if [ -n "$REF" ]; then
	git archive --format=tar "$REF" | tar -x -C "$STAGE"
else
	git ls-files -z | tar -c --null -T - -f - | tar -x -C "$STAGE"
fi

# Development-only trees and files. `bin/` in particular must not ship: it is
# how the archive is built, not part of it. `pyproject.toml` configures ruff
# and pytest — the extension itself has no build step and no dependencies, and
# shipping a dependency manifest invites someone to add one.
rm -rf "$STAGE/bin" "$STAGE/tests" "$STAGE/.github" "$STAGE/CLAUDE.md" \
       "$STAGE/pyproject.toml"
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$STAGE" -name '*.pyc' -delete

rm -f "$OUT"
( cd "$STAGE" && zip -qr "$REPO/$OUT" . -x '.git*' )

echo "Built $OUT ($(stat -c%s "$OUT") bytes)"
echo
echo "Install for the current user:"
echo "  unopkg add -f $OUT"
echo
echo "Install for every user on the machine (no Office process may be running):"
echo "  unopkg add --shared -f $OUT"
