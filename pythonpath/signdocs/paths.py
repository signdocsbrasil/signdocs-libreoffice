# SPDX-License-Identifier: MPL-2.0
"""
Where the extension keeps its state.

Everything lives under the LibreOffice user profile rather than $HOME, so a
portable install, a `-env:UserInstallation` override and a roaming profile all
behave the way the user expects — and a profile reset takes the stored
credentials with it.
"""

import os

STATE_FILENAME = "signdocs.json"
SELFTEST_FILENAME = "signdocs-selftest.json"


def user_dir_url(ctx):
    """file:// URL of the office user profile directory."""
    substitution = ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.util.PathSubstitution", ctx
    )
    return substitution.substituteVariables("$(user)", True)


def user_dir(ctx):
    """Native filesystem path of the office user profile directory."""
    # Imported here rather than at module scope so this module stays importable
    # without a running office. `unohelper` only exists inside the office's own
    # Python, and a module-scope import would make every unit test that touches
    # a path need a live UNO bridge.
    import unohelper

    return unohelper.fileUrlToSystemPath(user_dir_url(ctx))


def state_file(ctx):
    return os.path.join(user_dir(ctx), STATE_FILENAME)


def selftest_file(ctx):
    return os.path.join(user_dir(ctx), SELFTEST_FILENAME)
