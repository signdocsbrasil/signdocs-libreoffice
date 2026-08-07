#!/usr/bin/env bash
#
# Put a released .oxt on the CDN, and refuse to let the update feed and the
# binary drift apart.
#
# Every installed extension polls
# https://cdn.signdocs.com.br/libreoffice/update.xml, because description.xml
# names that URL in <update-information> and it is compiled into the package.
# LibreOffice compares the feed's <version> against the installed one and
# offers an update when it is higher — then downloads whatever the feed's
# <update-download> href points at.
#
# So there is a right order and a wrong one:
#
#   RIGHT  upload the .oxt, then bump <version> in the feed.
#          A half-finished release is invisible.
#   WRONG  bump the feed, then upload.
#          Every desktop offers an update that 404s until you catch up.
#
# This script does the first half and verifies it, then tells you exactly what
# the second half is. It deliberately does NOT edit the feed: update.xml lives
# in external-api and ships via CDK, so bumping it is a deploy, not a file
# copy.
#
# Not wired into CI on purpose. Doing so would mean giving a public repository
# write access to the production CDN bucket, which is a bigger decision than
# the convenience is worth.
#
#   bash bin/publish-cdn.sh            # upload the built .oxt
#   bash bin/publish-cdn.sh --dry-run  # check everything, upload nothing
set -uo pipefail

cd "$(dirname "$0")/.."

BUCKET="${SIGNDOCS_CDN_BUCKET:-sigext-cdn-js-prod}"
PREFIX="libreoffice"
BASE="https://cdn.signdocs.com.br/$PREFIX"
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

fail() { echo "  FAIL: $*" >&2; exit 1; }
ok()   { echo "  ok  $*"; }

VERSION="$(python3 - <<'PY'
import xml.etree.ElementTree as ET
ns = {'d': 'http://openoffice.org/extensions/description/2006'}
print(ET.parse('description.xml').getroot().find('d:version', ns).get('value'))
PY
)"
OXT="signdocs-brasil-${VERSION}.oxt"
[ -f "$OXT" ] || fail "$OXT not found — run bin/build-oxt.sh first"
ok "version $VERSION, local artefact $OXT"

# The .oxt must be the tagged tree, not whatever happens to be checked out.
# A release built from a dirty working copy is unreproducible and nobody can
# tell after the fact.
if ! git diff --quiet HEAD -- description.xml pythonpath signdocs_addon.py \
        META-INF Addons.xcu ProtocolHandler.xcu vendor icons 2>/dev/null; then
  fail "shipped files differ from HEAD — commit, tag, and rebuild with --ref"
fi
ok "shipped files match HEAD"

if git rev-parse "v$VERSION" >/dev/null 2>&1; then
  ok "tag v$VERSION exists"
else
  echo "  warn: no tag v$VERSION — releases should be built from a tag"
fi

# What the live feed currently advertises. Bumping it before the binary lands
# is the failure this script exists to prevent, so say so loudly.
LIVE="$(curl -fsS --max-time 20 "$BASE/update.xml" 2>/dev/null \
        | grep -oE '<version value="[^"]+"' | grep -oE '[0-9][^"]*' || true)"
if [ -n "$LIVE" ]; then
  ok "feed currently advertises $LIVE"
  if [ "$LIVE" = "$VERSION" ]; then
    # The feed already names this version. That is only a problem if the
    # binary is missing, so check rather than warn on a guess -- a false
    # alarm here trains people to ignore the real one.
    if curl -fsI --max-time 20 "$BASE/$OXT" >/dev/null 2>&1; then
      ok "feed and binary already agree on $VERSION (this upload replaces it)"
    else
      echo "  WARN: the feed advertises $VERSION but $BASE/$OXT is NOT"
      echo "        fetchable. Every client is being offered an update that"
      echo "        404s right now. Completing this upload fixes it."
    fi
  fi
else
  echo "  warn: could not read the live feed"
fi

if [ "$DRY" = "1" ]; then
  echo
  echo "  dry run — would upload $OXT to s3://$BUCKET/$PREFIX/"
  exit 0
fi

aws s3 cp "$OXT" "s3://$BUCKET/$PREFIX/$OXT" \
  --content-type application/vnd.openofficeorg.extension \
  --cache-control "public, max-age=300" >/dev/null 2>&1 \
  || fail "upload to s3://$BUCKET/$PREFIX/ failed"
ok "uploaded to s3://$BUCKET/$PREFIX/$OXT"

# Fetch it back over the CDN and compare bytes. "The upload returned 0" is not
# the same as "users can download this", and the difference is a broken
# update for everyone.
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
for attempt in 1 2 3; do
  if curl -fsS --max-time 60 -o "$TMP" "$BASE/$OXT" 2>/dev/null; then break; fi
  sleep 5
  [ "$attempt" = 3 ] && fail "uploaded, but $BASE/$OXT is not fetchable"
done
if [ "$(sha256sum "$OXT" | cut -d' ' -f1)" != "$(sha256sum "$TMP" | cut -d' ' -f1)" ]; then
  fail "the file served by the CDN does not match the local artefact"
fi
ok "downloaded from the CDN and sha256 matches"

echo
echo "  Binary is live. The feed still points at ${LIVE:-<unknown>}."
echo
echo "  To finish the release, in external-api:"
echo "    1. assets/libreoffice/update.xml — set <version> to $VERSION and the"
echo "       <update-download> href to $BASE/$OXT"
echo "    2. npm run test:unit  (the feed test pins version/href/identifier)"
echo "    3. npx cdk deploy SigExtCdnJs-prod --exclusively -c stage=prod"
echo
echo "  Only then will installed copies see $VERSION."
