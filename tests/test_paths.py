# SPDX-License-Identifier: MPL-2.0
"""
State lives in the office user profile, not $HOME.

That choice is load-bearing: `-env:UserInstallation` overrides, portable
installs and roaming profiles all have to work, and the test suites here rely
on it to keep a throwaway profile genuinely throwaway. It is also why importing
this module must not need a running office — asserted below, since a
module-scope `import unohelper` would break every test that touches a path.
"""

import os

from signdocs import paths


class _StubSubstitution(object):
    def __init__(self, value):
        self._value = value

    def substituteVariables(self, name, enabled):  # noqa: N802 - UNO API name
        assert name == "$(user)"
        assert enabled is True
        return self._value


class _StubServiceManager(object):
    def __init__(self, value):
        self._value = value

    def createInstanceWithContext(self, service, ctx):  # noqa: N802 - UNO API name
        assert service == "com.sun.star.util.PathSubstitution"
        return _StubSubstitution(self._value)


class _StubContext(object):
    def __init__(self, value):
        self.ServiceManager = _StubServiceManager(value)


def test_module_imports_without_an_office():
    # If this file can be collected at all the import worked; assert the
    # intent explicitly so the reason survives a refactor.
    assert paths.STATE_FILENAME == "signdocs.json"
    assert paths.SELFTEST_FILENAME == "signdocs-selftest.json"


def test_user_dir_url_asks_the_office_for_the_profile():
    ctx = _StubContext("file:///home/ana/.config/libreoffice/4/user")
    assert paths.user_dir_url(ctx) == "file:///home/ana/.config/libreoffice/4/user"


def test_state_and_selftest_files_sit_in_the_profile(monkeypatch):
    monkeypatch.setattr(paths, "user_dir", lambda ctx: os.path.join("/tmp", "user"))
    assert paths.state_file(None) == os.path.join("/tmp", "user", "signdocs.json")
    assert paths.selftest_file(None) == os.path.join(
        "/tmp", "user", "signdocs-selftest.json"
    )


def test_state_file_is_not_the_selftest_file(monkeypatch):
    # The self-test report is world-shareable diagnostics; the state file holds
    # a refresh token. Nothing may ever collapse the two.
    monkeypatch.setattr(paths, "user_dir", lambda ctx: "/tmp/user")
    assert paths.state_file(None) != paths.selftest_file(None)
