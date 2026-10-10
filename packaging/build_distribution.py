#!/usr/bin/env python3
"""Build local npm and PyPI artifacts from the same public skill payload."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.arena_install import _excluded_directory, _excluded_file

PACKAGING = ROOT / "packaging"
MANIFEST_PATH = PACKAGING / "payload-manifest.json"
EXPECTED_NPM_NAME = "@aao-sh/codex-arena"
EXPECTED_PYPI_NAME = "codex-arena"


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    # lstat exposes reparse points on Windows 3.11, before Path.is_junction exists.
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _relative_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError(f"payload entries must be non-empty paths: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"payload path escapes the source tree: {value!r}")
    return path


def _payload_files() -> tuple[str, list[PurePosixPath]]:
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read payload manifest {MANIFEST_PATH}: {exc}") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("version"), str):
        raise ValueError("payload manifest needs a string version")
    version = manifest["version"]
    required = manifest.get("files")
    optional = manifest.get("optional_files", [])
    if not isinstance(required, list) or not isinstance(optional, list):
        raise ValueError("payload manifest files and optional_files must be arrays")

    selected: list[PurePosixPath] = []
    seen: set[str] = set()
    for value in [*required, *optional]:
        relative = _relative_path(value)
        key = relative.as_posix()
        if key in seen:
            raise ValueError(f"duplicate payload path: {key}")
        seen.add(key)
        if key == "references/development-contract.md" or any(
            _excluded_directory(part) for part in relative.parts[:-1]
        ):
            raise ValueError(f"private or generated path is forbidden in the payload: {key}")
        source = ROOT
        for part in relative.parts:
            source = source / part
            if _is_link(source):
                raise ValueError(f"linked payload path is forbidden: {key}")
        if not source.exists() and value in optional:
            continue
        if not source.is_file():
            raise ValueError(f"payload file is missing, not regular, or linked: {key}")
        if _excluded_file(source.name):
            raise ValueError(f"credential file is forbidden in the payload: {key}")
        selected.append(relative)

    if not selected:
        raise ValueError("payload manifest is empty")
    return version, selected


def _copy_payload(payload_root: Path, selected: list[PurePosixPath]) -> None:
    payload_root.mkdir(parents=True, exist_ok=True)
    for relative in selected:
        source = ROOT.joinpath(*relative.parts)
        destination = payload_root.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)


def _validate_versions(version: str) -> None:
    npm = json.loads((PACKAGING / "npm" / "package.json").read_text(encoding="utf-8"))
    pyproject = tomllib.loads((PACKAGING / "pypi" / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject.get("project", {})
    if npm.get("name") != EXPECTED_NPM_NAME or npm.get("version") != version:
        raise ValueError("npm package name or version does not match the payload manifest")
    if project.get("name") != EXPECTED_PYPI_NAME or project.get("version") != version:
        raise ValueError("PyPI project name or version does not match the payload manifest")
    init_text = (PACKAGING / "pypi" / "codex_arena" / "__init__.py").read_text(encoding="utf-8")
    if f'__version__ = "{version}"' not in init_text:
        raise ValueError("Python package __version__ does not match the payload manifest")
    arena_text = (ROOT / "scripts" / "arena.py").read_text(encoding="utf-8")
    if not re.search(rf"version\s*=\s*['\"]codex-arena {re.escape(version)}['\"]", arena_text):
        raise ValueError("arena.py CLI version does not match the payload manifest")


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode:
        joined = " ".join(command)
        raise RuntimeError(
            f"command failed ({result.returncode}): {joined}\n{result.stdout}{result.stderr}"
        )
    return result


def build(output: Path) -> list[Path]:
    version, selected = _payload_files()
    _validate_versions(version)
    output.mkdir(parents=True, exist_ok=True)
    npm_output = output / "npm"
    pypi_output = output / "pypi"
    npm_output.mkdir(parents=True, exist_ok=True)
    pypi_output.mkdir(parents=True, exist_ok=True)

    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm was not found; install Node.js 22 or newer with npm")

    with tempfile.TemporaryDirectory(prefix="codex-arena-package-") as temporary:
        staging = Path(temporary)
        npm_stage = staging / "npm"
        shutil.copytree(PACKAGING / "npm", npm_stage)
        npm_payload = npm_stage / "payload"
        _copy_payload(npm_payload, selected)
        for name in ("README.md", "LICENSE", "NOTICE.md"):
            source = PACKAGING / "registry-readme.md" if name == "README.md" else npm_payload / name
            shutil.copyfile(source, npm_stage / name)

        packed = _run([npm, "pack", "--json", "--pack-destination", str(npm_output)], cwd=npm_stage)
        try:
            pack_records = json.loads(packed.stdout)
            npm_artifact = npm_output / pack_records[0]["filename"]
        except (json.JSONDecodeError, IndexError, KeyError, TypeError) as exc:
            raise RuntimeError(f"npm pack returned an unexpected result: {packed.stdout}") from exc
        if not npm_artifact.is_file():
            raise RuntimeError(f"npm did not create its tarball: {npm_artifact}")

        pypi_stage = staging / "pypi"
        shutil.copytree(PACKAGING / "pypi", pypi_stage)
        pypi_payload = pypi_stage / "codex_arena" / "payload"
        _copy_payload(pypi_payload, selected)
        for name in ("README.md", "LICENSE", "NOTICE.md"):
            source = PACKAGING / "registry-readme.md" if name == "README.md" else pypi_payload / name
            shutil.copyfile(source, pypi_stage / name)

        pypi_staging_output = staging / "pypi-output"
        pypi_staging_output.mkdir()
        build_arguments = [
            "--sdist",
            "--wheel",
            "--outdir",
            str(pypi_staging_output),
            str(pypi_stage),
        ]
        if importlib.util.find_spec("build") is not None:
            python_build = [sys.executable, "-m", "build", *build_arguments]
        else:
            uv = shutil.which("uv")
            if not uv:
                raise RuntimeError(
                    "Python package building requires the 'build' module or uv; "
                    "install it with 'python -m pip install build'"
                )
            python_build = [
                uv,
                "build",
                "--sdist",
                "--wheel",
                "--out-dir",
                str(pypi_staging_output),
                str(pypi_stage),
            ]
        built = _run(python_build, cwd=ROOT)
        pypi_artifacts = sorted(
            [*pypi_staging_output.glob("*.whl"), *pypi_staging_output.glob("*.tar.gz")],
            key=lambda path: path.name,
        )
        if len(pypi_artifacts) != 2:
            raise RuntimeError(
                f"Python build did not create one wheel and one sdist.\n{built.stdout}{built.stderr}"
            )
        for artifact in pypi_artifacts:
            shutil.copyfile(artifact, pypi_output / artifact.name)
        pypi_artifacts = [pypi_output / artifact.name for artifact in pypi_artifacts]

    return [npm_artifact, *pypi_artifacts]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".scratch" / "distributions",
        help="directory for the npm tarball, PyPI wheel, and source archive",
    )
    arguments = parser.parse_args(argv)
    output = arguments.output.expanduser().resolve()
    try:
        artifacts = build(output)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Codex Arena package build failed: {exc}", file=sys.stderr)
        return 1
    for artifact in artifacts:
        print(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
