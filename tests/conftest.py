# SPDX-License-Identifier: MPL-2.0
"""
Put `pythonpath/` on sys.path the same way LibreOffice's pythonloader does for
components inside an extension.

Nothing under `pythonpath/signdocs/` may import `uno` at module scope except
the `ui` package — that is the rule which keeps this logic testable without a
running office, and these tests are what enforce it.
"""

import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pythonpath"),
)
