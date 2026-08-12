# CLI Guide

`azure-functions-openapi` ships with a CLI entry point for generating OpenAPI output from decorated handlers.

## Install

```bash
pip install azure-functions-openapi
```

Then verify:

```bash
azure-functions-openapi --help
```

## Command overview

Current command set:

- `generate`: build OpenAPI spec in JSON or YAML

## `generate` command

### Basic usage

```bash
azure-functions-openapi generate
```

By default this prints JSON to stdout using:

- title: `API`
- version: `1.0.0`
- OpenAPI version: `3.1.0`

### Common examples

Generate JSON to stdout:

```bash
azure-functions-openapi generate --title "Todo API" --version "1.2.0"
```

Generate YAML to stdout:

```bash
azure-functions-openapi generate --format yaml --title "Todo API"
```

Write JSON to file:

```bash
azure-functions-openapi generate --output openapi.json --format json
```

Write YAML to file:

```bash
azure-functions-openapi generate --output openapi.yaml --format yaml
```

Generate OpenAPI 3.1 output:

```bash
azure-functions-openapi generate --openapi-version 3.1 --output openapi-3.1.json
```

Import your function app so routes are registered:

```bash
azure-functions-openapi generate --app function_app --title "Todo API"
```

Pretty-print JSON output:

```bash
azure-functions-openapi generate --app function_app --pretty --output openapi.json
```

### Endpoint-metadata discovery (`module:variable`)

`@openapi`-decorated routes register themselves the moment the module is
imported, so `--app module` is enough to see them. Producers that register
**only** through the shared endpoint-metadata namespace — `@validate_http`
(azure-functions-validation), `azure-functions-langgraph`, and other
third-party producers — are attached to the live `FunctionApp` object and are
discovered by scanning it.

To include those endpoints, pass an explicit `module:variable` so the CLI can
resolve the `FunctionApp` instance and run discovery on it:

```bash
# Imports function_app, resolves `app`, then discovers BOTH decorator-
# registered and endpoint-metadata routes into a single spec.
azure-functions-openapi generate --app function_app:app --output openapi.json
```

Discovery semantics:

- **`--app function_app`** (module only): the module is imported so `@openapi`
  decorators fire, but endpoint-metadata discovery is **not** run — the CLI
  never guesses the `FunctionApp` variable name. A note is printed reminding
  you to pass `module:variable` to also discover endpoint-metadata routes.
- **`--app function_app:app`** (module + variable): the named `FunctionApp`
  attribute is resolved and scanned, merging endpoint-metadata routes into the
  same registry as the decorator routes.
- Discovery is **one-shot** per run and uses the idempotent
  `FunctionBuilder.build()` path. The CLI never calls
  `FunctionApp.get_functions()`, which is non-idempotent on all supported SDK
  versions (1.21–1.25): it accumulates into `functions_bindings` and raises on
  a second call.
- **Blueprints** (raw or registered via `register_functions` /
  `register_blueprint`) are enumerated through the same path — no special
  casing is required.
- Re-running discovery on the same app is safe: the registry merges by
  function id, so no duplicate paths or operations are produced.

### Options reference

| Option | Alias | Values | Default | Description |
| --- | --- | --- | --- | --- |
| `--app` | - | `module` or `module:var` | - | Import module so `@openapi` decorators register routes; with `module:var`, also resolve the `FunctionApp` and discover endpoint-metadata routes (see [Endpoint-metadata discovery](#endpoint-metadata-discovery-modulevariable)) |
| `--title` | - | any string | `API` | OpenAPI `info.title` |
| `--version` | - | any string | `1.0.0` | OpenAPI `info.version` |
| `--description` | - | any string | library default | OpenAPI `info.description` (Markdown / CommonMark supported) |
| `--output` | `-o` | file path | stdout | Write generated content to file |
| `--format` | `-f` | `json`, `yaml` | `json` | Output serialization format |
| `--openapi-version` | - | `3.0`, `3.1` | `3.1` | OpenAPI schema version |
| `--pretty` | `-p` | flag | `false` | Pretty-print JSON output (adds indentation); no effect on YAML |
| `--route-prefix` | - | any string (or `""`) | `/api` | HTTP route prefix from `host.json` `extensions.http.routePrefix`. See [Route Prefix](route-prefix.md). |
| `--fail-on-empty-paths` | - | flag | `false` | Exit with code 1 if the generated spec has no paths |
| `--strict` | - | flag | `false` | Fail on any malformed registry entry instead of skipping it. Recommended for CI where a missing path should break the build |
| `--fail-on-warnings` | - | flag | `false` | Exit with code 2 if the generator emits any structured warnings (version skew, namespace fallback, or spec-validation issues). Use in CI to stop a wrong-but-plausible spec from being published |
| `--isolate-app` | - | flag | `false` | Scan the `--app` `FunctionApp` into a fresh, app-scoped registry instead of the shared global one. Requires `--app module:variable`. Use when several apps are imported in one process to avoid cross-app route leakage |

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | Runtime or generation error (including `--fail-on-empty-paths` with no paths, or an `--isolate-app` that cannot be honored) |
| `2` | Either invalid CLI arguments (argparse parse error) **or** structured warnings were emitted while `--fail-on-warnings` is set |

## Validate generated output

Use a validator in local checks and CI:

```bash
pip install openapi-spec-validator
openapi-spec-validator openapi.json
```

For YAML:

```bash
openapi-spec-validator openapi.yaml
```

## CI example

```yaml
name: OpenAPI Validation

on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install tools
        run: pip install azure-functions-openapi openapi-spec-validator
      - name: Generate spec
        run: azure-functions-openapi generate --openapi-version 3.1 --output openapi.json
      - name: Validate spec
        run: openapi-spec-validator openapi.json
```

## Troubleshooting

### `command not found`

- Confirm package installed in active environment
- Use `python -m azure_functions_openapi.cli --help` as fallback

### Empty `paths` in output

- Ensure app handlers are decorated with `@openapi`
- Pass `--app <module>` so decorated routes are registered before generation:

  ```bash
  azure-functions-openapi generate --app function_app --title "My API"
  ```

- Use `module:variable` syntax when the `FunctionApp` instance is not named `app`:

  ```bash
  azure-functions-openapi generate --app function_app:my_app --title "My API"
  ```
### Unsupported version error

- Use only `--openapi-version 3.0` or `--openapi-version 3.1`

## Related docs

- [Usage](usage.md)
- [Configuration](configuration.md)
- [API Reference](api.md)
- [Troubleshooting](troubleshooting.md)
