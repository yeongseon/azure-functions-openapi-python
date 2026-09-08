# ADR 0001 — Metadata inference default policy

- **Status:** Accepted
- **Deciders:** maintainers
- **Related issues:** [#530], [#533], [#551], [#553], [#556], [#572]

## Context

`azure-functions-openapi` can infer OpenAPI metadata from a handler without an
explicit `@openapi(...)` value:

- **Return-type inference** — derive the `200` response schema from a handler's
  return annotation (`-> User`).
- **Docstring inference** — derive `summary` / `description` from a handler's
  docstring.

Both are **gap-fill-only** and **lowest-precedence**: an explicit value (including
an explicit `""` suppression) always wins, and inference never overrides it.
Both are also **failure-silent** — inference can never break runtime or raise.

The open question was the *default* for each: on (inferred unless opted out) or
off (inferred only when opted in). This ADR records the decision so future
contributors do not re-litigate it.

## Decision

We set inference defaults **by the size of the surprise** a user would
experience if the feature were on without their asking:

### 1. Return type — default **on** (opt out with `infer_return_types=False`)

A return *type annotation* is a **structural declaration**, not free-form prose.
Annotating `-> User` is the Python analogue of declaring a response contract, and
inferring the `200` response from it is low-surprise — it matches the
FastAPI/Pydantic norm (FastAPI 0.89's return-annotation `response_model`
precedent). The realistic surprise surface is small because typical v2 handlers
return `func.HttpResponse`, which infers nothing.

Because a return type is already a quasi-public contract and the impact is
docs-only, this stays **default-on**. Users who annotate an internal/transport
return type they do not want published opt out per handler with
`infer_return_types=False` — the analogue of FastAPI's `response_model=None`.
See [#530] (shipped default-on in 0.25.0) and [#556] (added the opt-out,
**kept** the default on, superseding the earlier opt-in-flip proposal).

### 2. Docstring — **opt-in first, then default-on in the next minor**

A docstring is **free-form internal prose**. Publishing it into a public OpenAPI
spec without consent is a **larger surprise** — it retroactively exposes text the
author wrote for maintainers, not API consumers. So docstring inference ships
**opt-in** (`infer_docstring=True`) first, giving the ecosystem a release to
adjust docstrings that were never meant to be published, and only flips to
default-on in a **subsequent minor** once that expectation is set. See [#533] /
[#551] / [#553] (made docstring inference opt-in before it shipped).

### Decision rule

> **Defaults are set by the size of the surprise.** A structural declaration
> (return type) can default on; free-form prose (docstring) must earn default-on
> through an opt-in round-trip first.

### Opt-in round-trip (recorded case)

The docstring path deliberately takes an **opt-in → (one minor later) default-on**
round trip rather than shipping default-on immediately. This is the concrete
application of the decision rule: the round-trip is the cost we pay to avoid
retroactively publishing internal prose, and it is the precedent to follow for
any future "prose-like" inference source.

## Consequences

- `infer_return_types` defaults to `True`; `infer_docstring` defaults to `False`
  (until the planned next-minor flip).
- Explicit `responses=` / `summary=` / `description=` always win regardless of
  either flag; precedence is unchanged.
- Future inference sources are classified the same way: **structural →
  default-on candidate; prose → opt-in round-trip first**.

## References

- [#530] — return-type inference (shipped 0.25.0, stays on)
- [#533] / [#551] / [#553] — docstring inference made opt-in before shipping
- [#556] — return-type opt-out added; default kept on (supersedes opt-in-flip)
- [#572] — this ADR
- FastAPI 0.89 return-annotation (`response_model`) precedent

[#530]: https://github.com/yeongseon/azure-functions-openapi-python/issues/530
[#533]: https://github.com/yeongseon/azure-functions-openapi-python/issues/533
[#551]: https://github.com/yeongseon/azure-functions-openapi-python/issues/551
[#553]: https://github.com/yeongseon/azure-functions-openapi-python/issues/553
[#556]: https://github.com/yeongseon/azure-functions-openapi-python/issues/556
[#572]: https://github.com/yeongseon/azure-functions-openapi-python/issues/572
