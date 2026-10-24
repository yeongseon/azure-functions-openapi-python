"""Opt-in pytest plugin: browser verification is unsuccessful if any case skips."""

from _pytest.terminal import TerminalReporter
import pytest


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session) -> None:
    reporter: TerminalReporter | None = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None and reporter.stats.get("skipped"):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
