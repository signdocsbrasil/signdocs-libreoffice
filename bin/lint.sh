#!/usr/bin/env bash
#
# Cheap pre-build gate: Python syntax and XML well-formedness. Both catch
# mistakes that would otherwise only surface as a silently inert extension.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "python syntax"
python3 -m compileall -q signdocs_addon.py pythonpath bin >/dev/null
echo "  ok"

echo "ruff"
if command -v ruff >/dev/null; then
	ruff check signdocs_addon.py pythonpath tests bin
	echo "  ok"
else
	echo "  skipped (ruff not installed)"
fi

# The logic modules must stay importable without a running office: that is
# what makes them unit-testable, and it is easy to break by adding a
# convenience `import uno` at the top of the wrong file. Only ui/ may do it at
# module scope; elsewhere the import has to be deferred into the function that
# actually needs the office.
echo "no hardcoded pt-BR strings outside strings.py"
python3 bin/check_strings.py

echo "no module-scope uno imports outside ui/"
python3 - <<'PY'
import os, re, sys
bad = []
for root, _, files in os.walk('pythonpath/signdocs'):
    if os.path.basename(root) == 'ui':
        continue
    for name in files:
        if not name.endswith('.py'):
            continue
        path = os.path.join(root, name)
        src = open(path, encoding='utf-8').read()
        # Column 0 only: a deferred import inside a function is the sanctioned
        # way for an office-side helper to reach UNO.
        if re.search(r'^(import|from)\s+(uno|unohelper|com\.sun\.star)', src, re.M):
            bad.append(path)
if bad:
    sys.stderr.write('FAIL: uno imported outside ui/: %s\n' % bad)
    sys.exit(1)
print('  ok')
PY

echo "xml well-formedness"
python3 - <<'PY'
import glob, sys, xml.etree.ElementTree as ET

files = ['description.xml', 'META-INF/manifest.xml',
         'Addons.xcu', 'ProtocolHandler.xcu']
bad = 0
for f in files:
    try:
        ET.parse(f)
        print('  ok  %s' % f)
    except ET.ParseError as exc:
        # The usual culprit is a double hyphen inside an XML comment, which is
        # illegal and produces an opaque "invalid token" at that column.
        print('  FAIL %s: %s' % (f, exc))
        bad = 1
sys.exit(bad)
PY

# The HandlerSet node name and the implementation name registered in Python
# must be byte-identical. When they drift the menu still appears and every
# click silently does nothing.
python3 - <<'PY'
import re, sys, xml.etree.ElementTree as ET

OOR = '{http://openoffice.org/2001/registry}'
root = ET.parse('ProtocolHandler.xcu').getroot()
handler_set = root.find(".//*[@%sname='HandlerSet']" % OOR)
names = [n.get(OOR + 'name') for n in handler_set]

src = open('signdocs_addon.py', encoding='utf-8').read()
impl = re.search(r'IMPL_NAME\s*=\s*"([^"]+)"', src).group(1)

if impl not in names:
    sys.stderr.write(
        'FAIL: IMPL_NAME %r is not a HandlerSet node in ProtocolHandler.xcu %r\n'
        % (impl, names))
    sys.exit(1)
print('  ok  implementation name matches ProtocolHandler.xcu (%s)' % impl)
PY

echo "PASS"
