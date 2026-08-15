# Azure Functions OpenAPI

[![PyPI](https://img.shields.io/pypi/v/azure-functions-openapi.svg)](https://pypi.org/project/azure-functions-openapi/)
[![Downloads](https://static.pepy.tech/badge/azure-functions-openapi/month)](https://pepy.tech/project/azure-functions-openapi)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://pypi.org/project/azure-functions-openapi/)
[![CI](https://github.com/yeongseon/azure-functions-openapi-python/actions/workflows/ci-test.yml/badge.svg)](https://github.com/yeongseon/azure-functions-openapi-python/actions/workflows/ci-test.yml)
[![Release](https://github.com/yeongseon/azure-functions-openapi-python/actions/workflows/publish-pypi.yml/badge.svg)](https://github.com/yeongseon/azure-functions-openapi-python/actions/workflows/publish-pypi.yml)
[![Security Scans](https://github.com/yeongseon/azure-functions-openapi-python/actions/workflows/security.yml/badge.svg)](https://github.com/yeongseon/azure-functions-openapi-python/actions/workflows/security.yml)
[![codecov](https://codecov.io/gh/yeongseon/azure-functions-openapi-python/branch/main/graph/badge.svg)](https://codecov.io/gh/yeongseon/azure-functions-openapi-python)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://pre-commit.com/)
[![Docs](https://img.shields.io/badge/docs-yeongseon.dev-blue)](https://yeongseon.dev/azure-functions-python/openapi/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

他の言語: [English](README.md) | [한국어](README.ko.md) | [简体中文](README.zh-CN.md)

> ℹ️ この翻訳はコミュニティによる参考用であり、最新の [English README](README.md) より古い場合があります。正確な最新情報は英語版を参照してください。

**Azure Functions Python v2 プログラミング モデル**向けの OpenAPI（Swagger）ドキュメント生成と Swagger UI を提供します。

## Why Use It

Azure Functions の HTTP API をドキュメント化するには、通常、別途 OpenAPI スペックを手作業で管理する必要があります。`azure-functions-openapi` はデコレータ付きハンドラーからスペックを自動生成し、ドキュメントとコードの同期を維持します。

## Before / After

**❌ azure-functions-openapi なし** — スペックを手作業で管理

```python
# openapi_spec.json — 手で書き、手で更新
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

# function_app.py — 上のスペックとは何の連携もない
@app.route(route="users", methods=["POST"])
def create_user(req):
    ...
```

スペックはずれ、利用者は推測し、Swagger UI もありません。

**✅ azure-functions-openapi あり** — スペックがハンドラの隣に存在

```python
from pydantic import BaseModel


class CreateUserRequest(BaseModel):
    name: str


class UserResponse(BaseModel):
    id: str
    name: str


@openapi(
    summary="Create user",
    requests=CreateUserRequest,
    responses=UserResponse,
)
@app.route(route="users", methods=["POST"])
def create_user(req):
    ...

# 自動生成されるエンドポイント:
# GET /api/openapi.json  — 常にコードと同期
# GET /api/docs          — Swagger UI を含む
```

スペックは常にコードと一致します。Swagger UI も標準で提供されます。

## Scope

- Azure Functions Python **v2 プログラミング モデル**
- decorator ベースの `func.FunctionApp()` アプリケーション
- `@openapi` で文書化された HTTP トリガー関数
- Pydantic スキーマ生成（Pydantic v2 が必要）

このパッケージは従来の `function.json` ベースの v1 プログラミング モデルには対応していません。

## Features

- operation メタデータ用の `@openapi` decorator
- `/openapi.json`, `/openapi.yaml`, `/docs` エンドポイント
- query, path, header, body, response スキーマのサポート
- セキュアなデフォルトを備えた Swagger UI helper
- 生成および検証ワークフローのための CLI ツール

## CLI Quick Start

デコレーターを適用した関数アプリから OpenAPI スペックを生成します。

```bash
# インストール
pip install azure-functions-openapi

# 関数アプリモジュールからスペックを生成（@openapi ルートを登録）
azure-functions-openapi generate --app function_app --title "My API" --format json

# 整形してファイルに出力
azure-functions-openapi generate --app function_app --title "My API" --pretty --output openapi.json

# YAML 出力
azure-functions-openapi generate --app function_app --format yaml --output openapi.yaml
```

`module:variable` 形式を渡すと、`FunctionApp` インスタンスを解決し、`@validate_http` や `azure-functions-langgraph` などのプロデューサーが登録したエンドポイントメタデータのルートも検出して、`@openapi` ルートと 1 つのスペックにマージします。`module` のみを渡すと、CLI はモジュールをインポートし（`@openapi` デコレーターを実行）スペックを生成しますが、エンドポイントメタデータは検出しません。

```bash
azure-functions-openapi generate --app function_app:app --title "My API"
```

すべてのオプションと CI 統合の例は [CLI ガイド](docs/cli.md)を参照してください。

## Installation

```bash
pip install azure-functions-openapi
```

Function App の依存関係には次を含めてください。

```text
azure-functions
azure-functions-openapi
```

## SDK Compatibility

このパッケージは、`azure-functions` SDK からルート、メソッド、ハンドラーを 1 つの分離されたアダプター（`azure_functions_openapi.adapters`）を介して検出します。検出は **公開 API 優先** で、公開された冪等な `FunctionBuilder.build()` で列挙し、その他はすべて公開 `Function` アクセサー（`get_function_name` / `get_user_function` / `get_bindings` / `is_http_function`）を介して読み取ります。アダプターは冪等でない `FunctionApp.get_functions()` を決して呼び出しません。列挙に公開の代替手段がない **唯一** の非公開トークン `app._function_builders` のみがアダプター内部に分離され、必須のガードテストで保護されます。CI で明示的なマトリックスで検証します。経緯は [イシュー #258](https://github.com/yeongseon/azure-functions-openapi-python/issues/258) と [イシュー #327](https://github.com/yeongseon/azure-functions-openapi-python/issues/327) を参照してください。

| `azure-functions` | Python 3.10 | Python 3.11 | Python 3.12 | Python 3.13 | Python 3.14 |
| ----------------- | :---------: | :---------: | :---------: | :---------: | :---------: |
| `1.21.0`（下限）  | ✅ 検証済 |             |             |             |             |
| `1.24.0`          | ✅ 検証済 |             |             |             |             |
| `latest` (`<2.0`) | ✅ 検証済 | ✅ 検証済 | ✅ 検証済 | ✅ 検証済 | ✅ 検証済 |

`pyproject.toml` のバージョンピンは `azure-functions>=1.21.0,<2.0.0` です。下限が `1.21.0` なのは、それ以前のリリースが `FunctionBuilder.__call__` から `None` を返すためです（テストと CLI 抽出でデコレートされたハンドラーの直接呼び出しが壊れる）。より新しい SDK が必要な場合はイシューを開いてください。上限を設けているのは、`azure-functions` 2.x が Python < 3.13 のサポートを廃止し、まだ `@openapi` で検証されていないためです。

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


# 普通の Pydantic モデルで API を記述します。
class GreetRequest(BaseModel):
    name: str


class GreetResponse(BaseModel):
    message: str


# @openapi は下の @app.route から route と method を推論します —
# ここで再度指定する必要はありません。
@openapi(
    summary="Greet user",
    tags=["Example"],
    requests=GreetRequest,
    responses=GreetResponse,
)
@app.route(route="http_trigger", auth_level=func.AuthLevel.ANONYMOUS, methods=["POST"])
def http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    # @openapi はリクエスト/レスポンスの契約を文書化するだけで、検証はしません。
    # ランタイム検証は azure-functions-validation を参照してください。
    data = req.get_json()
    name = data.get("name", "world")
    return func.HttpResponse(
        json.dumps({"message": f"Hello, {name}!"}),
        mimetype="application/json",
    )
```

> **Pydantic v2 は任意です。** `requests=` / `responses=` を推奨しますが、依存関係を追加したくなければ生の JSON Schema dict を代わりに渡すこともできます（下記参照）。

<details>
<summary>スペック + Swagger UI エンドポイントの接続 (openapi.json / openapi.yaml / docs)</summary>

```python
# 生成されたスペックと Swagger UI を通常の HTTP ルートとして提供します。
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
<summary>上級: Pydantic の代わりに生の JSON Schema でスキーマを記述</summary>

```python
@openapi(
    summary="Greet user",
    tags=["Example"],
    requests={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
    responses={
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

![OpenAPI Swagger UI preview](docs/assets/webhook_receiver_openapi_swagger_ui_preview.png)

## Documentation

- 全ドキュメント: [yeongseon.dev/azure-functions-python/openapi](https://yeongseon.dev/azure-functions-python/openapi/)
- スモークテスト済みサンプル: `examples/`
- [Installation Guide](docs/installation.md)
- [Usage Guide](docs/usage.md)
- [API Reference](docs/api.md)
- [CLI Guide](docs/cli.md)
- **拡張する:** [プロデューサーガイド — 独自のエンドポイントメタデータを作成](docs/extending/producer-guide.md)

## Ecosystem

このパッケージは **Azure Functions Python DX Toolkit** の一部です。

**設計原則:** `azure-functions-openapi` は API ドキュメントとスペック生成を担当します。`azure-functions-validation` はリクエスト/レスポンスのバリデーションとシリアライズを担当します。`azure-functions-langgraph` は LangGraph ランタイムの公開を担当します。

| パッケージ | 役割 |
|---------|------|
| **azure-functions-openapi-python** | OpenAPI スペック生成と Swagger UI |
| [azure-functions-validation-python](https://github.com/yeongseon/azure-functions-validation-python) | リクエスト/レスポンスのバリデーションとシリアライズ |
| [azure-functions-db-python](https://github.com/yeongseon/azure-functions-db-python) | SQLAlchemy ベースの DB 統合ヘルパー（ポーリングベースの擬似トリガー、入力/出力/クライアント注入） |
| [azure-functions-langgraph-python](https://github.com/yeongseon/azure-functions-langgraph-python) | Azure Functions 向け LangGraph デプロイアダプター |
| [azure-functions-scaffold-python](https://github.com/yeongseon/azure-functions-scaffold-python) | プロジェクトスキャフォールディング CLI |
| [azure-functions-logging-python](https://github.com/yeongseon/azure-functions-logging-python) | 構造化ロギングと可観測性 |
| [azure-functions-doctor-python](https://github.com/yeongseon/azure-functions-doctor-python) | デプロイ前診断 CLI |
| [azure-functions-durable-graph-python](https://github.com/yeongseon/azure-functions-durable-graph-python) | Durable Functions によるマニフェストファーストのグラフランタイム *(実験的)* |
| [azure-functions-knowledge-python](https://github.com/yeongseon/azure-functions-knowledge-python) | 知識検索（RAG）デコレーター |
| [azure-functions-cookbook-python](https://github.com/yeongseon/azure-functions-cookbook-python) | ドッグフード例 — ツールキット全体を活用する実行可能なレシピ |

## Disclaimer

このプロジェクトは独立したコミュニティプロジェクトであり、Microsoft と提携・承認・保守関係にはありません。

Azure および Azure Functions は Microsoft Corporation の商標です。

## License

MIT
