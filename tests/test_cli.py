# tests/test_cli.py
"""Tests for CLI module."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from unittest import mock

import pytest

from azure_functions_openapi.cli import _import_app_module, handle_generate, main


class TestMain:
    """Tests for main() entry point."""

    def test_no_command_prints_help_and_returns_1(self) -> None:
        """Test that no command prints help and returns exit code 1."""
        with mock.patch.object(sys, "argv", ["azure-functions-openapi"]):
            result = main()
            assert result == 1

    def test_unknown_command_exits_with_error(self) -> None:
        """Test that unknown command exits with SystemExit (argparse behavior)."""
        with mock.patch.object(sys, "argv", ["azure-functions-openapi", "unknown"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2  # argparse exits with code 2 for errors

    def test_parse_args_unknown_command_path_returns_1(self) -> None:
        """Test explicit unknown command branch after parse_args."""
        args = mock.Mock(command="mystery")

        with mock.patch("argparse.ArgumentParser.parse_args", return_value=args):
            with mock.patch("builtins.print") as mock_print:
                result = main()

        assert result == 1
        mock_print.assert_called_with("Unknown command: mystery")

    def test_main_returns_1_when_handle_generate_raises(self) -> None:
        """Test main() error branch when generate handler raises."""
        args = mock.Mock(command="generate")

        with mock.patch("argparse.ArgumentParser.parse_args", return_value=args):
            with mock.patch(
                "azure_functions_openapi.cli.handle_generate",
                side_effect=RuntimeError("boom"),
            ):
                with mock.patch("builtins.print") as mock_print:
                    result = main()

        assert result == 1
        mock_print.assert_called_with("Error: boom", file=sys.stderr)


class TestHandleGenerate:
    """Tests for handle_generate() command."""

    def test_generate_json_default(self) -> None:
        """Test default JSON generation."""
        args = mock.Mock()
        args.title = "Test API"
        args.version = "1.0.0"
        args.format = "json"
        args.output = None
        args.pretty = False
        args.openapi_version = "3.0"
        args.app = None

        _spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {"/hello": {"get": {"responses": {"200": {"description": "ok"}}}}},
        }
        with mock.patch("azure_functions_openapi.cli.generate_openapi_spec", return_value=_spec):
            with mock.patch("builtins.print") as mock_print:
                result = handle_generate(args)

        assert result == 0
        mock_print.assert_called_once()
        output = mock_print.call_args[0][0]
        spec = json.loads(output)
        assert spec["openapi"] == "3.0.0"
        assert spec["info"]["title"] == "Test API"
        assert spec["info"]["version"] == "1.0.0"
        # --pretty=False → compact (no indent)
        assert "\n" not in output or output == output.strip()

    def test_generate_json_pretty(self) -> None:
        """Test pretty-print JSON: output should be indented."""
        args = mock.Mock()
        args.title = "Test API"
        args.version = "1.0.0"
        args.format = "json"
        args.output = None
        args.pretty = True
        args.openapi_version = "3.0"
        args.app = None

        with mock.patch("builtins.print") as mock_print:
            result = handle_generate(args)

        assert result == 0
        output = mock_print.call_args[0][0]
        # Pretty output must be multi-line with indentation
        assert "\n" in output
        assert "  " in output  # indent=2 produces leading spaces
        spec = json.loads(output)
        assert spec["openapi"] == "3.0.0"

    def test_generate_yaml_format(self) -> None:
        """Test YAML generation."""
        args = mock.Mock()
        args.title = "YAML API"
        args.version = "2.0.0"
        args.format = "yaml"
        args.output = None
        args.pretty = False
        args.openapi_version = "3.0"
        args.app = None

        _spec = {
            "openapi": "3.0.0",
            "info": {"title": "YAML API", "version": "2.0.0"},
            "paths": {"/hello": {"get": {"responses": {"200": {"description": "ok"}}}}},
        }
        with mock.patch("azure_functions_openapi.cli.generate_openapi_spec", return_value=_spec):
            with mock.patch("builtins.print") as mock_print:
                result = handle_generate(args)

        assert result == 0
        mock_print.assert_called_once()
        output = mock_print.call_args[0][0]
        assert "openapi:" in output
        assert "YAML API" in output

    def test_generate_openapi_version_3_1(self) -> None:
        """Test OpenAPI 3.1 generation."""
        args = mock.Mock()
        args.title = "API 3.1"
        args.version = "1.0.0"
        args.format = "json"
        args.output = None
        args.pretty = False
        args.openapi_version = "3.1"
        args.app = None

        _spec = {
            "openapi": "3.1.0",
            "info": {"title": "API 3.1", "version": "1.0.0"},
            "paths": {"/hello": {"get": {"responses": {"200": {"description": "ok"}}}}},
        }
        with mock.patch("azure_functions_openapi.cli.generate_openapi_spec", return_value=_spec):
            with mock.patch("builtins.print") as mock_print:
                result = handle_generate(args)

        assert result == 0
        mock_print.assert_called_once()
        output = mock_print.call_args[0][0]
        spec = json.loads(output)
        assert spec["openapi"] == "3.1.0"
        assert spec["info"]["title"] == "API 3.1"

    def test_generate_openapi_version_3_0_explicit(self) -> None:
        """Test explicit OpenAPI 3.0 generation."""
        args = mock.Mock()
        args.title = "API 3.0"
        args.version = "1.0.0"
        args.format = "json"
        args.output = None
        args.pretty = False
        args.openapi_version = "3.0"
        args.app = None

        with mock.patch("builtins.print") as mock_print:
            result = handle_generate(args)

        assert result == 0
        output = mock_print.call_args[0][0]
        spec = json.loads(output)
        assert spec["openapi"] == "3.0.0"

    def test_generate_with_output_file(self) -> None:
        """Test generation with output file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "openapi.json"

            args = mock.Mock()
            args.title = "File API"
            args.version = "1.0.0"
            args.format = "json"
            args.output = str(output_path)
            args.pretty = False
            args.openapi_version = "3.0"
            args.app = None

            result = handle_generate(args)

            assert result == 0
            assert output_path.exists()
            content = output_path.read_text()
            spec = json.loads(content)
            assert spec["info"]["title"] == "File API"

    def test_generate_yaml_with_openapi_3_1(self) -> None:
        """Test YAML generation with OpenAPI 3.1."""
        args = mock.Mock()
        args.title = "YAML 3.1 API"
        args.version = "1.0.0"
        args.format = "yaml"
        args.output = None
        args.pretty = False
        args.openapi_version = "3.1"
        args.app = None

        with mock.patch("builtins.print") as mock_print:
            result = handle_generate(args)

        assert result == 0
        output = mock_print.call_args[0][0]
        assert "openapi: 3.1.0" in output or "openapi: '3.1.0'" in output

    def test_generate_json_failure_returns_1(self) -> None:
        """Test JSON generation failure path."""
        args = mock.Mock(
            title="Broken API",
            version="1.0.0",
            format="json",
            output=None,
            pretty=False,
            openapi_version="3.0",
            app=None,
        )

        with mock.patch(
            "azure_functions_openapi.cli.generate_openapi_spec",
            side_effect=RuntimeError("boom"),
        ):
            with mock.patch("builtins.print") as mock_print:
                result = handle_generate(args)

        assert result == 1
        mock_print.assert_called_with(
            "Failed to generate OpenAPI specification: boom",
            file=sys.stderr,
        )

    def test_generate_output_file_failure_returns_1(self) -> None:
        """Test output file write failure path."""
        args = mock.Mock(
            title="Broken API",
            version="1.0.0",
            format="json",
            output="broken.json",
            pretty=False,
            openapi_version="3.0",
            app=None,
            fail_on_empty_paths=False,
        )

        spec_return: dict[str, object] = {"paths": {}, "info": {}}
        with mock.patch(
            "azure_functions_openapi.cli.generate_openapi_spec",
            return_value=spec_return,
        ):
            with mock.patch.object(Path, "write_text", side_effect=OSError("disk full")):
                with mock.patch("builtins.print") as mock_print:
                    result = handle_generate(args)

        assert result == 1
        # assert_any_call (not assert_called_with) because handle_generate may
        # emit multiple print() calls (e.g. progress messages) before writing;
        # we only care that the error message appeared at least once.

        mock_print.assert_any_call(
            "Failed to generate OpenAPI specification: disk full",
            file=sys.stderr,
        )


class TestCLIIntegration:
    """Integration tests for CLI commands via sys.argv."""

    def test_generate_command_via_main(self) -> None:
        """Test generate command through main()."""
        with mock.patch.object(
            sys, "argv", ["azure-functions-openapi", "generate", "--title", "CLI Test"]
        ):
            with mock.patch("builtins.print") as mock_print:
                result = main()

        assert result == 0
        output = mock_print.call_args[0][0]
        spec = json.loads(output)
        assert spec["info"]["title"] == "CLI Test"

    def test_generate_with_openapi_version_flag(self) -> None:
        """Test generate command with --openapi-version flag."""
        with mock.patch.object(
            sys,
            "argv",
            ["azure-functions-openapi", "generate", "--openapi-version", "3.1"],
        ):
            with mock.patch("builtins.print") as mock_print:
                result = main()

        assert result == 0
        output = mock_print.call_args[0][0]
        spec = json.loads(output)
        assert spec["openapi"] == "3.1.0"

    def test_generate_with_openapi_version_3_2(self) -> None:
        """Test generate command with --openapi-version 3.2."""
        with mock.patch.object(
            sys,
            "argv",
            ["azure-functions-openapi", "generate", "--openapi-version", "3.2"],
        ):
            with mock.patch("builtins.print") as mock_print:
                result = main()

        assert result == 0
        output = mock_print.call_args[0][0]
        spec = json.loads(output)
        assert spec["openapi"] == "3.2.0"

    def test_generate_with_all_options(self) -> None:
        """Test generate command with all options."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "spec.json"

            with mock.patch.object(
                sys,
                "argv",
                [
                    "azure-functions-openapi",
                    "generate",
                    "--title",
                    "Full Test",
                    "--version",
                    "2.0.0",
                    "--openapi-version",
                    "3.1",
                    "--format",
                    "json",
                    "--output",
                    str(output_path),
                ],
            ):
                result = main()

            assert result == 0
            assert output_path.exists()
            spec = json.loads(output_path.read_text())
            assert spec["openapi"] == "3.1.0"
            assert spec["info"]["title"] == "Full Test"
            assert spec["info"]["version"] == "2.0.0"


class TestMainExceptionHandling:
    """Tests for exception handling in main()."""

    def test_main_catches_exception_from_handle_generate(self) -> None:
        """When handle_generate raises, main() catches and returns 1."""
        with mock.patch.object(sys, "argv", ["azure-functions-openapi", "generate"]):
            with mock.patch(
                "azure_functions_openapi.cli.handle_generate",
                side_effect=RuntimeError("boom"),
            ):
                with mock.patch("builtins.print") as mock_print:
                    result = main()

                assert result == 1
                # Should print error to stderr
                mock_print.assert_called_once()
                assert "boom" in str(mock_print.call_args)


class TestHandleGenerateExceptionHandling:
    """Tests for exception handling in handle_generate()."""

    def test_handle_generate_catches_spec_generation_failure(self) -> None:
        """When get_openapi_json raises, handle_generate returns 1."""
        args = mock.Mock()
        args.title = "Test"
        args.version = "1.0.0"
        args.format = "json"
        args.output = None
        args.pretty = False
        args.openapi_version = "3.0"
        args.app = None

        with mock.patch(
            "azure_functions_openapi.cli.generate_openapi_spec",
            side_effect=RuntimeError("generation failed"),
        ):
            with mock.patch("builtins.print") as mock_print:
                result = handle_generate(args)

        assert result == 1
        mock_print.assert_called_once()
        assert "Failed to generate" in str(mock_print.call_args)

    def test_handle_generate_catches_yaml_generation_failure(self) -> None:
        """When get_openapi_yaml raises, handle_generate returns 1."""
        args = mock.Mock()
        args.title = "Test"
        args.version = "1.0.0"
        args.format = "yaml"
        args.output = None
        args.pretty = False
        args.openapi_version = "3.0"
        args.app = None

        with mock.patch(
            "azure_functions_openapi.cli.generate_openapi_spec",
            side_effect=RuntimeError("yaml failed"),
        ):
            with mock.patch("builtins.print") as mock_print:
                result = handle_generate(args)

        assert result == 1
        assert "Failed to generate" in str(mock_print.call_args)


class TestImportAppModule:
    """Tests for _import_app_module helper."""

    def test_plain_module_name_is_imported(self) -> None:
        """Plain 'module' format imports the module."""
        with mock.patch("importlib.import_module") as mock_import:
            _import_app_module("my_function_app")
        mock_import.assert_called_once_with("my_function_app")

    def test_module_colon_variable_format_imports_module_only(self) -> None:
        """'module:variable' format imports only the module part."""
        with mock.patch("importlib.import_module") as mock_import:
            _import_app_module("my_function_app:app")
        mock_import.assert_called_once_with("my_function_app")

    def test_empty_module_name_raises_value_error(self) -> None:
        """Empty module name (e.g. ':app') raises ValueError."""
        with pytest.raises(ValueError, match="Invalid --app value"):
            _import_app_module(":app")

    def test_import_error_propagates(self) -> None:
        """ImportError from a missing module propagates to caller."""
        with pytest.raises(ImportError):
            _import_app_module("nonexistent_module_xyz_12345")

    def test_nonexistent_variable_raises_attribute_error(self) -> None:
        """'module:nonexistent' raises AttributeError with a clear message."""
        import types

        fake_mod = types.ModuleType("fake_mod")
        with mock.patch("importlib.import_module", return_value=fake_mod):
            with pytest.raises(AttributeError, match="no attribute 'nonexistent'"):
                _import_app_module("fake_mod:nonexistent")

    def test_trailing_colon_raises_value_error(self) -> None:
        """'module:' (trailing colon, no variable) raises ValueError."""
        import types

        fake_mod = types.ModuleType("fake_mod")
        with mock.patch("importlib.import_module", return_value=fake_mod):
            with pytest.raises(ValueError, match="non-empty variable name"):
                _import_app_module("fake_mod:")

    def test_trailing_colon_whitespace_raises_value_error(self) -> None:
        """'module:   ' (whitespace-only variable) raises ValueError."""
        import types

        fake_mod = types.ModuleType("fake_mod")
        with mock.patch("importlib.import_module", return_value=fake_mod):
            with pytest.raises(ValueError, match="non-empty variable name"):
                _import_app_module("fake_mod:   ")

    def test_variable_resolving_to_none_raises_value_error(self) -> None:
        """'module:variable' where the attribute is None raises ValueError."""
        import types

        fake_mod = types.ModuleType("fake_mod")
        fake_mod.app = None  # type: ignore[attr-defined]
        with mock.patch("importlib.import_module", return_value=fake_mod):
            with pytest.raises(ValueError, match="resolved to None"):
                _import_app_module("fake_mod:app")


class TestHandleGenerateWithApp:
    """Tests for --app option in handle_generate."""

    def test_app_option_triggers_module_import(self) -> None:
        """handle_generate imports the specified module before generating."""
        args = mock.Mock()
        args.title = "Test API"
        args.version = "1.0.0"
        args.format = "json"
        args.output = None
        args.pretty = False
        args.openapi_version = "3.0"
        args.app = "my_function_app"

        with mock.patch("azure_functions_openapi.cli._import_app_module") as mock_import:
            mock_import.return_value = (None, False)
            with mock.patch("builtins.print"):
                result = handle_generate(args)

        assert result == 0
        mock_import.assert_called_once_with("my_function_app")

    def test_app_import_failure_returns_1(self) -> None:
        """If the module import fails, handle_generate returns exit code 1."""
        args = mock.Mock()
        args.title = "Test API"
        args.version = "1.0.0"
        args.format = "json"
        args.output = None
        args.pretty = False
        args.openapi_version = "3.0"
        args.app = "nonexistent_module_xyz"

        with mock.patch(
            "azure_functions_openapi.cli._import_app_module",
            side_effect=ImportError("No module named 'nonexistent_module_xyz'"),
        ):
            result = handle_generate(args)

        assert result == 1

    def test_app_attribute_error_returns_1(self) -> None:
        """If the named variable does not exist, handle_generate returns exit code 1."""
        args = mock.Mock()
        args.title = "Test API"
        args.version = "1.0.0"
        args.format = "json"
        args.output = None
        args.pretty = False
        args.openapi_version = "3.0"
        args.app = "function_app:nonexistent_var"

        with mock.patch(
            "azure_functions_openapi.cli._import_app_module",
            side_effect=AttributeError("Module 'function_app' has no attribute 'nonexistent_var'"),
        ):
            result = handle_generate(args)

        assert result == 1

    def test_no_app_option_skips_import(self) -> None:
        """When --app is not provided, no import is attempted."""
        args = mock.Mock()
        args.title = "Test API"
        args.version = "1.0.0"
        args.format = "json"
        args.output = None
        args.pretty = False
        args.openapi_version = "3.0"
        args.app = None

        with mock.patch("azure_functions_openapi.cli._import_app_module") as mock_import:
            mock_import.return_value = (None, False)
            with mock.patch("builtins.print"):
                result = handle_generate(args)

        assert result == 0
        mock_import.assert_not_called()


class TestEmptyPathsWarning:
    """Tests for the empty-paths guard warning."""

    def test_empty_paths_emits_warning_to_stderr(self) -> None:
        """When the generated spec has no paths, a hint is written to stderr."""
        args = mock.Mock()
        args.title = "Test API"
        args.version = "1.0.0"
        args.format = "json"
        args.output = None
        args.pretty = False
        args.openapi_version = "3.0"
        args.app = None
        args.fail_on_empty_paths = False

        empty_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {},
        }

        with mock.patch(
            "azure_functions_openapi.cli.generate_openapi_spec",
            return_value=empty_spec,
        ):
            with mock.patch("builtins.print") as mock_print:
                result = handle_generate(args)

        assert result == 0
        # Warning goes to stderr via print(..., file=sys.stderr)
        # We verify the print was called with the hint text by checking all calls.
        all_calls = str(mock_print.call_args_list)
        assert "--app" in all_calls

    def test_non_empty_paths_no_warning(self) -> None:
        """When paths are present, no warning is emitted."""
        args = mock.Mock()
        args.title = "Test API"
        args.version = "1.0.0"
        args.format = "json"
        args.output = None
        args.pretty = False
        args.openapi_version = "3.0"
        args.app = None

        spec_with_paths = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {"/hello": {"get": {"responses": {"200": {"description": "ok"}}}}},
        }

        with mock.patch(
            "azure_functions_openapi.cli.generate_openapi_spec",
            return_value=spec_with_paths,
        ):
            import io

            fake_stderr = io.StringIO()
            with mock.patch("sys.stderr", fake_stderr):
                with mock.patch("builtins.print"):
                    result = handle_generate(args)

        assert result == 0
        assert "--app" not in fake_stderr.getvalue()


class TestCLIAppFlag:
    """Integration tests for --app flag via sys.argv."""

    def test_app_flag_via_argv(self) -> None:
        """--app flag is parsed and passed through to handle_generate."""
        with mock.patch.object(
            sys,
            "argv",
            ["azure-functions-openapi", "generate", "--app", "function_app"],
        ):
            with mock.patch("azure_functions_openapi.cli._import_app_module") as mock_import:
                mock_import.return_value = (None, False)
                with mock.patch("builtins.print"):
                    result = main()

        assert result == 0
        mock_import.assert_called_once_with("function_app")

    def test_app_colon_variable_via_argv(self) -> None:
        """--app module:variable format is accepted via argv."""
        with mock.patch.object(
            sys,
            "argv",
            ["azure-functions-openapi", "generate", "--app", "function_app:app"],
        ):
            with mock.patch("azure_functions_openapi.cli._import_app_module") as mock_import:
                mock_import.return_value = (None, False)
                with mock.patch("builtins.print"):
                    result = main()

        assert result == 0
        mock_import.assert_called_once_with("function_app:app")


class TestFailOnEmptyPaths:
    """Tests for --fail-on-empty-paths flag."""

    def test_fail_on_empty_paths_returns_1_when_no_routes(self) -> None:
        """When --fail-on-empty-paths is set and spec has no paths, return 1."""
        args = mock.Mock()
        args.title = "Test API"
        args.version = "1.0.0"
        args.format = "json"
        args.output = None
        args.pretty = False
        args.openapi_version = "3.0"
        args.app = None
        args.fail_on_empty_paths = True

        empty_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {},
        }

        with mock.patch(
            "azure_functions_openapi.cli.generate_openapi_spec",
            return_value=empty_spec,
        ):
            with mock.patch("builtins.print"):
                result = handle_generate(args)

        assert result == 1

    def test_fail_on_empty_paths_false_returns_0_when_no_routes(self) -> None:
        """Without --fail-on-empty-paths, empty paths still returns 0."""
        args = mock.Mock()
        args.title = "Test API"
        args.version = "1.0.0"
        args.format = "json"
        args.output = None
        args.pretty = False
        args.openapi_version = "3.0"
        args.app = None
        args.fail_on_empty_paths = False

        empty_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {},
        }

        with mock.patch(
            "azure_functions_openapi.cli.generate_openapi_spec",
            return_value=empty_spec,
        ):
            with mock.patch("builtins.print"):
                result = handle_generate(args)

        assert result == 0

    def test_fail_on_empty_paths_flag_via_argv(self) -> None:
        """--fail-on-empty-paths flag is parsed and causes exit 1 when no routes."""
        with mock.patch.object(
            sys,
            "argv",
            ["azure-functions-openapi", "generate", "--fail-on-empty-paths"],
        ):
            empty_spec = {
                "openapi": "3.0.0",
                "info": {"title": "API", "version": "1.0.0"},
                "paths": {},
            }
            with mock.patch(
                "azure_functions_openapi.cli.generate_openapi_spec",
                return_value=empty_spec,
            ):
                with mock.patch("builtins.print"):
                    result = main()

        assert result == 1


class TestRoutePrefix:
    def test_route_prefix_default_is_api(self) -> None:
        with mock.patch.object(sys, "argv", ["azure-functions-openapi", "generate"]):
            with mock.patch("azure_functions_openapi.cli.generate_openapi_spec") as mock_gen:
                mock_gen.return_value = {"paths": {"/api/users": {}}}
                with mock.patch("builtins.print"):
                    main()

        _, kwargs = mock_gen.call_args
        assert kwargs.get("route_prefix") == "/api"

    def test_route_prefix_flag_passes_value(self) -> None:
        with mock.patch.object(
            sys,
            "argv",
            ["azure-functions-openapi", "generate", "--route-prefix", "/v1"],
        ):
            with mock.patch("azure_functions_openapi.cli.generate_openapi_spec") as mock_gen:
                mock_gen.return_value = {"paths": {"/v1/users": {}}}
                with mock.patch("builtins.print"):
                    main()

        _, kwargs = mock_gen.call_args
        assert kwargs.get("route_prefix") == "/v1"

    def test_route_prefix_flag_accepts_empty_string(self) -> None:
        with mock.patch.object(
            sys,
            "argv",
            ["azure-functions-openapi", "generate", "--route-prefix", ""],
        ):
            with mock.patch("azure_functions_openapi.cli.generate_openapi_spec") as mock_gen:
                mock_gen.return_value = {"paths": {"/users": {}}}
                with mock.patch("builtins.print"):
                    main()

        _, kwargs = mock_gen.call_args
        assert kwargs.get("route_prefix") == ""


class TestDescription:
    def test_description_default_uses_library_default(self) -> None:
        from azure_functions_openapi.spec import DEFAULT_OPENAPI_INFO_DESCRIPTION

        with mock.patch.object(sys, "argv", ["azure-functions-openapi", "generate"]):
            with mock.patch("azure_functions_openapi.cli.generate_openapi_spec") as mock_gen:
                mock_gen.return_value = {"paths": {"/api/users": {}}}
                with mock.patch("builtins.print"):
                    main()

        _, kwargs = mock_gen.call_args
        assert kwargs.get("description") == DEFAULT_OPENAPI_INFO_DESCRIPTION

    def test_description_flag_passes_value(self) -> None:
        with mock.patch.object(
            sys,
            "argv",
            [
                "azure-functions-openapi",
                "generate",
                "--description",
                "Custom CLI description with **markdown**",
            ],
        ):
            with mock.patch("azure_functions_openapi.cli.generate_openapi_spec") as mock_gen:
                mock_gen.return_value = {"paths": {"/api/users": {}}}
                with mock.patch("builtins.print"):
                    main()

        _, kwargs = mock_gen.call_args
        assert kwargs.get("description") == "Custom CLI description with **markdown**"

    def test_description_appears_in_generated_output(self) -> None:
        from azure_functions_openapi.decorator import (
            clear_openapi_registry,
            register_openapi_metadata,
        )

        clear_openapi_registry()
        register_openapi_metadata(path="/users", method="get")

        captured: list[str] = []

        def _capture(*args: object, **_kw: object) -> None:
            captured.append(" ".join(str(x) for x in args))

        with mock.patch.object(
            sys,
            "argv",
            [
                "azure-functions-openapi",
                "generate",
                "--description",
                "Spec for the Users API",
            ],
        ):
            with mock.patch("builtins.print", side_effect=_capture):
                rc = main()

        assert rc == 0
        joined = "\n".join(captured)
        assert "Spec for the Users API" in joined


class TestIsolateAppFailClosed:
    """#391: --isolate-app must fail closed when it cannot be honored, rather
    than silently falling back to the shared global registry with rc==0."""

    @staticmethod
    def _isolate_args(app: str | None) -> mock.Mock:
        args = mock.Mock()
        args.isolate_app = True
        args.app = app
        return args

    def test_isolate_without_app_exits_non_zero(self) -> None:
        args = self._isolate_args(None)
        with mock.patch("builtins.print") as mock_print:
            result = handle_generate(args)
        assert result == 1
        message = " ".join(str(c.args[0]) for c in mock_print.call_args_list)
        assert "--isolate-app" in message
        assert "--app" in message

    def test_isolate_with_module_without_variable_exits_non_zero(self) -> None:
        args = self._isolate_args("function_app")
        # A bare module resolves an app object but reports no ':variable', so
        # isolation cannot be scoped to a single FunctionApp.
        with mock.patch(
            "azure_functions_openapi.cli._import_app_module",
            return_value=(mock.Mock(), False),
        ):
            with mock.patch("builtins.print") as mock_print:
                result = handle_generate(args)
        assert result == 1
        message = " ".join(str(c.args[0]) for c in mock_print.call_args_list)
        assert "--isolate-app" in message
        assert "cannot be honored" in message
