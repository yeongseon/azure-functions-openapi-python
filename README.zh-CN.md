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

其他语言: [English](README.md) | [한국어](README.ko.md) | [日本語](README.ja.md)

为 **Azure Functions Python v2 编程模型**提供 OpenAPI（Swagger）文档生成和 Swagger UI。

## Why Use It

记录 Azure Functions HTTP API 通常需要手动维护单独的 OpenAPI 规范。`azure-functions-openapi` 可从带装饰器的处理函数自动生成规范，使文档和代码始终保持同步。

## Before / After

**❌ 不使用 azure-functions-openapi** — 手动维护规范

```python
# openapi_spec.json — 手写并手动更新
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

# function_app.py — 与上方的规范没有任何关联
@app.route(route="users", methods=["POST"])
def create_user(req):
    ...
```

规范会偏离，使用者只能猜测，也没有 Swagger UI。

**✅ 使用 azure-functions-openapi** — 规范就在处理器旁边

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

# 自动生成的端点：
# GET /api/openapi.json  — 始终与代码同步
# GET /api/docs          — 内置 Swagger UI
```

规范始终与代码一致，开箱即用的 Swagger UI。

## Scope

- Azure Functions Python **v2 编程模型**
- 基于 decorator 的 `func.FunctionApp()` 应用
- 使用 `@openapi` 记录文档的 HTTP 触发函数
- Pydantic schema 生成（需要 Pydantic v2）

此包**不支持**传统的基于 `function.json` 的 v1 编程模型。

## Features

- 用于 operation 元数据的 `@openapi` decorator
- `/openapi.json`、`/openapi.yaml` 和 `/docs` 端点
- 支持 query、path、header、body 和 response schema
- 带有安全默认值的 Swagger UI helper
- 用于生成和校验工作流的 CLI 工具

## Installation

```bash
pip install azure-functions-openapi
```

你的 Function App 依赖应包含：

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


# 使用普通的 Pydantic 模型描述你的 API。
class GreetRequest(BaseModel):
    name: str


class GreetResponse(BaseModel):
    message: str


# @openapi 会从下方的 @app.route 推断 route 和 method —
# 无需在此处重复指定。
@openapi(
    summary="Greet user",
    tags=["Example"],
    request_model=GreetRequest,
    response_model=GreetResponse,
)
@app.route(route="http_trigger", auth_level=func.AuthLevel.ANONYMOUS, methods=["POST"])
def http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    # @openapi 仅记录请求/响应契约，并不进行验证。
    # 运行时验证请参阅 azure-functions-validation。
    data = req.get_json()
    name = data.get("name", "world")
    return func.HttpResponse(
        json.dumps({"message": f"Hello, {name}!"}),
        mimetype="application/json",
    )
```

> **Pydantic v2 为可选项。** 推荐使用 `request_model=` / `response_model=`，但如果你不想添加依赖，也可以改为传入原始 JSON Schema dict（见下文）。

<details>
<summary>连接规范 + Swagger UI 端点 (openapi.json / openapi.yaml / docs)</summary>

```python
# 将生成的规范和 Swagger UI 作为普通 HTTP 路由提供。
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
<summary>高级：使用原始 JSON Schema 而非 Pydantic 描述模式</summary>

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

在本地可使用 Azure Functions Core Tools 运行。

```bash
func start
```

## Demo

代表性的 `webhook_receiver` 示例展示了采用该库后的完整效果：

- 你为 Azure Functions v2 的 HTTP 处理函数添加 `@openapi`。
- 该包会为该路由生成真实的 OpenAPI 文档。
- 同一路由会被渲染为 Swagger UI，便于在浏览器中查看。

### Generated Spec Result

生成的 OpenAPI 文件来自同一次示例运行，并被捕获为静态预览。因此，此 README 展示的就是代表性函数实际生成的文档。

![OpenAPI spec preview](docs/assets/hello_openapi_spec_preview.png)

### Swagger UI Result

下面的网页预览也来自同一个代表性示例，并由该示例流程生成的 Swagger UI 页面自动渲染和截图得到。

![OpenAPI Swagger UI preview](docs/assets/hello_openapi_swagger_ui_preview.png)

## Documentation

- 完整文档: [yeongseon.github.io/azure-functions-openapi-python](https://yeongseon.github.io/azure-functions-openapi-python/)
- 经过 smoke test 的示例: `examples/`
- [Installation Guide](docs/installation.md)
- [Usage Guide](docs/usage.md)
- [API Reference](docs/api.md)
- [CLI Guide](docs/cli.md)

## Ecosystem

- [azure-functions-langgraph](https://github.com/yeongseon/azure-functions-langgraph) — LangGraph 部署适配器
- [azure-functions-validation](https://github.com/yeongseon/azure-functions-validation) — 请求与响应校验
- [azure-functions-logging](https://github.com/yeongseon/azure-functions-logging) — 结构化日志
- [azure-functions-doctor](https://github.com/yeongseon/azure-functions-doctor) — 诊断 CLI
- [azure-functions-scaffold](https://github.com/yeongseon/azure-functions-scaffold) — 项目脚手架
- [azure-functions-durable-graph](https://github.com/yeongseon/azure-functions-durable-graph) — 基于 Durable Functions 的图运行时
- [azure-functions-python-cookbook](https://github.com/yeongseon/azure-functions-python-cookbook) — 食谱与示例

## Disclaimer

本项目是独立的社区项目，与 Microsoft 没有关联，也未获得 Microsoft 的认可或维护。

Azure 和 Azure Functions 是 Microsoft Corporation 的商标。

## License

MIT
