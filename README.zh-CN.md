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

> ⚠️ 此翻译可能已过时。最新内容请参阅 [README.md](README.md)。

为 **Azure Functions Python v2 编程模型**提供 OpenAPI（Swagger）文档生成和 Swagger UI。

## Why Use It

记录 Azure Functions HTTP API 通常需要手动维护单独的 OpenAPI 规范。`azure-functions-openapi` 可从带装饰器的处理函数自动生成规范，使文档和代码始终保持同步。

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

from azure_functions_openapi import (
    get_openapi_json,
    get_openapi_yaml,
    openapi,
    render_swagger_ui,
)


app = func.FunctionApp()


@app.function_name(name="http_trigger")
@openapi(
    summary="Greet user",
    route="/api/http_trigger",
    method="post",
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
    tags=["Example"],
    )
@app.route(route="http_trigger", auth_level=func.AuthLevel.ANONYMOUS, methods=["POST"])
def http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    data = req.get_json()
    name = data.get("name", "world")
    return func.HttpResponse(
        json.dumps({"message": f"Hello, {name}!"}),
        mimetype="application/json",
    )

@app.function_name(name="openapi_json")
@app.route(route="openapi.json", auth_level=func.AuthLevel.ANONYMOUS, methods=["GET"])
def openapi_json(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_json(
            title="Sample API",
            description="OpenAPI document for the Sample API.",
        ),
        mimetype="application/json",
    )


@app.function_name(name="openapi_yaml")
@app.route(route="openapi.yaml", auth_level=func.AuthLevel.ANONYMOUS, methods=["GET"])
def openapi_yaml(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        get_openapi_yaml(
            title="Sample API",
            description="OpenAPI document for the Sample API.",
        ),
        mimetype="application/x-yaml",
    )


@app.function_name(name="swagger_ui")
@app.route(route="docs", auth_level=func.AuthLevel.ANONYMOUS, methods=["GET"])
def swagger_ui(req: func.HttpRequest) -> func.HttpResponse:
    return render_swagger_ui()
```

可使用 Azure Functions Core Tools 在本地运行：

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

本包是 **Azure Functions Python DX Toolkit** 的一部分。

**设计原则：** `azure-functions-openapi` 负责 API 文档与规范生成。`azure-functions-validation` 负责请求/响应校验与序列化。`azure-functions-langgraph` 负责 LangGraph 运行时暴露。

| 包 | 职责 |
|---------|------|
| **azure-functions-openapi-python** | OpenAPI 规范生成与 Swagger UI |
| [azure-functions-validation-python](https://github.com/yeongseon/azure-functions-validation-python) | 请求/响应校验与序列化 |
| [azure-functions-db-python](https://github.com/yeongseon/azure-functions-db-python) | 基于 SQLAlchemy 的数据库集成助手（基于轮询的伪触发器，输入/输出/客户端注入） |
| [azure-functions-langgraph-python](https://github.com/yeongseon/azure-functions-langgraph-python) | 面向 Azure Functions 的 LangGraph 部署适配器 |
| [azure-functions-scaffold-python](https://github.com/yeongseon/azure-functions-scaffold-python) | 项目脚手架 CLI |
| [azure-functions-logging-python](https://github.com/yeongseon/azure-functions-logging-python) | 结构化日志与可观测性 |
| [azure-functions-doctor-python](https://github.com/yeongseon/azure-functions-doctor-python) | 部署前诊断 CLI |
| [azure-functions-durable-graph-python](https://github.com/yeongseon/azure-functions-durable-graph-python) | 基于 Durable Functions 的清单优先图运行时 *(实验性)* |
| [azure-functions-knowledge-python](https://github.com/yeongseon/azure-functions-knowledge-python) | 知识检索（RAG）装饰器 |
| [azure-functions-cookbook-python](https://github.com/yeongseon/azure-functions-cookbook-python) | 内部实践示例 — 可运行的完整工具链演示 |

## Disclaimer

本项目是独立的社区项目，与 Microsoft 没有关联，也未获得 Microsoft 的认可或维护。

Azure 和 Azure Functions 是 Microsoft Corporation 的商标。

## License

MIT
