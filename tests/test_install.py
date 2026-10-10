from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import arena_install
from scripts.arena_install import bootstrap_local, install_skill, rollback_install


def make_source(root: Path) -> Path:
    (root / "scripts").mkdir(parents=True)
    (root / "references").mkdir()
    (root / "scripts" / "arena.py").write_text("print('arena')\n", encoding="utf-8")
    (root / "references" / "contract.md").write_text("portable skill\n", encoding="utf-8")
    (root / "README.md").write_text("Codex Arena\n", encoding="utf-8")
    (root / "SKILL.md").write_text("---\nname: codex-arena\n---\nArena skill.\n", encoding="utf-8")
    for directory in (
        ".git",
        ".venv",
        "scratch",
        "holdout",
        ".memory",
        "memory",
        "auth",
        "credentials",
        "secrets",
        ".ssh",
        ".aws",
        "build",
        "dist",
        "codex_arena.egg-info",
    ):
        excluded = root / directory
        excluded.mkdir()
        (excluded / "secret.md").write_text("do not copy", encoding="utf-8")
    (root / ".env").write_text("TOKEN=secret", encoding="utf-8")
    (root / "credentials.json").write_text('{"token":"secret"}', encoding="utf-8")
    return root


def test_install_is_idempotent_preserves_foreign_config_and_excludes_private_state(
    tmp_path: Path,
) -> None:
    source = make_source(tmp_path / "源 project")
    workspace = tmp_path / "work space"
    workspace.mkdir()
    codex_dir = workspace / ".codex"
    codex_dir.mkdir()
    original_config = '# keep this comment\n[foreign]\nvalue = "untouched"\n'
    (codex_dir / "config.toml").write_text(original_config, encoding="utf-8")

    first = install_skill(source, workspace)
    package = workspace / ".agents" / "skills" / "codex-arena"
    installed_config = (codex_dir / "config.toml").read_text(encoding="utf-8")
    parsed = tomllib.loads(installed_config)

    assert first["changed"] is True
    assert first["files_count"] == 4
    assert parsed["foreign"] == {"value": "untouched"}
    assert "# keep this comment" in installed_config
    assert parsed["skills"]["config"] == [
        {"path": ".agents/skills/codex-arena", "enabled": True}
    ]
    assert (package / "scripts" / "arena.py").exists()
    assert (package / "SKILL.md").is_file()
    assert not (package / ".env").exists()
    assert not (package / "credentials.json").exists()
    for directory in (
        ".git",
        ".venv",
        "scratch",
        "holdout",
        ".memory",
        "memory",
        "auth",
        "credentials",
        "secrets",
        ".ssh",
        ".aws",
        "build",
        "dist",
        "codex_arena.egg-info",
    ):
        assert not (package / directory).exists()
    inventory = json.loads((package / ".arena-install.json").read_text(encoding="utf-8"))
    assert inventory["files"]["README.md"]
    assert inventory["files"]["SKILL.md"]
    assert inventory["files"]["scripts/arena.py"]

    second = install_skill(source, workspace)

    assert second["changed"] is False
    assert second["inventory_sha256"] == first["inventory_sha256"]
    assert (codex_dir / "config.toml").read_text(encoding="utf-8") == installed_config


def test_install_preserves_existing_skills_config_entry_without_duplicating_it(
    tmp_path: Path,
) -> None:
    source = make_source(tmp_path / "source")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    codex_dir = workspace / ".codex"
    codex_dir.mkdir()
    config_path = codex_dir / "config.toml"
    original_config = (
        '[[skills.config]]\npath = ".agents/skills/codex-arena"\n'
        "enabled = false\n"
    )
    config_path.write_text(original_config, encoding="utf-8")

    result = install_skill(source, workspace)

    assert result["changed"] is True
    assert config_path.read_text(encoding="utf-8") == original_config
    parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert parsed["skills"]["config"] == [
        {"path": ".agents/skills/codex-arena", "enabled": False}
    ]


def test_install_refuses_to_overwrite_edits_inside_its_managed_config_block(tmp_path: Path) -> None:
    source = make_source(tmp_path / "source")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install_skill(source, workspace)
    config_path = workspace / ".codex" / "config.toml"
    edited_config = config_path.read_text(encoding="utf-8").replace(
        "enabled = true", "enabled = false"
    )
    config_path.write_text(edited_config, encoding="utf-8")

    with pytest.raises(ValueError, match="managed.*edited|edited.*managed"):
        install_skill(source, workspace)

    assert config_path.read_text(encoding="utf-8") == edited_config


def test_install_rejects_source_equal_to_its_destination(tmp_path: Path) -> None:
    source = make_source(tmp_path / "source")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install_skill(source, workspace)

    with pytest.raises(ValueError, match="source|destination|itself"):
        install_skill(
            workspace / ".agents" / "skills" / "codex-arena",
            workspace,
        )


def test_reinstall_detects_local_edits_and_preserves_them(tmp_path: Path) -> None:
    source = make_source(tmp_path / "source")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install_skill(source, workspace)
    package = workspace / ".agents" / "skills" / "codex-arena"
    edited_file = package / "README.md"
    edited_file.write_text("user edit\n", encoding="utf-8")
    (source / "README.md").write_text("upstream update\n", encoding="utf-8")

    with pytest.raises(ValueError, match="edit|conflict|modified"):
        install_skill(source, workspace)

    assert edited_file.read_text(encoding="utf-8") == "user edit\n"
    assert not (package / ".arena-install.json.stage").exists()


def test_regular_install_does_not_create_a_local_environment(tmp_path: Path) -> None:
    source = make_source(tmp_path / "source")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    install_skill(source, workspace)

    assert not (workspace / ".venv").exists()


def test_install_from_workspace_root_does_not_copy_its_destination_or_corpus_data(
    tmp_path: Path,
) -> None:
    workspace = make_source(tmp_path / "workspace")
    (workspace / ".docs").mkdir()
    (workspace / ".docs" / "private.md").write_text("private corpus", encoding="utf-8")
    (workspace / ".playbooks").mkdir()
    (workspace / ".playbooks" / "workflow.md").write_text("workflow corpus", encoding="utf-8")

    first = install_skill(workspace, workspace)
    package = workspace / ".agents" / "skills" / "codex-arena"
    second = install_skill(workspace, workspace)

    assert first["changed"] is True
    assert second["changed"] is False
    assert (package / "scripts" / "arena.py").exists()
    assert not (package / ".agents").exists()
    assert not (package / ".docs").exists()
    assert not (package / ".playbooks").exists()
    assert not (package / "scratch").exists()


def test_install_copies_pinned_requirements_and_ignores_generated_python_cache(tmp_path: Path) -> None:
    source = make_source(tmp_path / "source")
    (source / "requirements.txt").write_text("fastembed==0.9.0\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    install_skill(source, workspace)
    package = workspace / ".agents" / "skills" / "codex-arena"
    bytecode = package / "scripts" / "__pycache__" / "arena.cpython-313.pyc"
    bytecode.parent.mkdir()
    bytecode.write_bytes(b"generated")
    result = install_skill(source, workspace)

    assert (package / "requirements.txt").read_text(encoding="utf-8") == "fastembed==0.9.0\n"
    assert result["changed"] is False


def test_install_rolls_back_package_and_config_when_config_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_source(tmp_path / "source")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install_skill(source, workspace)
    package = workspace / ".agents" / "skills" / "codex-arena"
    original_package = (package / "README.md").read_text(encoding="utf-8")
    config_path = workspace / ".codex" / "config.toml"
    config_path.write_text(config_path.read_text(encoding="utf-8") + "\n[foreign]\nkeep = true\n", encoding="utf-8")
    original_config = config_path.read_text(encoding="utf-8")
    (source / "README.md").write_text("updated source\n", encoding="utf-8")
    actual_replace = arena_install.os.replace

    def fail_config_stage(source_path: object, target_path: object) -> None:
        if ".config.toml.stage-" in str(source_path):
            raise PermissionError("simulated config replace failure")
        actual_replace(source_path, target_path)

    monkeypatch.setattr(arena_install.os, "replace", fail_config_stage)

    with pytest.raises(RuntimeError, match="rolled back"):
        install_skill(source, workspace)

    assert (package / "README.md").read_text(encoding="utf-8") == original_package
    assert config_path.read_text(encoding="utf-8") == original_config
    assert not list(package.parent.glob(".codex-arena.backup-*"))


def test_download_only_uses_pinned_requirements_without_creating_a_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    requirements = workspace / "requirements.txt"
    requirements.write_text("fastembed==0.9.0\n", encoding="utf-8")
    constraints = workspace / "constraints.txt"
    constraints.write_text("numpy==2.3.5\nsqlite-vec==0.1.9\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(stdout="cached")

    monkeypatch.setattr(arena_install.subprocess, "run", fake_run)
    result = bootstrap_local(workspace, requirements, download_only=True)

    assert result["action"] == "downloaded"
    assert result["environment"] is None
    assert calls[0][0] == sys.executable
    assert calls[0][3] == "download"
    assert "--constraint" in calls[0]
    assert calls[0][calls[0].index("--constraint") + 1] == str(constraints)
    assert calls[0][calls[0].index("--requirement") + 1] == str(requirements)
    assert not (workspace / ".venv").exists()


def test_rollback_restores_previous_package_and_config_without_touching_siblings(
    tmp_path: Path,
) -> None:
    source = make_source(tmp_path / "source")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_path = workspace / ".codex" / "config.toml"
    config_path.parent.mkdir(parents=True)
    original_config_bytes = '# user config\r\n[foreign]\r\nkeep = "yes"\r\n'.encode("utf-8")
    config_path.write_bytes(original_config_bytes)

    install_skill(source, workspace)
    package = workspace / ".agents" / "skills" / "codex-arena"
    previous_readme = (package / "README.md").read_text(encoding="utf-8")
    previous_config = config_path.read_bytes()
    sibling_package = workspace / ".agents" / "skills" / "other-skill"
    sibling_package.mkdir()
    sibling_file = sibling_package / "keep.txt"
    sibling_file.write_text("sibling stays", encoding="utf-8")
    (source / "README.md").write_text("new Arena release\n", encoding="utf-8")
    install_skill(source, workspace)

    result = rollback_install(workspace)

    assert result["changed"] is True
    assert (package / "README.md").read_text(encoding="utf-8") == previous_readme
    assert config_path.read_bytes() == previous_config
    assert sibling_file.read_text(encoding="utf-8") == "sibling stays"
    assert rollback_install(workspace)["changed"] is False


def test_rollback_of_first_install_removes_only_generated_files(tmp_path: Path) -> None:
    source = make_source(tmp_path / "source")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    unrelated = workspace / ".agents" / "skills" / "other-skill" / "keep.txt"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("keep", encoding="utf-8")
    install_skill(source, workspace)

    result = rollback_install(workspace)

    assert result["changed"] is True
    assert not (workspace / ".agents" / "skills" / "codex-arena").exists()
    assert not (workspace / ".codex" / "config.toml").exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_rollback_refuses_to_overwrite_user_edits_to_current_install(tmp_path: Path) -> None:
    source = make_source(tmp_path / "source")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install_skill(source, workspace)
    (source / "README.md").write_text("second release\n", encoding="utf-8")
    install_skill(source, workspace)
    edited_file = workspace / ".agents" / "skills" / "codex-arena" / "README.md"
    edited_file.write_text("local user edit\n", encoding="utf-8")

    with pytest.raises(ValueError, match="local edits|modified|conflict"):
        rollback_install(workspace)

    assert edited_file.read_text(encoding="utf-8") == "local user edit\n"


def test_rollback_refuses_to_overwrite_user_edits_to_current_config(tmp_path: Path) -> None:
    source = make_source(tmp_path / "source")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install_skill(source, workspace)
    (source / "README.md").write_text("second release\n", encoding="utf-8")
    install_skill(source, workspace)
    config_path = workspace / ".codex" / "config.toml"
    edited_config = config_path.read_text(encoding="utf-8") + "\n[local]\nkeep = true\n"
    config_path.write_text(edited_config, encoding="utf-8")

    with pytest.raises(ValueError, match="config changed|user edits"):
        rollback_install(workspace)

    assert config_path.read_text(encoding="utf-8") == edited_config
