"""Verify wheel identity before excluding it from an installed dependency inventory."""

from __future__ import annotations

from dataclasses import dataclass
from email.parser import Parser
from importlib.metadata import distributions
from pathlib import Path
import re
from zipfile import ZipFile

from tools.security_report import EvidenceError, identifier


@dataclass(frozen=True, slots=True)
class Package:
    name: str
    version: str


def package(name: str, version: str) -> Package:
    normalized = re.sub(r"[-_.]+", "-", identifier(name)).lower()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*", version):
        raise EvidenceError("invalid installed version")
    return Package(normalized, version)


@dataclass(frozen=True, slots=True)
class Inventory:
    candidate: Package
    dependencies: tuple[Package, ...]

    def requirements(self) -> str:
        return "".join(f"{p.name}=={p.version}\n" for p in self.dependencies)


def verified_inventory(site_packages: Path, wheel: Path) -> Inventory:
    with ZipFile(wheel) as archive:
        metadata = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            raise EvidenceError("candidate wheel metadata missing or ambiguous")
        message = Parser().parsestr(archive.read(metadata[0]).decode("utf-8"))
    candidate = package(str(message.get("Name", "")), str(message.get("Version", "")))
    installed = tuple(
        package(dist.metadata["Name"], dist.version or "")
        for dist in distributions(path=[str(site_packages)])
    )
    matches = tuple(p for p in installed if p.name == candidate.name)
    if matches != (candidate,) or len({p.name for p in installed}) != len(installed):
        raise EvidenceError("candidate absent, mismatched or duplicate installed distribution")
    dependencies = tuple(sorted((p for p in installed if p != candidate), key=lambda p: p.name))
    if not dependencies:
        raise EvidenceError("empty third-party inventory")
    return Inventory(candidate, dependencies)
