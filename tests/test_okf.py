import pytest
from scripts.arena_okf import validate_okf


def test_reserved_index_and_ordinary_underscore_index(tmp_path):
    (tmp_path / "index.md").write_text('---\nokf_version: "0.2"\n---\n# Contents\n')
    (tmp_path / "_index.md").write_text('---\ntype: Playbook\nunknown: preserved\n---\n# Agents\n')
    assert validate_okf(tmp_path)["concepts"] == 1
    (tmp_path / "_index.md").write_text('# Agents\n')
    with pytest.raises(ValueError, match="type"):
        validate_okf(tmp_path)


def test_okf_version_allowed_only_root_index(tmp_path):
    (tmp_path / "README.md").write_text('---\ntype: Playbook\nokf_version: "0.2"\n---\n')
    with pytest.raises(ValueError, match="okf_version"):
        validate_okf(tmp_path)
