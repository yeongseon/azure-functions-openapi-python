"""Fail fast if a dedicated e2e run is missing its required configuration.

Protects the direct `hatch run e2e-azure` entry point (#787's Makefile guard
only covers `make e2e-local`/`make e2e-azure`, not this script's own caller).
Without this, E2E_BASE_URL unset meant pytest still collected all six e2e
tests, skipped every one via their own skipif, and exited 0 with coverage
disabled -- a dedicated run that looked successful but executed nothing.

Intentionally does not gate a pure collection-only invocation: this script
is wired into the `e2e-azure` Hatch script itself (see pyproject.toml), so a
caller running `pytest --collect-only -m e2e tests/e2e/` directly (as
tests/test_e2e_marker_contract.py does, #787) never invokes it at all.
"""

from __future__ import annotations

import os
import sys

_REQUIRED_VARS = ("E2E_BASE_URL", "E2E_EXPECTED_VERSION")


def main() -> int:
    missing = [name for name in _REQUIRED_VARS if not os.environ.get(name)]
    if missing:
        print(
            "Error: e2e-azure requires " + " and ".join(missing) + " to be set, e.g.:\n"
            "  E2E_BASE_URL=https://<app>.azurewebsites.net "
            "E2E_EXPECTED_VERSION=<deployed-version> hatch run e2e-azure\n"
            "Running this entry point with them unset would collect the e2e "
            "tests but skip every one of them, exiting 0 -- an "
            "unintentionally successful-looking run that certified nothing.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
