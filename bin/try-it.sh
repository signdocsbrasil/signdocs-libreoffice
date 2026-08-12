#!/usr/bin/env bash
#
# Install the built extension into a throwaway LibreOffice profile and open
# one of the office modules with it.
#
# Uses -env:UserInstallation, so this runs *alongside* your normal
# LibreOffice: your real profile is untouched, your open documents are not
# disturbed, and you do not have to close anything first. Delete the profile
# directory and every trace of the test is gone.
#
#   bash bin/try-it.sh              # install and launch Writer
#   bash bin/try-it.sh --calc       # ...or Calc, --impress, --draw
#   bash bin/try-it.sh --all        # all four at once, one profile
#   bash bin/try-it.sh --reset      # wipe the test profile first
#   bash bin/try-it.sh --hml        # start pointing at homologação
#
# The four modules are worth exercising separately, not out of thoroughness
# but because each is a different code path: Addons.xcu names all four in its
# Context, and intake.py maps each to its own PDF export filter
# (writer_pdf_Export, calc_pdf_Export, ...). A module missing from either
# list fails in a way the others never show — the menu absent in Calc, or
# present everywhere and the export failing only in Draw.
#
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$PWD"

PROFILE="${SIGNDOCS_TRY_PROFILE:-/tmp/lo-signdocs-try}"
RESET=0
STAGE=""
MODULES=""
LABEL=""

while [ $# -gt 0 ]; do
	case "$1" in
		--reset)   RESET=1; shift ;;
		--hml)     STAGE="hml"; shift ;;
		--prod)    STAGE="prod"; shift ;;
		--writer)  MODULES="--writer"; LABEL="Writer"; shift ;;
		--calc)    MODULES="--calc"; LABEL="Calc"; shift ;;
		--impress) MODULES="--impress"; LABEL="Impress"; shift ;;
		--draw)    MODULES="--draw"; LABEL="Draw"; shift ;;
		# One process, four windows: the menu has to appear in every one of
		# them, and comparing side by side is the fastest way to see that it
		# does not.
		--all)     MODULES="--writer --calc --impress --draw"
		           LABEL="Writer, Calc, Impress and Draw"; shift ;;
		*) echo "usage: $0 [--reset] [--hml|--prod] [--writer|--calc|--impress|--draw|--all]" >&2
		   exit 2 ;;
	esac
done

# Writer stays the default, so the bare command behaves as it always has.
[ -n "$MODULES" ] || { MODULES="--writer"; LABEL="Writer"; }

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

Opening $LABEL with the extension installed.

  Menu:     Ferramentas ▸ Suplementos ▸ SignDocs Brasil
  Toolbar:  Ver ▸ Barras de ferramentas ▸ Add-On 1

  Profile:  $PROFILE   (delete it to undo everything)

EOF

exec soffice -env:UserInstallation="file://$PROFILE" --norestore $MODULES
