# Chromium key-forwarding verification

The **Browser key forwarding** workflow runs the named **Chromium key forwarding
(advisory)** lane on pull requests, pushes to main, and manual dispatch. It is
intentionally not a branch-protection requirement or a dependency of `ci-required`:
the six real-bundle cases depend on the public jsDelivr CDN, so collect stability
evidence before considering promotion. Failures remain visible, not suppressed by
`continue-on-error`.

## Run locally

Prerequisites: Python 3.11+, Node.js with npm on PATH, and network access to npm,
Playwright's browser downloads, and `https://cdn.jsdelivr.net`. No Azure account
or Functions host is needed.

```sh
make install
make browser-install
make test-browser
```

On Linux, install Chromium's system libraries if needed with
`make browser-install BROWSER_INSTALL_FLAGS=--with-deps` (may require sudo).
CI uses `make install-ci` and `make test-browser BROWSER_PYTHON=python` to run on
its selected interpreter rather than Hatch.

`browser-install` pins Playwright to the Makefile's `PLAYWRIGHT_VERSION` and
downloads only its matching Chromium headless shell. Package files live under
`.cache/browser` and browser files under `.cache/ms-playwright`; no user npm-cache
discovery or revision-specific executable path is used. Remove these two
directories when no longer needed. Tests never install prerequisites implicitly.

`test-browser` explicitly selects `-m browser` and disables package coverage for
this focused lane. It runs two offline interceptor cases (default and custom CSP)
plus six cases against the real SRI-enforced CDN bundle: normal download,
same-origin 302/307/308, cross-origin 302, and a redirect chain. Missing Node,
Playwright, Chromium, CDN access, or any skipped case makes the command fail.
The default `make test` and `make check-all` still exclude browser tests and keep
the independent 95% library coverage gate.
