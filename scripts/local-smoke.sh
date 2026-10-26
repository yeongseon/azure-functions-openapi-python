#!/usr/bin/env bash
set -euo pipefail

root=$(pwd)
python=${PYTHON:-python3}
fail() { echo "Error: $*" >&2; exit 1; }
command -v "$python" >/dev/null || fail "Python >=3.11 is required (PYTHON=$python)"
"$python" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || fail "Python >=3.11 is required"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/openapi-smoke.XXXXXXXX")
pids=()
cleanup() {
    status=$?
    trap - EXIT
    trap '' INT TERM
    for pid in "${pids[@]}"; do kill -TERM -- "-$pid" 2>/dev/null || true; done
    if ((${#pids[@]})); then
        sleep 1
        for pid in "${pids[@]}"; do kill -KILL -- "-$pid" 2>/dev/null || true; done
        for pid in "${pids[@]}"; do wait "$pid" 2>/dev/null || true; done
    fi
    if ((status != 0)); then
        for log in "$tmp"/*.log; do
            if [[ -f "$log" ]]; then echo "--- $log"; cat "$log"; fi
        done
    fi
    rm -rf "$tmp"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Job control gives each service its own process group, including npm/worker descendants.
set -m

case "${1:-}" in
integration)
    for tool in func curl; do command -v "$tool" >/dev/null || fail "$tool is required for integration"; done
    azurite=(azurite)
    if ! command -v azurite >/dev/null; then
        command -v npx >/dev/null || fail "azurite or npx is required for integration"
        azurite=(npx --no-install azurite)
    fi
    smoke="$root/tests/host_smoke/.venv/bin/python"
    [[ -x "$smoke" ]] || fail "smoke venv missing: create tests/host_smoke/.venv and install tests/host_smoke/requirements.txt, pytest, pytest-cov, requests (see docs/development.md)"
    "$smoke" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || fail "smoke venv needs Python >=3.11"
    "$smoke" -c 'import azure_functions_openapi, pytest, pytest_cov, requests' || fail "smoke venv dependencies are missing; see docs/development.md"
    read -r host_port blob_port queue_port table_port < <("$python" - <<'PY'
from contextlib import ExitStack
import socket

with ExitStack() as stack:
    sockets = [stack.enter_context(socket.socket()) for _ in range(4)]
    for sock in sockets:
        sock.bind(("127.0.0.1", 0))
    print(*(sock.getsockname()[1] for sock in sockets))
PY
    )
    base="http://127.0.0.1:$host_port"
    export HOST_SMOKE_BASE_URL="$base"
    # Public Azurite development key, not an Azure credential. Override local.settings.json.
    export AzureWebJobsStorage="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:$blob_port/devstoreaccount1;QueueEndpoint=http://127.0.0.1:$queue_port/devstoreaccount1;TableEndpoint=http://127.0.0.1:$table_port/devstoreaccount1;"
    export FUNCTIONS_WORKER_RUNTIME=python FUNCTIONS_CORE_TOOLS_TELEMETRY_OPTOUT=1
    "${azurite[@]}" --silent --location "$tmp/azurite" \
        --blobHost 127.0.0.1 --queueHost 127.0.0.1 --tableHost 127.0.0.1 \
        --blobPort "$blob_port" --queuePort "$queue_port" --tablePort "$table_port" >"$tmp/azurite.log" 2>&1 &
    pids+=("$!")
    (cd tests/host_smoke; export PATH="$PWD/.venv/bin:$PATH"; exec func start --port "$host_port" --verbose) >"$tmp/host.log" 2>&1 &
    host_pid=$!
    pids+=("$host_pid")
    echo "Host smoke: $base (Azurite $blob_port/$queue_port/$table_port)"
    ready=false
    for ((attempt=0; attempt<60; attempt++)); do
        if curl --noproxy '*' --fail --silent --max-time 2 "$base/api/custom_name" --output "$tmp/custom.json"; then ready=true; break; fi
        kill -0 "$host_pid" 2>/dev/null || break
        kill -0 "${pids[0]}" 2>/dev/null || break
        sleep 2
    done
    [[ "$ready" == true ]] || fail "The custom-name route did not become ready"
    "$smoke" -c 'import json, sys; assert json.load(open(sys.argv[1])) == {"function_name": "custom_name"}' "$tmp/custom.json"
    curl --noproxy '*' --fail --silent --max-time 10 "$base/api/openapi.json" --output "$tmp/openapi.json"
    documented_path=$("$smoke" - "$tmp/openapi.json" <<'PY'
import json
import sys

with open(sys.argv[1]) as source:
    spec = json.load(source)
assert spec["openapi"]
paths = [path for path in spec["paths"] if path not in ("/api/openapi.json", "/api/docs")]
assert paths == ["/api/custom_name"], paths
print(paths[0])
PY
    )
    curl --noproxy '*' --fail --silent --max-time 10 "$base$documented_path" --output "$tmp/documented.json"
    "$smoke" -c 'import json, sys; assert json.load(open(sys.argv[1])) == {"function_name": "custom_name"}' "$tmp/documented.json"
    curl --noproxy '*' --fail --silent --max-time 10 "$base/api/docs" --output "$tmp/swagger.html"
    grep -q 'SwaggerUIBundle' "$tmp/swagger.html"
    "$smoke" -m pytest tests/host_smoke -m host_smoke --no-cov -rs
    if grep -Eq "0 functions (loaded|found \(Worker\))|No job functions found|Executed 'Functions\..*' \(Failed" "$tmp/host.log"; then
        fail "The Functions host reported indexing or invocation errors"
    fi
    ;;
wheel-smoke)
    : "${HATCH:?HATCH must name the Hatch executable}"
    "$HATCH" build -t wheel "$tmp/dist"
    "$python" -m venv "$tmp/venv"
    "$tmp/venv/bin/python" -m pip install --disable-pip-version-check "$tmp"/dist/*.whl
    "$tmp/venv/bin/python" -m pip check
    (cd "$tmp"; CHECKOUT="$root" "$tmp/venv/bin/python" -I - <<'PY'
import os
from pathlib import Path

import azure.functions as func
import azure_functions_openapi
from azure_functions_openapi import generate_openapi_spec, openapi, scan_endpoint_metadata

module_path = Path(azure_functions_openapi.__file__).resolve()
print(f"imported module: {module_path}")
assert not module_path.is_relative_to(Path(os.environ["CHECKOUT"]).resolve())
app = func.FunctionApp()

@openapi(summary="Artifact smoke", responses={200: {"description": "OK"}})
@app.route(route="artifact-smoke", methods=["GET"])
def artifact_smoke(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse("ok")

scan_endpoint_metadata(app)
spec = generate_openapi_spec()
assert spec["paths"]["/api/artifact-smoke"]["get"]
PY
    )
    ;;
*) fail "usage: local-smoke.sh integration|wheel-smoke" ;;
esac
