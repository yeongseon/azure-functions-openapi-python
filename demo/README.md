# Demo Assets

These generators and the loopback-only preview server are local screenshot tooling,
not production web servers. Use synthetic inputs only; generated HTML/spec previews
must not contain credentials or customer payloads. The examples they invoke use
local-only anonymous defaults (see `examples/README.md`).

The README demo assets are generated from code:

- `run_webhook_receiver_example.py` executes the representative `webhook_receiver` example flow and generates the OpenAPI and Swagger UI artifacts used by the README.
- `make demo` regenerates the generated spec preview image and the Swagger UI preview image.
