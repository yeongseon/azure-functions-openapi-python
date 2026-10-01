# Installation

## Requirements

| Dependency | Version |
| --- | --- |
| Python | 3.10 -- 3.14 |
| Azure Functions Core Tools | Latest stable |
| Azure Functions programming model | v2 (`func.FunctionApp` with decorators) |

This library is **not** compatible with the legacy `function.json`-based v1 model.

## Install from PyPI

```bash
pip install azure-functions-openapi
```

### Verify the installation

```bash
python -c "import azure_functions_openapi; print(azure_functions_openapi.__version__)"
```

### Optional dependencies

Install the `dev` extras for local development:

```bash
pip install azure-functions-openapi[dev]
```

Install the `docs` extras to build the documentation site locally:

```bash
pip install azure-functions-openapi[docs]
```

If you also use `azure-functions-validation` for request/response validation,
install it alongside — `scan_endpoint_metadata()` will auto-discover
validation metadata without any extra configuration:

```bash
pip install azure-functions-openapi azure-functions-validation
```


## Add to requirements.txt

Azure Functions reads `requirements.txt` during deployment. Ensure both the runtime
SDK and this library are listed:

```text
azure-functions
azure-functions-openapi
```

If your endpoints use Pydantic models for request or response schemas, add Pydantic
as well:

```text
pydantic>=2.0
```

## Local Development Setup

Clone the repository and create a virtual environment:

```bash
git clone https://github.com/yeongseon/azure-functions-openapi-python.git
cd azure-functions-openapi-python
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .[dev]
```

Or use the Makefile shortcut:

```bash
make install
```

This creates the Hatch-managed environment and installs pre-commit hooks.

## Azure Functions Core Tools

The Core Tools provide the `func` CLI for local development and deployment.

Install using the official Microsoft instructions for your platform:

- **Windows**: [https://learn.microsoft.com/azure/azure-functions/functions-run-local](https://learn.microsoft.com/azure/azure-functions/functions-run-local)
- **macOS**: `brew tap azure/functions && brew install azure-functions-core-tools@4`
- **Linux**: [https://learn.microsoft.com/azure/azure-functions/functions-run-local](https://learn.microsoft.com/azure/azure-functions/functions-run-local)

Verify the installation:

```bash
func --version
```

## Deployment

### Azure Functions

Deploy with the Azure Functions Core Tools:

```bash
func azure functionapp publish <app-name>
```

The `requirements.txt` in your project root is installed automatically during deployment.

### Docker

If you deploy via a custom Docker image, install the package in your Dockerfile:

```dockerfile
FROM mcr.microsoft.com/azure-functions/python:4-python3.12

COPY requirements.txt /home/site/wwwroot/requirements.txt
RUN pip install -r /home/site/wwwroot/requirements.txt

COPY . /home/site/wwwroot
```

## Upgrading

Upgrade to the latest release:

```bash
pip install --upgrade azure-functions-openapi
```

Check the [Changelog](changelog.md) for breaking changes before upgrading across
major or minor versions.
