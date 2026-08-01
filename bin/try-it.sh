#!/usr/bin/env bash
#
# Install the built extension into a throwaway LibreOffice profile and open
# Writer with it.
#
# Uses -env:UserInstallation, so this runs *alongside* your normal
# LibreOffice: your real profile is untouched, your open documents are not
# disturbed, and you do not have to close anything first. Delete the profile
# directory and every trace of the test is gone.
#
#   bash bin/try-it.sh              # install and launch
#   bash bin/try-it.sh --reset      # wipe the test profile first
#   bash bin/try-it.sh --hml        # start pointing at homologação
#
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$PWD"

PROFILE="${SIGNDOCS_TRY_PROFILE:-/tmp/lo-signdocs-try}"
RESET=0
STAGE=""

while [ $# -gt 0 ]; do
	case "$1" in
		--reset) RESET=1; shift ;;
		--hml)   STAGE="hml"; shift ;;
		--prod)  STAGE="prod"; shift ;;
		*) echo "usage: $0 [--reset] [--hml|--prod]" >&2; exit 2 ;;
	esac
done

VERSION="$(python3 - <<'PY'
import xml.etree.ElementTree as ET
ns = {'d': 'http://openoffice.org/extensions/description/2006'}
print(ET.parse('description.xml').getroot().find('d:version', ns).get('value'))
PY
)"
OXT="signdocs-brasil-${VERSION}.oxt"

if [ ! -f "$OXT" ]; then
	echo "building $OXT"
	bash bin/build-oxt.sh >/dev/null
fi

if [ "$RESET" = "1" ]; then
	echo "wiping $PROFILE"
	rm -rf "$PROFILE"
fi
mkdir -p "$PROFILE"

echo "installing $OXT into $PROFILE"
unopkg add -f -env:UserInstallation="file://$PROFILE" "$REPO/$OXT" >/dev/null

if [ -n "$STAGE" ]; then
	# Pre-set the stage so the first connect goes where you expect. The
	# extension ships pointing at production on purpose; this is the same
	# thing the Configurações dialog writes.
	python3 - "$PROFILE" "$STAGE" <<'PY'
import json, os, sys
profile, stage = sys.argv[1], sys.argv[2]
path = os.path.join(profile, "user", "signdocs.json")
os.makedirs(os.path.dirname(path), exist_ok=True)
data = {}
if os.path.exists(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
data["signdocs.stage"] = stage
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
os.chmod(path, 0o600)
print("stage set to %s" % stage)
PY
fi

cat <<EOF

Opening Writer with the extension installed.

  Menu:     Ferramentas ▸ Suplementos ▸ SignDocs Brasil
  Toolbar:  Ver ▸ Barras de ferramentas ▸ Add-On 1

  Profile:  $PROFILE   (delete it to undo everything)

EOF

exec soffice -env:UserInstallation="file://$PROFILE" --norestore --writer
