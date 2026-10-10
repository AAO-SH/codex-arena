from __future__ import annotations

import json
import os
import importlib.util
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
import inspect
import venv
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("private_name", [".env.production", "signing.key", "secret.pem"])
def test_manifest_rejects_local_credentials(tmp_path, monkeypatch, private_name):
    spec = importlib.util.spec_from_file_location("arena_distribution", ROOT / "packaging/build_distribution.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    (tmp_path / private_name).write_text("test-only marker", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"version": "1.0.0", "files": [private_name]}), encoding="utf-8")
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "MANIFEST_PATH", manifest)
    with pytest.raises(ValueError, match="credential"):
        builder._payload_files()


def test_payload_rejects_reparse_point_without_python312_junction_api(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("arena_distribution", ROOT / "packaging/build_distribution.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    class Windows311ReparsePoint:
        def is_symlink(self):
            return False
        def lstat(self):
            return SimpleNamespace(st_file_attributes=0x400)
    assert builder._is_link(Windows311ReparsePoint())


def _extract(archive: tarfile.TarFile, destination: Path) -> None:
    if "filter" in inspect.signature(archive.extractall).parameters:
        archive.extractall(destination, filter="data")
    else:
        archive.extractall(destination)


@pytest.fixture(scope="module")
def built_distributions(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("arena-releases") / "artifacts"
    result = subprocess.run(
        [sys.executable, "packaging/build_distribution.py", "--output", str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return output


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_npm_tarball_runs_packaged_cli_in_unicode_workspace(
    built_distributions: Path, tmp_path: Path
) -> None:
    node = shutil.which("node")
    assert node, "Node.js is required to verify the npm package"
    archives = list((built_distributions / "npm").glob("*.tgz"))
    assert len(archives) == 1
    package_dir = tmp_path / "npm package"
    package_dir.mkdir()
    with tarfile.open(archives[0], "r:gz") as archive:
        _extract(archive, package_dir)
    package_root = package_dir / "package"
    package_metadata = json.loads((package_root / "package.json").read_text(encoding="utf-8"))
    assert package_metadata["name"] == "@aao-sh/codex-arena"
    assert package_metadata["engines"]["node"] == ">=22"
    assert package_metadata["repository"]["url"] == "https://github.com/AAO-SH/codex-arena.git"
    assert package_metadata["publishConfig"]["access"] == "public"
    registry_readme = (package_root / "README.md").read_text(encoding="utf-8")
    assert "https://raw.githubusercontent.com/AAO-SH/codex-arena/main/assets/codex-arena-logo.png" in registry_readme
    assert "https://github.com/AAO-SH/codex-arena/blob/main/references/packaging.md" in registry_readme
    python_env = {**os.environ, "PYTHON": sys.executable}

    listing = _run(
        [node, str(package_root / "bin" / "codex-arena.js"), "--help"],
        cwd=tmp_path,
        env=python_env,
    )
    assert "install" in listing
    assert _run(
        [node, str(package_root / "bin" / "codex-arena.js"), "--version"],
        cwd=tmp_path,
        env=python_env,
    ).strip() == f"codex-arena {package_metadata['version']}"

    workspace = tmp_path / "Projeto Ω com espaço"
    workspace.mkdir()
    _run(
        [
            node,
            str(package_root / "bin" / "codex-arena.js"),
            "install",
            "--workspace",
            str(workspace),
        ],
        cwd=tmp_path,
        env=python_env,
    )
    doctor = _run(
        [
            node,
            str(package_root / "bin" / "codex-arena.js"),
            "doctor",
            "--workspace",
            str(workspace),
            "--offline",
        ],
        cwd=tmp_path,
        env=python_env,
    )
    assert "Diagnóstico" in doctor
    installed = workspace / ".agents" / "skills" / "codex-arena"
    assert (installed / "SKILL.md").is_file()
    assert (installed / "assets" / "codex-arena-logo.png").is_file()
    assert (installed / "assets" / "aao-logo.svg").is_file()


def test_pypi_wheel_and_sdist_are_rebuildable_and_installable(
    built_distributions: Path, tmp_path: Path
) -> None:
    python_dist = built_distributions / "pypi"
    wheels = list(python_dist.glob("*.whl"))
    sdists = list(python_dist.glob("*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1

    with tarfile.open(sdists[0], "r:gz") as archive:
        members = {member.name for member in archive.getmembers()}
    assert any(name.endswith("/codex_arena/payload/SKILL.md") for name in members)
    assert not any(name.endswith("/references/development-contract.md") for name in members)

    source_archive = tmp_path / "codex_arena_source"
    source_archive.mkdir()
    with tarfile.open(sdists[0], "r:gz") as archive:
        _extract(archive, source_archive)
    source_tree = next(source_archive.iterdir())
    rebuilt_output = tmp_path / "rebuilt wheel"
    if shutil.which("uv"):
        build_command = [
            shutil.which("uv") or "uv",
            "build",
            "--wheel",
            "--out-dir",
            str(rebuilt_output),
            str(source_tree),
        ]
    else:
        build_command = [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(rebuilt_output),
            str(source_tree),
        ]
    _run(build_command, cwd=tmp_path)
    rebuilt_wheels = list(rebuilt_output.glob("*.whl"))
    assert len(rebuilt_wheels) == 1
    with zipfile.ZipFile(rebuilt_wheels[0]) as archive:
        assert "codex_arena/payload/assets/codex-arena-logo.png" in archive.namelist()
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8")
        assert "Name: codex-arena" in metadata
        assert "Requires-Python: >=3.11" in metadata
        assert "Requires-Dist:" not in metadata

    environment = tmp_path / "isolated python"
    venv.EnvBuilder(with_pip=True).create(environment)
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    entry_point = scripts / ("codex-arena.exe" if os.name == "nt" else "codex-arena")
    _run(
        [str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(rebuilt_wheels[0])],
        cwd=tmp_path,
    )
    assert "install" in _run([str(entry_point), "--help"], cwd=tmp_path)
    workspace = tmp_path / "Meu Projeto 漢字"
    workspace.mkdir()
    _run(
        [str(entry_point), "install", "--workspace", str(workspace)], cwd=tmp_path
    )
    doctor = _run(
        [str(entry_point), "doctor", "--workspace", str(workspace), "--offline"],
        cwd=tmp_path,
    )
    assert "Diagnóstico" in doctor
    installed = workspace / ".agents" / "skills" / "codex-arena"
    assert (installed / "SKILL.md").is_file()
    assert (installed / "assets" / "codex-arena-logo.png").is_file()
    assert (installed / "assets" / "aao-logo-light.svg").is_file()


def test_built_payload_excludes_private_and_development_files(
    built_distributions: Path, tmp_path: Path
) -> None:
    archives = list((built_distributions / "npm").glob("*.tgz"))
    assert len(archives) == 1
    with tarfile.open(archives[0], "r:gz") as archive:
        names = {member.name for member in archive.getmembers()}
    assert "package/payload/SKILL.md" in names
    assert "package/payload/assets/codex-arena-logo.png" in names
    assert "package/payload/assets/aao-logo.svg" in names
    assert "package/payload/assets/aao-logo-light.svg" in names
    assert not any(
        forbidden in name.casefold()
        for name in names
        for forbidden in (
            "/.venv/",
            "/.codex/",
            "/.agents/",
            "/.scratch/",
            "/.memory/",
            "/.playbooks/",
            "development-contract.md",
            ".env",
            ".pypirc",
        )
    )
