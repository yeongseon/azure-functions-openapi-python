# Security Policy

## Reporting a Vulnerability

We take security seriously. If you discover a vulnerability, please report it
responsibly and avoid public disclosure until a fix is available.

### Preferred: GitHub Security Advisory

1. Go to the [Security Advisories page](https://github.com/yeongseon/azure-functions-openapi-python/security/advisories/new)
2. Click "Report a vulnerability"
3. Submit the details in the private advisory

### Alternative: Email

If you prefer email, contact: yeongseon.choe@gmail.com

### What to Include

* A clear description of the issue
* Steps to reproduce
* Impact assessment
* Suggested mitigation or fix, if available

### Response Timeline

* Initial response: within 48 hours
* Status update: within 7 days

## Supported Versions

| Version | Supported |
| ------- | --------- |
| Latest release | :white_check_mark: |
| Older releases | :x: |

## Automated security controls

| Control | Where it runs | Enforcement |
| --- | --- | --- |
| Bandit 1.9.4 | PR, main push, weekly, dispatch (`security.yml`) | Required `bandit` merge check; all severities block unless explicitly excepted |
| Semgrep `p/python` | Same workflow | Required `semgrep` merge check; existing SHA-pinned action retained |
| CodeQL Python `security-extended` | PR, main push, weekly | Required `Analyze` merge check; results published to code scanning |
| Runtime dependency audit | Release candidate wheel on Python 3.11–3.14 | Blocking `runtime-dependency-audit` dependency of `publish` |
| Browser CDN/SRI | Release candidate wheel, plus weekly/dispatch dependency reporting | Blocks release on mismatched bytes or unavailable verification |
| Runtime + development dependency audit | Weekly/dispatch (`dependency-audit.yml`) | Reporting-only; each lane's classified result is visible in Job Summary |
| SBOM | Weekly/dispatch (`sbom.yml`) | Reporting inventory of the installed built wheel; verifies expected packages exist |

Existing `ci-required`, `PR title`, conversation resolution, wheel reuse, host smoke,
and real-Azure certification remain unchanged. The new release security gate does
not replace any existing gate. PyPI still receives only the `build` job's artifact
through trusted OIDC publishing. Security jobs have `contents: read` only; CodeQL's
existing `security-events: write`, Azure OIDC and PyPI OIDC are unchanged.

### Static scan coverage

`make security-bandit` scans **all Python files** in `src/`,
`examples/` (including `e2e_app`), `demo/`, `scripts/`, and `tools/`. There are no
per-file exclusions within these surfaces. The helper compares Bandit's file
inventory to the on-disk Python inventory, requires at least 40 files and positive
LOC, and rejects scan errors and inline suppressions (`nosec`/`skipped_tests`).
Tests and fixtures under `tests/` are intentionally outside this executable-product
scan. Generated HTML/JSON/PNG previews, bytecode and other non-Python files are not
Python scan inputs; their Python generators are scanned. Bicep and workflow review
complement these checks; Bandit does not claim to analyze those languages.

`make security` and `make check-all` include this same expanded-scope check.
Low-severity reviewed tooling findings are retained
in evidence, not hidden with global Bandit skips. Exact ID/file/line exceptions in
`security/bandit-policy.json` explain shell-free subprocess use and literal-marker
false positives. No example/demo exception was required by the baseline scan.

### Runtime advisory and exception policy

`security/dependency-audit-policy.json` blocks **any known advisory** in the resolved
runtime closure of the candidate wheel. Advisory severity is recorded when exposed
by pip-audit; missing severity is `UNKNOWN` and still blocks. This deliberately
avoids treating absent CVSS data as low risk. Each supported Python version is
audited because environment markers change the Azure Functions dependency closure.
The candidate environment contains only the wheel and its runtime dependencies:
it is created without pip. The helper reads the candidate wheel METADATA and
requires exactly one installed distribution with the same normalized name and
exact version before excluding only that candidate. It freezes every installed
third-party distribution to `name==version` and runs pip-audit 2.10.1 outside the
environment with `--requirement`, `--no-deps`, and `--disable-pip`. The returned
inventory must match those exact pins; a returned candidate must match its verified
identity. An unpublished first-party version therefore needs no PyPI record, but
missing/mismatched identity, an empty closure, third-party skips or omitted packages
remain blocking. Development tools cannot contaminate the release runtime audit.

Use the same Makefile entry points locally (after provisioning the audit tool):

```bash
make security-runtime SECURITY_PYTHON=/path/to/audit/bin/python \
  SITE_PACKAGES=/path/to/candidate/lib/python3.11/site-packages \
  CANDIDATE_WHEEL=/path/to/candidate.whl SECURITY_OUTPUT=security-results/runtime
make security-development SECURITY_PYTHON=/path/to/audit/bin/python \
  SITE_PACKAGES=/path/to/development/lib/python3.11/site-packages \
  CANDIDATE_WHEEL=/path/to/candidate.whl SECURITY_OUTPUT=security-results/development
make security-browser SECURITY_PYTHON=/path/to/candidate/bin/python
make security-types
```

Runtime checking blocks releases; scheduled runtime/development reporting uses
the same non-zero classifier exits with explicitly reporting-only workflow steps.

Exceptions require maintainer review and `id`, `package`, `kind`, `reason`, `owner`,
`added`, and `expires` (ISO dates), with a positive lifetime of at most 90 days.
Allowed dependency kinds are `not-affected` (document independently verified
affectedness evidence) and `fix-not-available` (valid only while the advisory lists
no fixed version). Package and advisory ID must match exactly (package separators
are normalized); aliases are not silently ignored. Expired exceptions fail even
when unused. Unused/stale exception counts are reported for removal. The runtime
policy starts empty. Static exceptions use `reviewed-static` plus exact file/line,
with the same ownership, rationale and expiry requirements. Do not add `# nosec`
or a blanket rule exclusion as an alternative to this review.

### Failure semantics and recovery

Helpers exit `0` for `PASS`, `1` for `FAIL` (findings, integrity mismatch or expired
policy exception), `2` for `TOOL_ERROR` (crash, invalid/missing JSON, audit collection
or network failure), and `3` for `INCOMPLETE` (empty/undersized scan, missing coverage,
unsafe suppressions or missing execution evidence). All non-PASS results block the
release gate. A pip-audit skipped/unavailable package is not a clean audit. The
Semgrep action exposes only its step outcome here: success is recorded as INCOMPLETE
with `action outcome only`,
failure conservatively as TOOL_ERROR with unknown findings count (its original
failing step remains blocking), and skipped/cancelled as INCOMPLETE. The summary
does not pretend an action failure proves a vulnerability.
`make security-semgrep SCAN_OUTCOME=success` retains exit-3 INCOMPLETE evidence
without failing the collector; it tolerates no tool-error exit. The pinned action
remains the blocking scan. Collectors and artifact uploads run with `if: always()`.

Fail-closed network verification trades availability for evidence: advisory database
or jsDelivr outages can delay publication. Bounded tool timeouts and curl retries
limit hanging; never bypass the gate. Retry an unchanged tag via
`gh workflow run publish-pypi.yml --ref vX.Y.Z`; changed code must fix forward to a
new release candidate. No network checks run in default pytest.

### Evidence and redaction

`security-results/**/summary.json` (or `security-results/summary.json`) uses schema
version 1 with check name, scope, status, tool exit status, counts, suppression
counts, applied exception identifiers, tool versions, and allow-listed finding
metadata. Markdown counts/status are appended to `$GITHUB_STEP_SUMMARY`. SHA-pinned
artifact uploads run with `if: always()` and fail if evidence is missing. Each job
or matrix cell has a unique artifact name. Generated local evidence is gitignored.

Raw scanner stdout/stderr, code snippets, advisory descriptions, exception reasons,
HTTP headers, connection strings and downloaded assets are **not** uploaded or
printed by the helpers. Only rule/advisory IDs, relative file paths, line numbers,
classification and package identifiers survive input parsing. Invalid diagnostics
are replaced by fixed messages, never echoed. Redaction regression tests use
credential-bearing canaries. Evidence is a code/config review finding until runtime
impact is independently demonstrated; a clean scan is not proof of absence.

### Examples and deployment boundaries

Examples are local-only demonstrations unless explicitly described as ephemeral
certification infrastructure. OpenAPI security declarations do not enforce runtime
authorization; the report bearer check and partner purge key-presence check are
placeholders, and webhook HMAC is optional when its environment secret is unset.
The demo static server binds loopback only. The e2e Function App is
intentionally anonymously reachable for CI warmup/tests/screenshots and holds only
synthetic data; it is not a production template.

Production deployments need explicit authentication, restricted network ingress,
HTTPS/minimum TLS, private blob access, managed identities and appropriate storage
RBAC. `infra/main.bicep` already requires HTTPS, TLS 1.2 for storage and disables
public blobs. It retains shared-key connection-string deployment/storage and public
network reachability for the existing Flex Consumption certification flow. Disabling
shared keys, replacing storage authentication with managed identity, private endpoints,
or changing Function App/SCM minimum TLS needs real-Azure validation before adoption;
these are follow-up review recommendations, not confirmed exploitable vulnerabilities.
