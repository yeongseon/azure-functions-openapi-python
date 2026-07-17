"""Tests for the public API surface of azure-functions-openapi."""

import azure_functions_openapi


class TestAPISurface:
    """Verify __all__ matches exactly the declared public names."""

    def test_all_exports(self) -> None:
        assert set(azure_functions_openapi.__all__) == {
            "__version__",
            "OPENAPI_VERSION_3_0",
            "OPENAPI_VERSION_3_1",
            "OpenAPISpecConfigError",
            "SDKIncompatibleError",
            "OpenAPIOperationMetadata",
            "clear_openapi_registry",
            "generate_openapi_spec",
            "get_openapi_json",
            "get_openapi_yaml",
            "openapi",
            "register_openapi_metadata",
            "render_swagger_ui",
            "scan_validation_metadata",
        }

    def test_version_matches_distribution_metadata(self) -> None:
        from importlib.metadata import version

        assert azure_functions_openapi.__version__ == version("azure-functions-openapi")

    def test_version_is_string(self) -> None:
        assert isinstance(azure_functions_openapi.__version__, str)

    def test_public_names_are_importable(self) -> None:
        from azure_functions_openapi import (  # noqa: F401
            OPENAPI_VERSION_3_0,
            OPENAPI_VERSION_3_1,
            OpenAPIOperationMetadata,
            OpenAPISpecConfigError,
            SDKIncompatibleError,
            clear_openapi_registry,
            generate_openapi_spec,
            get_openapi_json,
            get_openapi_yaml,
            openapi,
            register_openapi_metadata,
            render_swagger_ui,
            scan_validation_metadata,
        )

    def test_openapi_root_export_is_decorator(self) -> None:
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-W",
                "ignore::DeprecationWarning",
                "-c",
                "import azure_functions_openapi as p; "
                "from azure_functions_openapi.decorator import openapi as d; "
                "assert p.openapi is d, type(p.openapi).__name__",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr or result.stdout

    def test_openapi_submodule_is_importable_via_importlib(self) -> None:
        import importlib
        import types
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            openapi_module = importlib.import_module("azure_functions_openapi.openapi")

        assert isinstance(openapi_module, types.ModuleType)
        assert openapi_module.generate_openapi_spec is azure_functions_openapi.generate_openapi_spec

    def test_openapi_submodule_emits_deprecation_warning(self) -> None:
        import importlib
        import sys
        import warnings

        sys.modules.pop("azure_functions_openapi.openapi", None)
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            importlib.import_module("azure_functions_openapi.openapi")

        deprecations = [w for w in captured if issubclass(w.category, DeprecationWarning)]
        assert deprecations, "expected DeprecationWarning when importing the shim"
        assert "azure_functions_openapi.spec" in str(deprecations[0].message)

    def test_generate_openapi_spec_is_callable(self) -> None:
        assert callable(azure_functions_openapi.generate_openapi_spec)

    def test_openapi_spec_config_error_is_exception(self) -> None:
        assert issubclass(azure_functions_openapi.OpenAPISpecConfigError, Exception)
