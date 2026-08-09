# Azure Functions OpenAPI

[![PyPI](https://img.shields.io/pypi/v/azure-functions-openapi.svg)](https://pypi.org/project/azure-functions-openapi/)
[![Downloads](https://static.pepy.tech/badge/azure-functions-openapi/month)](https://pepy.tech/project/azure-functions-openapi)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://pypi.org/project/azure-functions-openapi/)
[![CI](https://github.com/yeongseon/azure-functions-openapi-python/actions/workflows/ci-test.yml/badge.svg)](https://github.com/yeongseon/azure-functions-openapi-python/actions/workflows/ci-test.yml)
[![Release](https://github.com/yeongseon/azure-functions-openapi-python/actions/workflows/publish-pypi.yml/badge.svg)](https://github.com/yeongseon/azure-functions-openapi-python/actions/workflows/publish-pypi.yml)
[![Security Scans](https://github.com/yeongseon/azure-functions-openapi-python/actions/workflows/security.yml/badge.svg)](https://github.com/yeongseon/azure-functions-openapi-python/actions/workflows/security.yml)
[![codecov](https://codecov.io/gh/yeongseon/azure-functions-openapi-python/branch/main/graph/badge.svg)](https://codecov.io/gh/yeongseon/azure-functions-openapi-python)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://pre-commit.com/)
[![Docs](https://img.shields.io/badge/docs-gh--pages-blue)](https://yeongseon.github.io/azure-functions-openapi-python/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Translation pending:** The CLI `--app module:variable` endpoint-metadata discovery section (added to the English [README.md](README.md) in #331) is not yet translated here. Tracking: [#334](https://github.com/yeongseon/azure-functions-openapi-python/issues/334).

다른 언어: [English](README.md) | [日本語](README.ja.md) | [简体中文](README.zh-CN.md)

**Azure Functions Python v2 프로그래밍 모델**을 위한 OpenAPI(Swagger) 문서화와 Swagger UI를 제공합니다.

## Why Use It

Azure Functions HTTP API를 문서화하려면 일반적으로 별도의 OpenAPI 스펙을 수동으로 유지해야 합니다. `azure-functions-openapi`는 데코레이터가 적용된 핸들러에서 자동으로 스펙을 생성하여 문서와 코드를 항상 동기화된 상태로 유지합니다.

## Before / After

**❌ azure-functions-openapi 없이** — 스펙을 손으로 관리

```python
# openapi_spec.json — 직접 작성하고 직접 갱신
{
    "paths": {
        "/api/users": {
            "post": {
                "summary": "Create user",
                "requestBody": { "...": "..." },
                "responses": { "200": { "...": "..." } }
            }
        }
    }
}

# function_app.py — 위 스펙과 아무런 연결이 없음
@app.route(route="users", methods=["POST"])
def create_user(req):
    ...
```

스펙은 어긋나고, 사용자는 추측하며, Swagger UI도 없습니다.

**✅ azure-functions-openapi 사용** — 스펙이 핸들러 옆에 존재

```python
from pydantic import BaseModel


class CreateUserRequest(BaseModel):
    name: str


class UserResponse(BaseModel):
    id: str
    name: str


@openapi(
    summary="Create user",
    request_model=CreateUserRequest,
    response_model=UserResponse,
)
@app.route(route="users", methods=["POST"])
def create_user(req):
    ...

# 자동 생성되는 엔드포인트:
# GET /api/openapi.json  — 항상 코드와 동기화
# GET /api/docs          — Swagger UI 포함
```

스펙이 항상 코드와 일치합니다. Swagger UI도 기본 제공됩니다.

## Scope

- Azure Functions Python **v2 프로그래밍 모델**
- decorator 기반 `func.FunctionApp()` 애플리케이션
- `@openapi`로 문서화된 HTTP 트리거 함수
- Pydantic 스키마 생성(Pydantic v2 필요)

이 패키지는 기존 `function.json` 기반의 v1 프로그래밍 모델은 지원하지 않습니다.

## Features

- operation 메타데이터를 위한 `@openapi` decorator
- `/openapi.json`, `/openapi.yaml`, `/docs` 엔드포인트
- query, path, header, body, response 스키마 지원
- 보안 기본값이 포함된 Swagger UI helper
- 생성 및 검증 워크플로를 위한 CLI 도구

## Installation

```bash
pip install azure-functions-openapi
```

Function App 의존성에는 다음이 포함되어야 합니다.

```text
azure-functions
azure-functions-openapi
```

## Quick Start

```python
import json

import azure.functions as func
from pydantic import BaseModel

from azure_functions_openapi import (
    get_openapi_json,
    get_openapi_yaml,
    openapi,
    render_swagger_ui,
)

app = func.FunctionApp()


# 일반 Pydantic 모델로 API를 기술합니다.
class GreetRequest(BaseModel):
    name: str


class GreetResponse(BaseModel):
    message: str


# @openapi는 아래 @app.route에서 route와 method를 추론합니다 —
# 여기서 다시 지정할 필요가 없습니다.
@openapi(
    summary="Greet user",
    tags=["Example"],
    request_model=GreetRequest,
    response_model=GreetResponse,
)
@app.route(route="http_trigger", auth_level=func.AuthLevel.ANONYMOUS, methods=["POST"])
def http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    # @openapi는 요청/응답 계약을 문서화할 뿐, 검증하지는 않습니다.
    # 런타임 검증은 azure-functions-validation을 참고하세요.
    data = req.get_json()
    name = data.get("name", "world")
    return func.HttpResponse(
        json.dumps({"message": f"Hello, {name}!"}),
        mimetype="application/json",
    )
```

> **Pydantic v2는 선택 사항입니다.** `request_model=` / `response_model=`을 권장하지만, 의존성을 추가하고 싶지 않다면 원시 JSON Schema dict를 대신 전달할 수 있습니다(아래 참고).

<details>
<summary>스펙 + Swagger UI 엔드포인트 연결 (openapi.json / openapi.yaml / docs)</summary>

```python
# 생성된 스펙과 Swagger UI를 일반 HTTP 라우트로 제공합니다.
@app.route(route="openapi.json", auth_level=func.AuthLevel.ANONYMOUS, methods=["GET"])
def openapi_json(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_json(
            title="Sample API",
            description="OpenAPI document for the Sample API.",
        ),
        mimetype="application/json",
    )


@app.route(route="openapi.yaml", auth_level=func.AuthLevel.ANONYMOUS, methods=["GET"])
def openapi_yaml(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_yaml(
            title="Sample API",
            description="OpenAPI document for the Sample API.",
        ),
        mimetype="application/x-yaml",
    )


@app.route(route="docs", auth_level=func.AuthLevel.ANONYMOUS, methods=["GET"])
def swagger_ui(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui()
```

</details>

<details>
<summary>고급: Pydantic 대신 원시 JSON Schema로 스키마 기술</summary>

```python
@openapi(
    summary="Greet user",
    tags=["Example"],
    request_body={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
    response={
        200: {
            "description": "Successful greeting",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                    }
                }
            },
        }
    },
)
@app.route(route="http_trigger", auth_level=func.AuthLevel.ANONYMOUS, methods=["POST"])
def http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    ...
```

</details>

로컬에서는 Azure Functions Core Tools로 실행할 수 있습니다.

```bash
func start
```

## Demo

대표 `webhook_receiver` 예제는 이 라이브러리를 도입했을 때의 전체 결과를 보여줍니다.

- Azure Functions v2 HTTP 핸들러에 `@openapi`를 추가합니다.
- 패키지가 해당 라우트에 대한 실제 OpenAPI 문서를 생성합니다.
- 같은 라우트가 브라우저에서 확인할 수 있도록 Swagger UI로 렌더링됩니다.

### Generated Spec Result

생성된 OpenAPI 파일은 같은 예제 실행 결과에서 정적 미리보기로 캡처되었습니다. 따라서 이 README에는 대표 함수가 실제로 생성한 문서가 그대로 표시됩니다.

![OpenAPI spec preview](docs/assets/hello_openapi_spec_preview.png)

### Swagger UI Result

아래 웹 미리보기 역시 같은 대표 예제에서 생성되었으며, 해당 예제 흐름이 만든 Swagger UI 페이지를 자동으로 렌더링해 캡처한 결과입니다.

![OpenAPI Swagger UI preview](docs/assets/hello_openapi_swagger_ui_preview.png)

## Documentation

- 전체 문서: [yeongseon.github.io/azure-functions-openapi-python](https://yeongseon.github.io/azure-functions-openapi-python/)
- 스모크 테스트된 예제: `examples/`
- [Installation Guide](docs/installation.md)
- [Usage Guide](docs/usage.md)
- [API Reference](docs/api.md)
- [CLI Guide](docs/cli.md)

## Ecosystem

이 패키지는 **Azure Functions Python DX Toolkit**의 일부입니다.

**설계 원칙:** `azure-functions-openapi`는 API 문서화와 스펙 생성을 담당합니다. `azure-functions-validation`은 요청/응답 검증과 직렬화를 담당합니다. `azure-functions-langgraph`는 LangGraph 런타임 노출을 담당합니다.

| 패키지 | 역할 |
|---------|------|
| **azure-functions-openapi-python** | OpenAPI 스펙 생성 및 Swagger UI |
| [azure-functions-validation-python](https://github.com/yeongseon/azure-functions-validation-python) | 요청/응답 검증 및 직렬화 |
| [azure-functions-db-python](https://github.com/yeongseon/azure-functions-db-python) | SQLAlchemy 기반 DB 통합 헬퍼 (폴링 기반 의사 트리거, 입력/출력/클라이언트 주입) |
| [azure-functions-langgraph-python](https://github.com/yeongseon/azure-functions-langgraph-python) | Azure Functions용 LangGraph 배포 어댑터 |
| [azure-functions-scaffold-python](https://github.com/yeongseon/azure-functions-scaffold-python) | 프로젝트 스캐폴딩 CLI |
| [azure-functions-logging-python](https://github.com/yeongseon/azure-functions-logging-python) | 구조화된 로깅 및 관측성 |
| [azure-functions-doctor-python](https://github.com/yeongseon/azure-functions-doctor-python) | 배포 전 진단 CLI |
| [azure-functions-durable-graph-python](https://github.com/yeongseon/azure-functions-durable-graph-python) | Durable Functions 기반 매니페스트 우선 그래프 런타임 *(실험적)* |
| [azure-functions-knowledge-python](https://github.com/yeongseon/azure-functions-knowledge-python) | 지식 검색(RAG) 데코레이터 |
| [azure-functions-cookbook-python](https://github.com/yeongseon/azure-functions-cookbook-python) | 도그푸드 예제 — 전체 툴킷을 활용하는 실행 가능한 레시피 |

## Disclaimer

이 프로젝트는 독립적인 커뮤니티 프로젝트이며 Microsoft와 제휴되어 있지 않고, Microsoft의 후원이나 유지보수를 받지 않습니다.

Azure 및 Azure Functions는 Microsoft Corporation의 상표입니다.

## License

MIT
