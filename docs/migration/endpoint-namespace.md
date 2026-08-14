# Migrating off the legacy `validation` metadata namespace

## What changed

In **0.21.2** the OpenAPI bridge stopped reading the legacy `validation` metadata
namespace as a discovery fallback ([#442], closing [#313]). The bridge now reads
**only** the shared `endpoint` namespace (plus plain `@openapi` decorators).

Sibling packages in the Azure Functions Python DX Toolkit cooperate by attaching
plain JSON-compatible metadata to handler functions — never by importing one
another. Producer packages (such as `azure-functions-validation`) historically
wrote their metadata under a package-local `validation` namespace; the toolkit
has since converged on a single shared `endpoint` namespace. The bridge kept a
temporary read mirror so it could still discover producers that only emitted the
old namespace. That mirror is now removed.

## Runtime effect

If you upgrade the OpenAPI consumer to 0.21.2+ **without** upgrading a producer
package that still emits only the old `validation` namespace:

- The operation is **still registered** — it is derived from the Azure Functions
  binding (route + method), so your endpoint does not disappear.
- The **validation-derived schema hints are dropped** — request/response models
  contributed via the old namespace no longer flow into the generated spec.
- A **`VERSION_SKEW`** warning is emitted to flag the stale-producer condition.

This is a graceful degradation plus a warning, not a crash.

## How to migrate

Upgrade your producer packages to versions that emit the shared `endpoint`
namespace. In particular, upgrade `azure-functions-validation` to a release that
writes `endpoint` metadata, then regenerate your spec. Once every producer emits
`endpoint`, the `VERSION_SKEW` warning clears and full schema hints return.

If you cannot upgrade a producer yet, add an explicit `@openapi(...)` decorator
to the affected handler so the bridge can build the operation from first-class
metadata instead of relying on producer-emitted hints.

## A note on versioning

This removal was a **compatibility-affecting behavior change** and, under the
toolkit's semver policy (a behavior escalation must ship as a minor, not a
patch), it should not have gone out in the 0.21.1 → 0.21.2 **patch**. We are not
yanking 0.21.2 — it also carries unrelated wanted fixes and the change is a
graceful degradation rather than a hard break — but to realign with the policy
the **next release is 0.22.0** (a minor). Treat 0.21.2 as the point at which the
legacy `validation` read mirror was removed.

[#442]: https://github.com/yeongseon/azure-functions-openapi-python/pull/442
[#313]: https://github.com/yeongseon/azure-functions-openapi-python/issues/313
