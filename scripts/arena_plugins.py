"""Declarative plugin composition with mandatory bound semantic review."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .arena_okf import frontmatter
from . import arena_signing as signing

FIELDS = ("requires", "capabilities", "effects", "invariants", "incompatible")


def parse_plugin(path: Path) -> dict:
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Plugin must not be a symlink")
    metadata, body = frontmatter(path.read_text(encoding="utf-8"))
    name = metadata.get("name")
    if metadata.get("type") != "Playbook" or not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
        raise ValueError("Plugin requires Playbook type and portable name")
    for field in FIELDS:
        if not isinstance(metadata.get(field), list) or any(not isinstance(item, str) or not item.strip() for item in metadata[field]):
            raise ValueError(f"Plugin requires structured {field} list")
    if not metadata["capabilities"] or not metadata["effects"] or not metadata["invariants"] or not re.search(r"^#+\s+(?:High.level\s+)?Pseudocode\b", body, flags=re.I | re.M) or len(body.strip()) < 30:
        raise ValueError("Plugin needs capabilities/effects/invariants and high-level pseudocode")
    return {**metadata, "body": body, "sha256": signing.digest({"metadata": metadata, "body": body})}


def review_context(workspace: Path, bundle: Path, enabled: list[str]) -> dict:
    """Prepare semantic review only for a tier with real approved validation."""
    from . import arena_playbooks as playbooks
    manifest = playbooks.validate_playbook(workspace, bundle)
    runtime = playbooks.get_runtime(workspace, bundle, check_plugins=False)
    return _context(bundle, enabled, manifest, runtime)


def structural_context(workspace: Path, bundle: Path, enabled: list[str]) -> dict:
    """Inspect signed candidate structure without granting activation approval."""
    from . import arena_playbooks as playbooks
    manifest = playbooks.validate_playbook(workspace, bundle)
    runtime = playbooks.inspect_runtime(workspace, bundle)
    return _context(bundle, enabled, manifest, runtime)


def _context(bundle: Path, enabled: list[str], manifest: dict, runtime: dict) -> dict:
    if not isinstance(enabled, list) or len(set(enabled)) != len(enabled) or any(not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name) for name in enabled):
        raise ValueError("Invalid plugin names")
    selected = {}
    for name in sorted(enabled):
        path = Path(bundle) / "plugins" / name / "main.md"
        if not path.is_file():
            raise ValueError("Unknown plugin: " + name)
        plugin = parse_plugin(path)
        if plugin["name"] != name:
            raise ValueError("Plugin name/path mismatch")
        selected[name] = plugin
    for name, plugin in selected.items():
        if set(plugin["incompatible"]) & set(selected):
            raise ValueError("Declared plugin conflict: " + name)
        if set(plugin["requires"]) - set(selected):
            raise ValueError("Missing required plugin: " + name)
    tier_root = Path(bundle) / "tier" / runtime["selected_tier"]
    base = {path.relative_to(bundle).as_posix(): path.read_text(encoding="utf-8") for path in tier_root.rglob("*") if path.is_file() and path.suffix in {".py", ".md"}}
    return {"schema_version": 1, "base_hash": runtime["candidate_hash"], "base_rules": manifest["rules"], "base_strategy": base,
            "plugins": selected, "enabled": sorted(enabled), "model_hash": signing.digest({"model": runtime["model"], "effort": runtime["effort"]}),
            "instruction": "Review the actual base strategy and combined plugin pseudocode. Decide compatible, conflict, or unknown for requirements, capabilities, effects and invariants. Unknown/conflict deny activation; explain the result."}


def set_plugins(workspace: Path, bundle: Path, enabled: list[str], reviewer=None, review_receipt: dict | None = None) -> dict:
    """Set exact enabled set. Callback performs semantic review explicitly.

    A cached or supplied plugin-review envelope must contain context_hash plus
    review {decision,explanation}. Cache keys bind whole combination and model.
    Disabling modules rechecks the remaining combination (empty set is safe).
    """
    from . import arena_playbooks as playbooks
    context = review_context(workspace, bundle, enabled)
    runtime = playbooks.get_runtime(workspace, bundle, check_plugins=False)
    bound = signing.digest(context)
    cache = signing._storage(workspace) / "plugin-reviews" / (bound + ".json")
    if enabled:
        if review_receipt is not None:
            receipt = review_receipt
        elif cache.exists():
            receipt = json.loads(cache.read_text(encoding="utf-8"))
        elif callable(reviewer):
            review = reviewer(context)
            if not isinstance(review, dict) or set(review) != {"decision", "explanation"}:
                raise ValueError("Semantic reviewer must return decision/explanation")
            receipt = signing.sign_payload(workspace, {"context_hash": bound, "review": review}, "plugin-review")
        else:
            raise ValueError("Semantic review callback or bound signed review required")
        payload = signing.verify_payload(workspace, receipt, "plugin-review")
        if payload.get("context_hash") != bound:
            raise ValueError("Semantic review is stale for base/plugins/model")
        review = payload.get("review")
        if not isinstance(review, dict) or not isinstance(review.get("explanation"), str) or not review["explanation"].strip() or review.get("decision") not in {"compatible", "conflict", "unknown"}:
            raise ValueError("Invalid semantic review")
        if review["decision"] != "compatible":
            raise ValueError("Semantic review denied: " + review["decision"] + ": " + review["explanation"])
        signing.write_json(cache, receipt)
    runtime["enabled_plugins"] = sorted(enabled)
    playbooks.write_runtime(workspace, bundle, runtime)
    return runtime


def validate_enabled_plugins(workspace: Path, bundle: Path, enabled: list[str]) -> None:
    """Runtime edits never bypass combination/model-bound review receipts."""
    context = review_context(workspace, bundle, enabled)
    if not enabled:
        return
    bound = signing.digest(context)
    cache = signing._storage(workspace) / "plugin-reviews" / (bound + ".json")
    if not cache.is_file() or cache.is_symlink():
        raise ValueError("Runtime plugins require a matching signed semantic review")
    payload = signing.verify_payload(workspace, json.loads(cache.read_text(encoding="utf-8")), "plugin-review")
    if payload.get("context_hash") != bound or payload.get("review", {}).get("decision") != "compatible":
        raise ValueError("Runtime plugin semantic review mismatch")
