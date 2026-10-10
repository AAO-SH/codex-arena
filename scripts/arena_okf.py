"""Strict producer checks for OKF v0.2; unknown concept keys are preserved.

Contract: GoogleCloudPlatform/open-knowledge-format/SPEC.md, v0.2,
pinned at ad30107c31c06aec8a7d5636e0d1058118604e6f.
This validates structure, never the factual truth of a concept.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path
import yaml


class _UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError("Duplicate YAML frontmatter key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def frontmatter(text: str) -> tuple[dict, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if end is None:
        raise ValueError("Unclosed YAML frontmatter")
    try:
        metadata = yaml.load("".join(lines[1:end]), Loader=_UniqueLoader)
    except yaml.YAMLError as exc:
        raise ValueError("Malformed YAML frontmatter") from exc
    if not isinstance(metadata, dict):
        raise ValueError("Frontmatter must be a mapping")
    return metadata, "".join(lines[end + 1:])


def _instant(value, label):
    try:
        instant = value if isinstance(value, datetime.datetime) else datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00").replace(" ", ""))
        if instant.tzinfo is None:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError(f"{label} requires an ISO datetime with offset") from None


def validate_okf(root: Path) -> dict:
    root = Path(root).resolve()
    concepts = 0
    for path in sorted(root.rglob("*.md")):
        if path.is_symlink():
            raise ValueError("OKF symlink unsupported")
        metadata, body = frontmatter(path.read_text(encoding="utf-8"))
        relative = path.relative_to(root)
        if path.name == "index.md":
            if relative == Path("index.md"):
                if set(metadata) - {"okf_version"} or (metadata and metadata.get("okf_version") != "0.2"):
                    raise ValueError("Root index permits only okf_version 0.2")
            elif metadata:
                raise ValueError("Nested index must not have frontmatter")
            continue
        if "okf_version" in metadata:
            raise ValueError("okf_version belongs only in root index.md")
        if path.name == "log.md":
            if metadata:
                raise ValueError("Reserved log must not have frontmatter")
            for heading in re.findall(r"^##\s+(.+)$", body, flags=re.M):
                try:
                    datetime.date.fromisoformat(heading)
                except ValueError:
                    raise ValueError("Log headings require YYYY-MM-DD") from None
            continue
        if not isinstance(metadata.get("type"), str) or not metadata["type"].strip():
            raise ValueError(f"{relative}: concept requires nonempty type")
        concepts += 1
        if "sources" in metadata:
            if not isinstance(metadata["sources"], list) or any(not isinstance(source, dict) or not isinstance(source.get("resource"), str) or not source["resource"].strip() for source in metadata["sources"]):
                raise ValueError("Every source requires resource")
        if "generated" in metadata:
            generated = metadata["generated"]
            if not isinstance(generated, dict) or not generated.get("by"):
                raise ValueError("generated requires by")
            if "at" in generated:
                _instant(generated["at"], "generated.at")
        if "verified" in metadata:
            verified = metadata["verified"]
            if isinstance(verified, dict):
                verified = [verified]
            if not isinstance(verified, list):
                raise ValueError("verified requires mapping/list")
            for entry in verified:
                if not isinstance(entry, dict) or not entry.get("by") or "at" not in entry:
                    raise ValueError("Verification event requires by and at")
                _instant(entry["at"], "verified.at")
        if "status" in metadata and metadata["status"] not in {"draft", "stable", "deprecated"}:
            raise ValueError("Invalid OKF status")
        if "stale_after" in metadata:
            _instant(metadata["stale_after"], "stale_after")
        if metadata["type"] == "Attested Computation" and not metadata.get("runtime"):
            raise ValueError("Attested Computation requires runtime")
    return {"okf_version": "0.2", "concepts": concepts}
