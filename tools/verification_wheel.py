"""Offline wheel-install smoke outside the checkout, using installed dependencies."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile

from tools.verification_process import run


def main() -> int:
    directory = Path("test-results/verify/logs")
    code = run([sys.executable, "-m", "build", "--no-isolation"], directory / "build.log")
    if code:
        return code
    wheels = list(Path("dist").glob("*.whl"))
    if len(wheels) != 1:
        print("Expected exactly one wheel; clean stale dist artifacts before verifying")
        return 1
    with tempfile.TemporaryDirectory(prefix="openapi-wheel-") as temporary:
        root = Path(temporary)
        subprocess.run(
            [sys.executable, "-m", "venv", "--system-site-packages", str(root / "venv")], check=True
        )
        python = str(root / "venv/bin/python")
        packages = (
            root
            / "venv/lib"
            / f"python{sys.version_info.major}.{sys.version_info.minor}"
            / "site-packages"
        )
        (packages / "verification-dependencies.pth").write_text(
            sysconfig.get_path("purelib") + "\n"
        )
        code = run(
            [python, "-m", "pip", "install", "--no-deps", "--no-index", str(wheels[0].resolve())],
            directory / "wheel-install.log",
        )
        if code:
            return code
        script = (
            "from pathlib import Path; import azure.functions as f; "
            "import azure_functions_openapi as a; "
            f"assert Path(a.__file__).resolve().is_relative_to(Path({str(root)!r})); "
            "app=f.FunctionApp(); "
            "handler=lambda req: f.HttpResponse('ok'); "
            "app.route(route='wheel-smoke', methods=['GET'])("
            "a.openapi(summary='Wheel smoke',responses={200:{'description':'OK'}})(handler)); "
            "spec=a.generate_openapi_spec(app=app); assert '/api/wheel-smoke' in spec['paths']; "
            "print('Installed wheel generates the documented route outside checkout')"
        )
        result = subprocess.run([python, "-c", script], cwd=root, capture_output=True, text=True)
        (directory / "wheel-smoke.log").write_text(result.stdout + result.stderr)
        print(result.stdout + result.stderr)
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
