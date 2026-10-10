"""Transactional, workspace-local installation helpers for Codex Arena."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
import venv
from pathlib import Path
from typing import Any, Iterable


_PACKAGE_NAME = "codex-arena"
_CONFIG_START = "# BEGIN CODEX ARENA INSTALL CONFIG"
_CONFIG_END = "# END CODEX ARENA INSTALL CONFIG"
_MANIFEST_NAME = ".arena-install.json"
_ROLLBACK_STATE_NAME = "install-state.json"
_ROLLBACK_BACKUP_DIR = "install-backups"
_ROLLBACK_MARKER_NAME = "rollback.json"
_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".scratch",
    "scratch",
    ".holdout",
    "holdout",
    "heldout",
    ".memory",
    "memory",
    ".codex",
    ".agents",
    ".docs",
    ".playbooks",
    ".ssh",
    ".aws",
    ".azure",
    ".gnupg",
    "auth",
    "authentication",
    "credentials",
    "secrets",
}
_IGNORED_GENERATED_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
_EXCLUDED_FILE_NAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials",
    "credentials.json",
    "auth.json",
    "token",
    "token.json",
    "id_rsa",
    "id_ed25519",
    "known_hosts",
    "authorized_keys",
}
_EXCLUDED_SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".ppk"}
_PINNED_REQUIREMENT = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?"
    r"==[A-Za-z0-9][A-Za-z0-9+_.!-]*(?:\s*;\s*.+)?$"
)


def _norm(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def _reject_symlink_components(path: Path, stop: Path) -> None:
    """Refuse writes that would pass through a symlink or Windows junction."""
    stop_abs = stop.absolute()
    path_abs = path.absolute()
    try:
        parts = path_abs.relative_to(stop_abs).parts
    except ValueError as exc:
        raise ValueError(f"path escapes workspace: {path}") from exc
    cursor = stop_abs
    if cursor.exists() and cursor.is_symlink():
        raise ValueError(f"workspace path is a symlink: {cursor}")
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction()):
            raise ValueError(f"refusing to write through a link: {cursor}")


def _excluded_directory(name: str) -> bool:
    lowered = name.casefold()
    return lowered in _EXCLUDED_DIRS


def _excluded_file(name: str) -> bool:
    lowered = name.casefold()
    return (
        lowered in _EXCLUDED_FILE_NAMES
        or lowered.startswith(".env.")
        or lowered.startswith("credentials.")
        or lowered.startswith("auth.")
        or lowered.startswith("token.")
        or lowered.startswith("secret.")
        or lowered.startswith("id_rsa.")
        or lowered.startswith("id_ed25519.")
        or Path(lowered).suffix in _EXCLUDED_SECRET_SUFFIXES
    )


def _copy_package(source: Path, stage: Path) -> tuple[dict[str, str], list[str]]:
    stage.mkdir(parents=True)
    excluded: list[str] = []
    files: dict[str, str] = {}

    for current, directories, file_names in os.walk(source, topdown=True, followlinks=False):
        current_path = Path(current)
        relative_dir = current_path.relative_to(source)
        kept_directories: list[str] = []
        for name in sorted(directories):
            child = current_path / name
            relative = (relative_dir / name).as_posix()
            if _excluded_directory(name) or child.is_symlink() or (
                hasattr(child, "is_junction") and child.is_junction()
            ):
                excluded.append(relative)
                continue
            kept_directories.append(name)
            (stage / relative_dir / name).mkdir(parents=True, exist_ok=True)
        directories[:] = kept_directories

        for name in sorted(file_names):
            source_file = current_path / name
            relative_path = relative_dir / name
            relative = relative_path.as_posix()
            if name == _MANIFEST_NAME or _excluded_file(name) or name.casefold().endswith(".pyc"):
                excluded.append(relative)
                continue
            if source_file.is_symlink() or (
                hasattr(source_file, "is_junction") and source_file.is_junction()
            ):
                excluded.append(relative)
                continue
            destination = stage / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(source_file, destination)
            except OSError as exc:
                raise RuntimeError(f"could not copy {source_file}: {exc}") from exc
            files[relative] = _file_hash(destination)

    return dict(sorted(files.items())), sorted(excluded)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for block in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inventory_hash(files: dict[str, str]) -> str:
    encoded = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    stage = path.with_name(f".{path.name}.stage-{uuid.uuid4().hex}")
    try:
        stage.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(stage, path)
    finally:
        _remove_path(stage)


def _read_json(path: Path, description: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{description} is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{description} is malformed: {path}")
    return payload


def _tree_inventory(directory: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    if not directory.exists():
        return files
    for path in directory.rglob("*"):
        relative = path.relative_to(directory)
        if any(part.casefold() in _IGNORED_GENERATED_DIRS for part in relative.parts[:-1]):
            continue
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError(f"installed package contains a link: {path}")
        if path.is_file() and path.name != _MANIFEST_NAME and not path.name.casefold().endswith(".pyc"):
            files[relative.as_posix()] = _file_hash(path)
    return dict(sorted(files.items()))


def _assert_no_local_edits(directory: Path) -> None:
    if not directory.exists():
        return
    manifest_path = directory / _MANIFEST_NAME
    if not manifest_path.is_file():
        raise ValueError(
            f"existing install at {directory} has no Arena inventory; refusing to replace user files"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"existing install inventory is unreadable: {manifest_path}") from exc
    expected = manifest.get("files") if isinstance(manifest, dict) else None
    if (
        not isinstance(expected, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("inventory_sha256") != _inventory_hash(expected)
        or _tree_inventory(directory) != expected
    ):
        raise ValueError(
            f"local edits conflict with reinstall at {directory}; preserve or review those changes first"
        )


def _config_path_key(raw_path: str, workspace: Path) -> str:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = workspace / path
    return _norm(path)


def _render_config(original: str, package_path: str, workspace: Path) -> str:
    start_count = original.count(_CONFIG_START)
    end_count = original.count(_CONFIG_END)
    if start_count != end_count or start_count > 1:
        raise ValueError(".codex/config.toml contains an invalid Arena managed block")

    base = original
    if start_count:
        start = original.index(_CONFIG_START)
        end_marker = original.index(_CONFIG_END, start)
        end = end_marker + len(_CONFIG_END)
        block = original[start:end]
        expected_block = (
            f"{_CONFIG_START}\n[[skills.config]]\npath = \"{package_path}\"\n"
            f"enabled = true\n{_CONFIG_END}"
        )
        legacy_block = (
            f"{_CONFIG_START}\n[codex_arena.install]\npath = \"{package_path}\"\n"
            f"{_CONFIG_END}"
        )
        normalized_block = block.replace("\r\n", "\n")
        if normalized_block not in {expected_block, legacy_block}:
            raise ValueError("the Arena managed block was edited or is unrecognized; refusing to overwrite it")
        if original.startswith("\r\n", end):
            end += 2
        elif original.startswith("\n", end):
            end += 1
        base = original[:start] + original[end:]

    try:
        import tomllib

        parsed: dict[str, Any] = tomllib.loads(base)
    except Exception as exc:
        raise ValueError(f"existing .codex/config.toml is not valid TOML: {exc}") from exc

    skills_section = parsed.get("skills", {})
    if not isinstance(skills_section, dict):
        raise ValueError("existing skills config is not a TOML table")
    skill_entries = skills_section.get("config", [])
    if not isinstance(skill_entries, list):
        raise ValueError("skills.config must be an array of tables")
    wanted = _config_path_key(package_path, workspace)
    for entry in skill_entries:
        if not isinstance(entry, dict):
            raise ValueError("each skills.config entry must be a TOML table")
        configured_path = entry.get("path")
        if isinstance(configured_path, str) and _config_path_key(configured_path, workspace) == wanted:
            # A user-owned entry already enables or disables this skill. Preserve it exactly.
            return base

    managed = (
        f'{_CONFIG_START}\n'
        "[[skills.config]]\n"
        f'path = "{package_path}"\n'
        "enabled = true\n"
        f"{_CONFIG_END}\n"
    )
    separator = "" if not base or base.endswith("\n") else "\n"
    result = base + separator + managed
    try:
        tomllib.loads(result)
    except Exception as exc:
        raise ValueError(f"could not add Arena settings to .codex/config.toml: {exc}") from exc
    return result


def _remove_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _install_source(source: Path) -> Path:
    nested = source / ".agents" / "skills" / _PACKAGE_NAME
    has_project_package = (
        (source / "scripts").is_dir()
        or (source / "README.md").is_file()
        or (source / "requirements.txt").is_file()
    )
    if source.name.casefold() != _PACKAGE_NAME and nested.is_dir() and not has_project_package:
        return nested.resolve()
    return source.resolve()


def install_skill(
    source: str | Path,
    workspace: str | Path,
    *,
    bootstrap: bool = False,
    requirements: str | Path | None = None,
    download_only: bool = False,
) -> dict[str, Any]:
    """Install a package into ``workspace/.agents/skills/codex-arena``.

    Installation stages both the package and the local Codex setting before changing
    either destination. Existing TOML content is retained, and package updates roll
    back if the config replacement fails.
    """
    workspace_path = Path(workspace).expanduser().resolve(strict=False)
    source_input = Path(source).expanduser()
    if not source_input.exists() or not source_input.is_dir():
        raise ValueError(f"source must be an existing directory: {source_input}")
    source_path = _install_source(source_input)
    if not source_path.is_dir():
        raise ValueError(f"source package is not a directory: {source_path}")
    skill_instruction = source_path / "SKILL.md"
    if not skill_instruction.is_file() or skill_instruction.is_symlink():
        raise ValueError(f"source package must contain a regular SKILL.md file: {source_path}")

    try:
        workspace_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"could not create workspace {workspace_path}: {exc}") from exc

    skill_parent = workspace_path / ".agents" / "skills"
    destination = skill_parent / _PACKAGE_NAME
    config_directory = workspace_path / ".codex"
    config_path = config_directory / "config.toml"
    arena_state_directory = config_directory / "arena"
    rollback_store = arena_state_directory / _ROLLBACK_BACKUP_DIR
    rollback_state_path = arena_state_directory / _ROLLBACK_STATE_NAME
    _reject_symlink_components(skill_parent, workspace_path)
    _reject_symlink_components(destination, workspace_path)
    _reject_symlink_components(config_path, workspace_path)
    _reject_symlink_components(arena_state_directory, workspace_path)
    _reject_symlink_components(rollback_store, workspace_path)

    source_resolved = source_path.resolve()
    destination_resolved = destination.resolve(strict=False)
    same_source_and_destination = _norm(source_resolved) == _norm(destination_resolved)
    source_is_workspace = _norm(source_resolved) == _norm(workspace_path)
    if same_source_and_destination or (
        _is_within(destination_resolved, source_resolved) and not source_is_workspace
    ):
        raise ValueError("source and destination overlap; refusing to copy a package into itself")
    if not _is_within(destination_resolved, workspace_path):
        raise ValueError(f"destination escapes workspace: {destination}")

    config_original = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    config_rendered = _render_config(
        config_original, ".agents/skills/codex-arena", workspace_path
    )
    _assert_no_local_edits(destination)

    skill_parent.mkdir(parents=True, exist_ok=True)
    config_directory.mkdir(parents=True, exist_ok=True)
    transaction_id = uuid.uuid4().hex
    stage = skill_parent / f".{_PACKAGE_NAME}.stage-{transaction_id}"
    backup = skill_parent / f".{_PACKAGE_NAME}.backup-{transaction_id}"
    config_stage = config_directory / f".config.toml.stage-{transaction_id}"
    config_backup = config_directory / f".config.toml.backup-{transaction_id}"
    rollback_stage = rollback_store / f".stage-{transaction_id}"
    rollback_final = rollback_store / transaction_id
    rollback_committed = False

    try:
        files, excluded = _copy_package(source_path, stage)
        manifest = {
            "schema_version": 1,
            "files": files,
            "inventory_sha256": _inventory_hash(files),
        }
        (stage / _MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        config_stage.write_text(config_rendered, encoding="utf-8", newline="\n")

        source_changed = _tree_inventory(destination) != files
        config_changed = not config_path.exists() or config_path.read_text(encoding="utf-8") != config_rendered
        if not source_changed and not config_changed:
            _remove_path(stage)
            _remove_path(config_stage)
            if bootstrap:
                bootstrap_result = bootstrap_local(
                    workspace_path,
                    requirements,
                    download_only=download_only,
                )
            else:
                bootstrap_result = None
            return {
                "changed": False,
                "installed_path": str(destination),
                "config_path": str(config_path),
                "files_count": len(files),
                "inventory_sha256": manifest["inventory_sha256"],
                "excluded": excluded,
                "bootstrap": bootstrap_result,
            }

        rollback_store.mkdir(parents=True, exist_ok=True)
        rollback_stage.mkdir(parents=True)
        previous_package_exists = destination.exists()
        previous_config_exists = config_path.exists()
        previous_package_inventory: dict[str, str] | None = None
        previous_package_inventory_sha256: str | None = None
        if previous_package_exists:
            previous_package_inventory = _tree_inventory(destination)
            previous_package_inventory_sha256 = _inventory_hash(previous_package_inventory)
            shutil.copytree(destination, rollback_stage / "package", copy_function=shutil.copy2)
        if previous_config_exists:
            shutil.copy2(config_path, rollback_stage / "config.toml")

        destination_backed_up = False
        destination_installed = False
        config_backed_up = False
        config_installed = False
        try:
            if source_changed and destination.exists():
                os.replace(destination, backup)
                destination_backed_up = True
            if source_changed:
                os.replace(stage, destination)
                destination_installed = True
            if config_changed and config_path.exists():
                os.replace(config_path, config_backup)
                config_backed_up = True
            if config_changed:
                os.replace(config_stage, config_path)
                config_installed = True
            marker = {
                "schema_version": 1,
                "backup_id": transaction_id,
                "previous_package_exists": previous_package_exists,
                "previous_package_inventory": previous_package_inventory,
                "previous_package_inventory_sha256": previous_package_inventory_sha256,
                "previous_config_exists": previous_config_exists,
                "previous_config_sha256": _file_hash(config_path) if previous_config_exists else None,
                "installed_inventory_sha256": manifest["inventory_sha256"],
                "installed_config_sha256": _text_hash(config_rendered),
            }
            _write_json_atomic(rollback_stage / _ROLLBACK_MARKER_NAME, marker)
            os.replace(rollback_stage, rollback_final)
            _write_json_atomic(
                rollback_state_path,
                {
                    "schema_version": 1,
                    "available": True,
                    "backup_id": transaction_id,
                    "installed_inventory_sha256": manifest["inventory_sha256"],
                    "installed_config_sha256": _text_hash(config_rendered),
                },
            )
            rollback_committed = True
        except Exception as exc:
            if config_installed:
                _remove_path(config_path)
            if config_backed_up and config_backup.exists():
                os.replace(config_backup, config_path)
            if destination_installed:
                _remove_path(destination)
            if destination_backed_up and backup.exists():
                os.replace(backup, destination)
            _remove_path(rollback_stage)
            _remove_path(rollback_final)
            raise RuntimeError(f"Arena installation failed and was rolled back: {exc}") from exc

        try:
            _remove_path(backup)
            _remove_path(config_backup)
        except OSError:
            # The verified copy in rollback_store is authoritative; stale transaction
            # backups are safe to clean up on a later install.
            pass
        _remove_path(stage)
        _remove_path(config_stage)
        if bootstrap:
            bootstrap_result = bootstrap_local(
                workspace_path,
                requirements,
                download_only=download_only,
            )
        else:
            bootstrap_result = None
        return {
            "changed": True,
            "installed_path": str(destination),
            "config_path": str(config_path),
            "files_count": len(files),
            "inventory_sha256": manifest["inventory_sha256"],
            "excluded": excluded,
            "bootstrap": bootstrap_result,
        }
    except (ValueError, RuntimeError):
        _remove_path(stage)
        _remove_path(config_stage)
        _remove_path(rollback_stage)
        if not rollback_committed:
            _remove_path(rollback_final)
        raise
    except OSError as exc:
        _remove_path(stage)
        _remove_path(config_stage)
        _remove_path(rollback_stage)
        if not rollback_committed:
            _remove_path(rollback_final)
        raise RuntimeError(f"could not stage Arena installation: {exc}") from exc


def rollback_install(workspace: str | Path) -> dict[str, Any]:
    """Restore the last installer-verified package and config snapshot.

    The current install must still match its recorded inventory, and the snapshot
    must still match its own hashes. This prevents rollback from discarding edits
    made after the update. Only the Arena package and project config are replaced.
    """
    workspace_path = Path(workspace).expanduser().resolve(strict=False)
    if not workspace_path.is_dir():
        raise ValueError(f"workspace must be an existing directory: {workspace_path}")

    skill_parent = workspace_path / ".agents" / "skills"
    destination = skill_parent / _PACKAGE_NAME
    config_directory = workspace_path / ".codex"
    config_path = config_directory / "config.toml"
    arena_state_directory = config_directory / "arena"
    state_path = arena_state_directory / _ROLLBACK_STATE_NAME
    rollback_store = arena_state_directory / _ROLLBACK_BACKUP_DIR
    for path in (skill_parent, destination, config_path, arena_state_directory, rollback_store, state_path):
        _reject_symlink_components(path, workspace_path)
    if not state_path.is_file():
        return {"changed": False, "reason": "no rollback snapshot is available"}

    state = _read_json(state_path, "installer rollback state")
    if state.get("schema_version") != 1:
        raise ValueError("installer rollback state has an unsupported schema")
    if state.get("available") is not True:
        return {"changed": False, "reason": "the last rollback snapshot was already used"}
    backup_id = state.get("backup_id")
    if not isinstance(backup_id, str) or not re.fullmatch(r"[0-9a-f]{32}", backup_id):
        raise ValueError("installer rollback state contains an invalid backup id")

    backup_directory = rollback_store / backup_id
    _reject_symlink_components(backup_directory, workspace_path)
    marker = _read_json(backup_directory / _ROLLBACK_MARKER_NAME, "installer rollback inventory")
    if marker.get("schema_version") != 1 or marker.get("backup_id") != backup_id:
        raise ValueError("installer rollback inventory does not match its state pointer")
    if (
        marker.get("installed_inventory_sha256") != state.get("installed_inventory_sha256")
        or marker.get("installed_config_sha256") != state.get("installed_config_sha256")
    ):
        raise ValueError("installer rollback hashes do not match the state pointer")

    _assert_no_local_edits(destination)
    if not destination.is_dir():
        raise ValueError("the installed Arena package is missing; refusing to guess what to restore")
    installed_manifest = _read_json(destination / _MANIFEST_NAME, "installed Arena inventory")
    installed_files = installed_manifest.get("files")
    if (
        not isinstance(installed_files, dict)
        or _tree_inventory(destination) != installed_files
        or _inventory_hash(installed_files) != state.get("installed_inventory_sha256")
    ):
        raise ValueError("local edits conflict with rollback; preserve or review those changes first")
    if not config_path.is_file() or _file_hash(config_path) != state.get("installed_config_sha256"):
        raise ValueError("project config changed after installation; refusing to overwrite user edits")

    previous_package_exists = marker.get("previous_package_exists") is True
    previous_config_exists = marker.get("previous_config_exists") is True
    backup_package = backup_directory / "package"
    backup_config = backup_directory / "config.toml"
    old_files: dict[str, str] | None = None
    if previous_package_exists:
        _assert_no_local_edits(backup_package)
        old_manifest = _read_json(backup_package / _MANIFEST_NAME, "saved Arena inventory")
        old_files_value = old_manifest.get("files")
        if not isinstance(old_files_value, dict):
            raise ValueError("saved Arena inventory is malformed")
        old_files = old_files_value
        old_inventory_hash = _inventory_hash(old_files)
        if (
            _tree_inventory(backup_package) != old_files
            or old_inventory_hash != marker.get("previous_package_inventory_sha256")
            or old_files != marker.get("previous_package_inventory")
        ):
            raise ValueError("saved Arena package backup failed its inventory check")
    elif backup_package.exists():
        raise ValueError("unexpected package data exists in the rollback snapshot")
    if previous_config_exists:
        if not backup_config.is_file() or _file_hash(backup_config) != marker.get("previous_config_sha256"):
            raise ValueError("saved project config failed its hash check")
    elif backup_config.exists():
        raise ValueError("unexpected config data exists in the rollback snapshot")

    _reject_symlink_components(skill_parent, workspace_path)
    _reject_symlink_components(config_directory, workspace_path)
    skill_parent.mkdir(parents=True, exist_ok=True)
    config_directory.mkdir(parents=True, exist_ok=True)
    transaction_id = uuid.uuid4().hex
    package_stage = skill_parent / f".{_PACKAGE_NAME}.rollback-stage-{transaction_id}"
    package_current = skill_parent / f".{_PACKAGE_NAME}.rollback-current-{transaction_id}"
    config_stage = config_directory / f".config.toml.rollback-stage-{transaction_id}"
    config_current = config_directory / f".config.toml.rollback-current-{transaction_id}"
    if previous_package_exists:
        shutil.copytree(backup_package, package_stage, copy_function=shutil.copy2)
    if previous_config_exists:
        shutil.copy2(backup_config, config_stage)

    package_backed_up = False
    package_restored = False
    config_backed_up = False
    config_restored = False
    try:
        os.replace(destination, package_current)
        package_backed_up = True
        if previous_package_exists:
            os.replace(package_stage, destination)
            package_restored = True
        os.replace(config_path, config_current)
        config_backed_up = True
        if previous_config_exists:
            os.replace(config_stage, config_path)
            config_restored = True
        _write_json_atomic(
            state_path,
            {
                "schema_version": 1,
                "available": False,
                "backup_id": backup_id,
                "installed_inventory_sha256": state["installed_inventory_sha256"],
                "installed_config_sha256": state["installed_config_sha256"],
            },
        )
    except Exception as exc:
        if config_restored:
            _remove_path(config_path)
        if config_backed_up and config_current.exists():
            os.replace(config_current, config_path)
        if package_restored:
            _remove_path(destination)
        if package_backed_up and package_current.exists():
            os.replace(package_current, destination)
        _remove_path(package_stage)
        _remove_path(config_stage)
        raise RuntimeError(f"Arena rollback failed and was rolled back: {exc}") from exc

    try:
        _remove_path(package_current)
        _remove_path(config_current)
        _remove_path(package_stage)
        _remove_path(config_stage)
    except OSError:
        pass
    return {
        "changed": True,
        "workspace": str(workspace_path),
        "installed_path": str(destination) if previous_package_exists else None,
        "config_path": str(config_path) if previous_config_exists else None,
        "restored_previous_package": previous_package_exists,
        "restored_previous_config": previous_config_exists,
        "backup_id": backup_id,
    }


def _validate_pinned_requirements(
    requirements_path: Path, *, description: str = "requirements"
) -> list[str]:
    if not requirements_path.is_file():
        raise ValueError(f"{description} file does not exist: {requirements_path}")
    requirements: list[str] = []
    for line_number, raw_line in enumerate(
        requirements_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if not _PINNED_REQUIREMENT.fullmatch(line):
            raise ValueError(
                f"{description} must pin every package with == (line {line_number}): {line}"
            )
        requirements.append(line)
    if not requirements:
        raise ValueError(f"{description} file contains no pinned packages")
    return requirements


def bootstrap_local(
    workspace: str | Path,
    requirements: str | Path | None,
    *,
    download_only: bool = False,
    cache_dir: str | Path | None = None,
    python: str | Path | None = None,
) -> dict[str, Any]:
    """Create or use a workspace-local venv and install or cache pinned packages.

    This function has no automatic caller. Invoking it is the explicit opt-in for
    package downloads or installation.
    """
    workspace_path = Path(workspace).expanduser().resolve(strict=False)
    if not workspace_path.is_dir():
        raise ValueError(f"workspace must be an existing directory: {workspace_path}")
    if requirements is None:
        raise ValueError("a pinned requirements file is required for local bootstrap")
    requirements_path = Path(requirements).expanduser()
    if not requirements_path.is_absolute():
        requirements_path = workspace_path / requirements_path
    requirements_path = requirements_path.resolve(strict=False)
    pinned = _validate_pinned_requirements(requirements_path)
    constraints_path = requirements_path.with_name("constraints.txt")
    constraint_args: list[str] = []
    if constraints_path.exists():
        _validate_pinned_requirements(constraints_path, description="constraints")
        constraint_args = ["--constraint", str(constraints_path)]

    environment = workspace_path / ".venv"
    if download_only:
        cache = (
            Path(cache_dir).expanduser()
            if cache_dir is not None
            else workspace_path / ".codex" / "arena" / "wheels"
        )
        if not cache.is_absolute():
            cache = workspace_path / cache
        cache = cache.resolve(strict=False)
        if not _is_within(cache, workspace_path):
            raise ValueError("requirements cache must be inside the workspace")
        cache.mkdir(parents=True, exist_ok=True)
        if python is None:
            download_python = Path(sys.executable)
        else:
            requested = str(python)
            found = shutil.which(requested)
            download_python = Path(found or requested).expanduser()
            if not download_python.exists():
                raise ValueError(f"requested Python executable does not exist: {python}")
        command = [
            str(download_python), "-m", "pip", "download", *constraint_args,
            "--requirement", str(requirements_path), "--dest", str(cache)
        ]
        action = "downloaded"
        result_path = cache
    else:
        if environment.is_symlink() or (
            hasattr(environment, "is_junction") and environment.is_junction()
        ):
            raise ValueError(f"refusing to use a linked environment: {environment}")
        if python is not None and environment.exists():
            raise ValueError(
                f"local environment already exists at {environment}; refusing to replace it with another Python"
            )
        if not environment.exists():
            if python is None:
                venv.EnvBuilder(with_pip=True).create(environment)
            else:
                requested = str(python)
                found = shutil.which(requested)
                selected_python = Path(found or requested).expanduser()
                if not selected_python.exists():
                    raise ValueError(f"requested Python executable does not exist: {python}")
                try:
                    subprocess.run(
                        [str(selected_python), "-m", "venv", str(environment)],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                except (OSError, subprocess.CalledProcessError) as exc:
                    raise RuntimeError(f"could not create workspace-local environment: {exc}") from exc
        environment_python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not environment_python.exists():
            raise RuntimeError(f"local virtual environment is missing its Python executable: {environment}")
        command = [
            str(environment_python), "-m", "pip", "install", *constraint_args,
            "--requirement", str(requirements_path)
        ]
        action = "installed"
        result_path = environment
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"local dependency {action} failed: {exc}") from exc
    return {
        "action": action,
        "environment": str(environment) if environment.exists() else None,
        "path": str(result_path),
        "requirements": pinned,
        "command": command,
        "output": completed.stdout.strip(),
    }


__all__ = ["bootstrap_local", "install_skill", "rollback_install"]
