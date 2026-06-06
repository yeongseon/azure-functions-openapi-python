# Azure Functions OpenAPI

[![PyPI](https://img.shields.io/pypi/v/azure-functions-openapi.svg)](https://pypi.org/project/azure-functions-openapi/)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://pypi.org/project/azure-functions-openapi/)
[![CI](https://github.com/yeongseon/azure-functions-openapi-python/actions/workflows/ci-test.yml/badge.svg)](https://github.com/yeongseon/azure-functions-openapi-python/actions/workflows/ci-test.yml)
[![Release](https://github.com/yeongseon/azure-functions-openapi-python/actions/workflows/publish-pypi.yml/badge.svg)](https://github.com/yeongseon/azure-functions-openapi-python/actions/workflows/publish-pypi.yml)
[![Security Scans](https://github.com/yeongseon/azure-functions-openapi-python/actions/workflows/security.yml/badge.svg)](https://github.com/yeongseon/azure-functions-openapi-python/actions/workflows/security.yml)
[![codecov](https://codecov.io/gh/yeongseon/azure-functions-openapi-python/branch/main/graph/badge.svg)](https://codecov.io/gh/yeongseon/azure-functions-openapi-python)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://pre-commit.com/)
[![Docs](https://img.shields.io/badge/docs-gh--pages-blue)](https://yeongseon.github.io/azure-functions-openapi-python/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

他の言語: [English](README.md) | [한국어](README.ko.md) | [简体中文](README.zh-CN.md)

**Azure Functions Python v2 プログラミング モデル**向けの OpenAPI（Swagger）ドキュメント生成と Swagger UI を提供します。

## Why Use It

Azure Functions の HTTP API をドキュメント化するには、通常、別途 OpenAPI スペックを手作業で管理する必要があります。`azure-functions-openapi` はデコレータ付きハンドラーからスペックを自動生成し、ドキュメントとコードの同期を維持します。

## Scope

- Azure Functions Python **v2 プログラミング モデル**
- decorator ベースの `func.FunctionApp()` アプリケーション
- `@openapi` で文書化された HTTP トリガー関数
- オプションの Pydantic スキーマ生成（Pydantic v1 と v2 の両方をサポート）

このパッケージは従来の `function.json` ベースの v1 プログラミング モデルには対応していません。

## Features

- operation メタデータ用の `@openapi` decorator
- `/openapi.json`, `/openapi.yaml`, `/docs` エンドポイント
- query, path, header, body, response スキーマのサポート
- セキュアなデフォルトを備えた Swagger UI helper
- 生成および検証ワークフローのための CLI ツール

## Installation

```bash
pip install azure-functions-openapi
```

Function App の依存関係には次を含めてください。

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

ローカルでは Azure Functions Core Tools で実行できます。

```bash
func start
```

## Demo

代表的な `webhook_receiver` サンプルは、このライブラリを導入したときの結果全体を示します。

- Azure Functions v2 の HTTP ハンドラーに `@openapi` を付与します。
- パッケージがそのルートに対する実際の OpenAPI ドキュメントを生成します。
- 同じルートがブラウザ確認用に Swagger UI でレンダリングされます。

### Generated Spec Result

生成された OpenAPI ファイルは、同じサンプル実行から静的プレビューとして取得されています。そのため、この README には代表的な関数が実際に生成したドキュメントが表示されます。

![OpenAPI spec preview](docs/assets/webhook_receiver_openapi_spec_preview.png)

### Swagger UI Result

以下の Web プレビューも同じ代表サンプルから生成されており、そのフローで作られた Swagger UI ページを自動的にレンダリングして取得したものです。

![OpenAPI Swagger UI preview](docs/assets/webhook_receiver_swagger_ui_preview.png)

## Documentation

- 全ドキュメント: [yeongseon.github.io/azure-functions-openapi-python](https://yeongseon.github.io/azure-functions-openapi-python/)
- スモークテスト済みサンプル: `examples/`
- [Installation Guide](docs/installation.md)
- [Usage Guide](docs/usage.md)
- [API Reference](docs/api.md)
- [CLI Guide](docs/cli.md)

## Ecosystem

- [azure-functions-langgraph](https://github.com/yeongseon/azure-functions-langgraph) — LangGraph デプロイアダプター
- [azure-functions-validation](https://github.com/yeongseon/azure-functions-validation) — リクエストとレスポンスのバリデーション
- [azure-functions-logging](https://github.com/yeongseon/azure-functions-logging) — 構造化ロギング
- [azure-functions-doctor](https://github.com/yeongseon/azure-functions-doctor) — 診断 CLI
- [azure-functions-scaffold](https://github.com/yeongseon/azure-functions-scaffold) — プロジェクトスキャフォールディング
- [azure-functions-durable-graph](https://github.com/yeongseon/azure-functions-durable-graph) — Durable Functions ベースのグラフランタイム
- [azure-functions-python-cookbook](https://github.com/yeongseon/azure-functions-python-cookbook) — レシピとサンプル

## Disclaimer

このプロジェクトは独立したコミュニティプロジェクトであり、Microsoft と提携・承認・保守関係にはありません。

Azure および Azure Functions は Microsoft Corporation の商標です。

## License

MIT
