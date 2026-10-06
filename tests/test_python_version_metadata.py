from __future__ import annotations

from email.parser import BytesParser
from pathlib import Path
import subprocess
import sys
import tarfile
import tomllib
from zipfile import ZipFile

from packaging.specifiers import SpecifierSet
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_PYTHON = SpecifierSet(">=3.11,<3.15")


@pytest.fixture(scope="module")
def built_metadata(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, str]:
    # Given isolated output for both distribution formats
    output = tmp_path_factory.mktemp("dist")

    # When the project builds its wheel and source distribution
    subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(output)],
        cwd=PROJECT_ROOT,
        check=True,
    )

    # Then expose the metadata embedded in each artifact
    wheel = next(output.glob("*.whl"))
    with ZipFile(wheel) as archive:
        wheel_metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        wheel_metadata = archive.read(wheel_metadata_name).decode()
    sdist = next(output.glob("*.tar.gz"))
    with tarfile.open(sdist) as archive:
        pkg_info = next(
            member for member in archive.getmembers() if member.name.endswith("/PKG-INFO")
        )
        extracted = archive.extractfile(pkg_info)
        assert extracted is not None
        sdist_metadata = extracted.read().decode()
    return wheel_metadata, sdist_metadata


def test_requires_python_declares_supported_range() -> None:
    # Given the source package metadata
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]

    # When the declared Python range is parsed semantically
    declared = SpecifierSet(project["requires-python"])

    # Then the complete normalized range is exactly the supported range
    assert declared == SUPPORTED_PYTHON


@pytest.mark.parametrize(
    "mutant",
    [">=3.11,<3.14.1", ">=3.11,<3.15,!=3.12.5"],
    ids=["narrow-upper-bound", "excluded-patch"],
)
def test_supported_range_rejects_semantically_different_mutants(mutant: str) -> None:
    # Given a range that agrees at each supported minor's .0 release
    mutated = SpecifierSet(mutant)

    # When the complete normalized range is compared
    # Then hidden boundary and interior exclusions are rejected
    assert mutated != SUPPORTED_PYTHON


def test_classifiers_match_supported_python_minors() -> None:
    # Given the source package metadata
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]

    # When version-specific Python classifiers are selected
    prefix = "Programming Language :: Python :: 3."
    classified_minors = {
        classifier.removeprefix(prefix)
        for classifier in project["classifiers"]
        if classifier.startswith(prefix)
    }

    # Then every and only supported minor version is advertised
    assert classified_minors == {"11", "12", "13", "14"}


@pytest.mark.parametrize("artifact_index", [0, 1], ids=["wheel", "sdist"])
def test_built_artifact_requires_python_matches_supported_range(
    built_metadata: tuple[str, str], artifact_index: int
) -> None:
    # Given metadata from a built wheel or source distribution
    metadata = BytesParser().parsebytes(built_metadata[artifact_index].encode())

    # When its Python requirement is parsed semantically
    declared = SpecifierSet(metadata["Requires-Python"])

    # Then the complete normalized range is exactly the supported range
    assert declared == SUPPORTED_PYTHON
