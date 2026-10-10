"""Signed executable strategy bundles and paired holdout promotion gates.

Generation is injected: build_playbook accepts teacher-produced artifacts, never
copies a winning answer and never invokes an inference provider implicitly.
Local signatures attest pipeline origin, not the truth of a human-written claim.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import statistics
from pathlib import Path, PurePosixPath

from . import arena_signing as signing
from .arena_okf import frontmatter, validate_okf

TIERS = ("iron", "copper", "silver", "gold")
EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
DEFAULT_RULES = {"min_holdout": 5, "repetitions": 3, "quality_gain": 5, "resource_gain": 0.10}


def _path(relative: str) -> PurePosixPath:
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise ValueError("Artifact paths must be portable relative paths")
    path = PurePosixPath(relative)
    if path.is_absolute() or any(part in {"..", ".", ""} for part in relative.split("/")):
        raise ValueError("Artifact path escapes bundle")
    if any(part.casefold().split(".")[0] in {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))} for part in path.parts):
        raise ValueError("Reserved artifact path")
    return path


def _bundle(workspace: Path, bundle: Path) -> Path:
    workspace = Path(workspace).resolve()
    bundle = Path(bundle).absolute()
    try:
        bundle.relative_to(workspace / ".playbooks")
    except ValueError:
        raise ValueError("Bundle must reside in workspace .playbooks") from None
    current = bundle
    while current != workspace:
        if current.is_symlink():
            raise ValueError("Bundle symlink escape")
        current = current.parent
    if not bundle.is_dir():
        raise ValueError("Bundle does not exist")
    return bundle


def _files(bundle: Path) -> dict:
    result = {}
    for path in sorted(bundle.rglob("*")):
        if path.is_symlink():
            raise ValueError("Bundle contains symlink")
        if path.is_file() and path.relative_to(bundle).as_posix() != "playbook.json":
            result[path.relative_to(bundle).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _script_check(text: str, path: str) -> None:
    try:
        tree = ast.parse(text, filename=path)
        compile(tree, path, "exec")
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"Invalid Python artifact {path}: {exc}") from exc
    if any(isinstance(node, (ast.Pass,)) or isinstance(node, ast.Constant) and node.value is Ellipsis or isinstance(node, ast.Name) and node.id == "NotImplementedError" for node in ast.walk(tree)):
        raise ValueError(f"Stub strategy rejected: {path}")
    functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    substantive = any(any(isinstance(node, (ast.Call, ast.For, ast.While, ast.If, ast.ListComp, ast.DictComp, ast.BinOp)) for node in ast.walk(fn)) for fn in functions)
    if not substantive:
        raise ValueError(f"Strategy needs functional automation: {path}")


def _structure(bundle: Path) -> None:
    if not (bundle / "README.md").is_file():
        raise ValueError("Playbook requires README.md")
    metadata, _ = frontmatter((bundle / "README.md").read_text(encoding="utf-8"))
    if metadata.get("type") != "Playbook":
        raise ValueError("README requires type: Playbook")
    for tier in TIERS:
        base = bundle / "tier" / tier
        scripts = list((base / "scripts").rglob("*.py"))
        agents = list((base / ".agents").glob("*.md"))
        if not scripts or not (base / ".agents" / "_index.md").is_file() or len(agents) < 2:
            raise ValueError(f"Tier {tier} requires executable scripts, .agents/_index.md and strategy concepts")
        for script in scripts:
            _script_check(script.read_text(encoding="utf-8"), script.relative_to(bundle).as_posix())
        for agent in agents:
            metadata, body = frontmatter(agent.read_text(encoding="utf-8"))
            if metadata.get("type") != "Playbook" or len(body.strip()) < 30:
                raise ValueError("Agent strategy requires Playbook metadata and explanation")
    for main in (bundle / "plugins").glob("*/main.md"):
        from .arena_plugins import parse_plugin
        parse_plugin(main)
    validate_okf(bundle)


def _available_plugins(bundle: Path, files: dict) -> list:
    from .arena_plugins import parse_plugin
    inventory = []
    for path in sorted((bundle / 'plugins').glob('*/main.md')):
        plugin = parse_plugin(path)
        if plugin['name'] != path.parent.name:
            raise ValueError('Plugin name/path mismatch')
        relative = path.relative_to(bundle).as_posix()
        inventory.append({'name': plugin['name'], 'main_path': relative, 'sha256': files[relative]})
    return inventory


def _rules(rules: dict | None) -> dict:
    value = dict(DEFAULT_RULES, **(rules or {}))
    if set(value) != set(DEFAULT_RULES):
        raise ValueError("Unknown validation rule")
    for field in ("min_holdout", "repetitions"):
        if type(value[field]) is not int or value[field] < 1:
            raise ValueError("Validation case and repetition counts must be positive")
    if not _number(value["quality_gain"]) or value["quality_gain"] < 0:
        raise ValueError("Quality gain must be nonnegative")
    if not _number(value["resource_gain"]) or not 0 <= value["resource_gain"] < 1:
        raise ValueError("Resource gain must be in [0,1)")
    return value


def _model_policy(source: dict) -> list:
    policy = source.get("model_policy", [{"model": "gpt-6-luna", "effort": "medium"}, {"model": "gpt-6.1-sol", "effort": "high"}, {"model": "gpt-6-astra", "effort": "xhigh"}])
    if not isinstance(policy, list) or not policy or any(not isinstance(pair, dict) or set(pair) != {"model", "effort"} or not isinstance(pair["model"], str) or not pair["model"].strip() or pair["effort"] not in EFFORTS for pair in policy):
        raise ValueError("Source model_policy requires allowed model/effort pairs")
    return policy


def _document(bundle: Path) -> dict:
    try:
        document = json.loads((Path(bundle) / "playbook.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Missing/malformed playbook.json") from exc
    if not isinstance(document, dict) or set(document) != {"signed", "runtime"}:
        raise ValueError("playbook.json requires signed payload and separate runtime")
    return document


def build_playbook(workspace: Path, name: str, description: str, version: str,
                   artifacts: dict | list, provenance: dict, rules: dict | None = None) -> Path:
    """Build once from validated generated text. Source is tournament-source envelope.

    artifacts: {relative_path: UTF-8 content} or [{path, content}]. Root validates
    tournament champions before signing source; simulation is explicit and blocked
    from activation. A bundle name/version is never overwritten.
    """
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
        raise ValueError("Invalid playbook name")
    if not isinstance(description, str) or not description.strip() or not isinstance(version, str) or not version.strip():
        raise ValueError("Description and version required")
    source = signing.verify_payload(workspace, provenance, "tournament-source")
    if type(source.get("simulation")) is not bool:
        raise ValueError("Source must declare simulation")
    if not source["simulation"]:
        champions = source.get("champions", [])
        if not source.get("tournament_id") or not isinstance(champions, list) or {champion.get("tier") for champion in champions if isinstance(champion, dict)} != set(TIERS):
            raise ValueError("Verified tournament champions required for all tiers")
        if any(not c.get("competitor_id") or not isinstance(c.get("evidence"), list) or not c["evidence"] for c in champions):
            raise ValueError("Champion source requires verified match evidence")
    if isinstance(artifacts, list):
        if any(not isinstance(a, dict) or set(a) != {"path", "content"} for a in artifacts):
            raise ValueError("Artifact list entries require path/content")
        if len({a["path"] for a in artifacts}) != len(artifacts):
            raise ValueError("Duplicate artifact path")
        artifacts = {a["path"]: a["content"] for a in artifacts}
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("Generated artifact mapping required")
    rules = _rules(rules)
    validated = {}
    for relative, content in artifacts.items():
        path = _path(relative)
        if path.name in {"manifest.json", "playbook.json"} or path.suffix not in {".md", ".py", ".json", ".txt"} or not isinstance(content, str) or not content.strip():
            raise ValueError("Unsupported or empty generated artifact")
        if relative.casefold() in {key.casefold() for key in validated}:
            raise ValueError("Case-colliding artifact")
        validated[relative] = content
    validated.setdefault("index.md", '---\nokf_version: "0.2"\n---\n# Playbook\n\n* [Strategy](README.md) - Executable measured strategy.\n')
    root = Path(workspace).resolve()
    parent = root / ".playbooks"
    if parent.is_symlink():
        raise ValueError("Playbook directory must not be symlink")
    parent.mkdir(parents=True, exist_ok=True)
    bundle = parent / name
    if bundle.exists():
        raise ValueError("Playbook name already exists; generate a new version/name")
    bundle.mkdir()
    try:
        for relative, content in validated.items():
            target = bundle.joinpath(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        _structure(bundle)
        files = _files(bundle)
        model_policy = _model_policy(source)
        generation_id = signing.digest({"files": files, "rules": rules, "model_policy": model_policy, "source": source})
        manifest = {"schema_version": 1, "name": name, "description": description, "version": version,
                    "files": files, "rules": rules, "provenance": provenance, "model_policy": model_policy, "generation_id": generation_id,
                    "available_plugins": _available_plugins(bundle, files),
                    "tiers": {tier: {"candidate_hash": signing.digest({"tier": tier, "files": files, "rules": rules}), "validation": {"required": True, "storage": "workspace-local-signed-evidence"}} for tier in TIERS}}
        runtime = {"schema_version": 1, "selected_tier": "gold", "model": model_policy[-1]["model"], "effort": model_policy[-1]["effort"], "enabled_plugins": [], "candidate_hash": manifest["tiers"]["gold"]["candidate_hash"]}
        signing.write_json(bundle / "playbook.json", {"signed": signing.sign_payload(workspace, manifest, "playbook-manifest"), "runtime": runtime})
    except Exception:
        # Only this newly-created directory is removed; no caller-owned content.
        import shutil
        shutil.rmtree(bundle)
        raise
    return bundle


def generate_playbook(workspace: Path, name: str, description: str, version: str,
                      provenance: dict, generator, rules: dict | None = None) -> Path:
    """Explicit injected teacher callback receives champion evidence and contract."""
    if not callable(generator):
        raise ValueError("Explicit generation callback required")
    source = signing.verify_payload(workspace, provenance, "tournament-source")
    artifacts = generator({"name": name, "description": description, "version": version,
                           "champion_evidence": source, "tiers": list(TIERS),
                           "instruction": "Synthesize reusable automation and explanatory strategy concepts; do not copy winning answers. Return path/content artifacts for README, every tier scripts and .agents/_index.md + strategy.md, optional plugins/main.md modules."})
    return build_playbook(workspace, name, description, version, artifacts, provenance, rules)


def validate_playbook(workspace: Path, bundle: Path) -> dict:
    bundle = _bundle(workspace, bundle)
    document = _document(bundle)
    envelope = document["signed"]
    manifest = signing.verify_payload(workspace, envelope, "playbook-manifest")
    if manifest.get("schema_version") != 1 or manifest.get("name") != bundle.name:
        raise ValueError("Manifest schema/name mismatch")
    if _files(bundle) != manifest.get("files"):
        raise ValueError("Artifact hash closure mismatch: tampered or unmanifested files")
    if manifest.get('available_plugins', []) != _available_plugins(bundle, manifest['files']):
        raise ValueError('Signed available plugin inventory mismatch')
    _rules(manifest.get("rules"))
    source = signing.verify_payload(workspace, manifest.get("provenance"), "tournament-source")
    if _model_policy(source) != manifest.get("model_policy") or manifest.get("generation_id") != signing.digest({"files": manifest["files"], "rules": manifest["rules"], "model_policy": manifest["model_policy"], "source": source}):
        raise ValueError("Signed generation/model policy mismatch")
    validate_runtime(document["runtime"], manifest)
    if set(manifest.get("tiers", {})) != set(TIERS):
        raise ValueError("Manifest requires all tiers")
    for tier in TIERS:
        if manifest["tiers"][tier].get("candidate_hash") != candidate_hash(bundle, tier):
            raise ValueError("Frozen candidate hash mismatch")
    _structure(bundle)
    return manifest


def candidate_hash(bundle: Path, tier: str) -> str:
    if tier not in TIERS:
        raise ValueError("Unknown tier")
    try:
        manifest = _document(Path(bundle))["signed"]["payload"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("Missing candidate manifest") from exc
    return signing.digest({"tier": tier, "files": _files(Path(bundle)), "rules": manifest["rules"]})


def _number(value) -> bool:
    return type(value) in {int, float} and math.isfinite(value)


def _state(workspace: Path, bundle: Path) -> Path:
    identity = signing.digest(_document(Path(bundle))["signed"]["payload"])
    return signing._storage(workspace) / "playbooks" / identity


def record_validation(workspace: Path, bundle: Path, tier: str, receipts: list, holdout_id: str) -> dict:
    with signing.pipeline_lock(workspace, "holdout-validation"):
        return _record_validation(workspace, bundle, tier, receipts, holdout_id)


def _record_validation(workspace: Path, bundle: Path, tier: str, receipts: list, holdout_id: str) -> dict:
    """Consume signed paired holdout-run receipts; never trusts a 'passed' claim.

    Each payload: holdout_id,candidate_hash,case_id,case_hash,split='holdout',
    repetition(int),simulation(bool),execution_evidence(nonempty list),baseline,
    candidate. Arms: quality[0..100],complete(bool),hard_checks(bool),tokens,
    elapsed_ms. Missing resource counters remain None and cannot demonstrate gain.
    """
    manifest = validate_playbook(workspace, bundle)
    if tier not in TIERS or not isinstance(holdout_id, str) or not holdout_id.strip() or not isinstance(receipts, list):
        raise ValueError("Tier, holdout id and signed receipts required")
    chash = candidate_hash(bundle, tier)
    rows = []
    pairs = set()
    case_hashes = {}
    for receipt in receipts:
        row = signing.verify_payload(workspace, receipt, "holdout-run")
        if row.get("holdout_id") != holdout_id or row.get("candidate_hash") != chash or row.get("split") != "holdout":
            raise ValueError("Receipt does not match frozen candidate/holdout")
        if type(row.get("simulation")) is not bool or not isinstance(row.get("execution_evidence"), list) or len(row["execution_evidence"]) < 2:
            raise ValueError("Paired execution evidence and simulation flag required")
        case = row.get("case_id")
        rep = row.get("repetition")
        if not isinstance(case, str) or not case or type(rep) is not int or rep < 0 or not isinstance(row.get("case_hash"), str) or not row["case_hash"]:
            raise ValueError("Invalid case/repetition identity")
        if (case, rep) in pairs:
            raise ValueError("Duplicate paired case/repetition")
        pairs.add((case, rep))
        if case in case_hashes and case_hashes[case] != row["case_hash"]:
            raise ValueError("Case hash changed across repetitions")
        case_hashes[case] = row["case_hash"]
        for arm in ("baseline", "candidate"):
            metrics = row.get(arm)
            if not isinstance(metrics, dict) or not _number(metrics.get("quality")) or not 0 <= metrics["quality"] <= 100 or type(metrics.get("complete")) is not bool or type(metrics.get("hard_checks")) is not bool:
                raise ValueError("Invalid quality/completion/hard-check metrics")
            for resource in ("tokens", "elapsed_ms"):
                value = metrics.get(resource)
                if value is not None and (not _number(value) or value < 0):
                    raise ValueError("Invalid resource metric")
        rows.append(row)
    rules = manifest["rules"]
    if len(case_hashes) < rules["min_holdout"] or len(set(case_hashes.values())) != len(case_hashes):
        raise ValueError("Configured minimum distinct holdout cases required")
    for case in case_hashes:
        repetitions = {rep for name, rep in pairs if name == case}
        if repetitions != set(range(rules["repetitions"])):
            raise ValueError("Every holdout case requires paired repetitions")
    registry_path = signing._storage(workspace) / "holdout-use.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {}
    # The holdout identity binds case hashes, so renaming the holdout cannot bypass reuse.
    holdout_fingerprint = signing.digest(sorted(case_hashes.values()))
    generation_id = manifest["generation_id"]
    registry_keys = ["id:" + holdout_id, "set:" + holdout_fingerprint, *("case:" + case_hash for case_hash in case_hashes.values())]
    for key in registry_keys:
        prior = registry.get(key)
        if prior and (prior.get("generation_id") != generation_id or tier in prior.get("consumed_tiers", [])):
            raise ValueError("Holdout already used for this tier or revised generation; obtain fresh cases after tuning")
    baseline_q = statistics.mean(row["baseline"]["quality"] for row in rows)
    candidate_q = statistics.mean(row["candidate"]["quality"] for row in rows)
    baseline_failures = sum(not row["baseline"]["complete"] for row in rows)
    candidate_failures = sum(not row["candidate"]["complete"] for row in rows)
    hard_regression = any(row["baseline"]["hard_checks"] and not row["candidate"]["hard_checks"] for row in rows)
    # A candidate with any hard failure is never activated, even if baseline also fails.
    candidate_hard_failure = any(not row["candidate"]["hard_checks"] for row in rows)
    improvements = {}
    for resource in ("tokens", "elapsed_ms"):
        values = [(row["baseline"].get(resource), row["candidate"].get(resource)) for row in rows]
        if any(a is None or b is None for a, b in values) or sum(a for a, _ in values) <= 0:
            improvements[resource] = None
        else:
            improvements[resource] = 1 - sum(b for _, b in values) / sum(a for a, _ in values)
    quality_gain = candidate_q - baseline_q
    resource_gain = any(value is not None and value + 1e-12 >= rules["resource_gain"] for value in improvements.values())
    passed = not hard_regression and not candidate_hard_failure and candidate_failures <= baseline_failures and candidate_q >= baseline_q and (quality_gain >= rules["quality_gain"] or resource_gain)
    case_deltas = [statistics.mean(row["candidate"]["quality"] - row["baseline"]["quality"] for row in rows if row["case_id"] == case) for case in case_hashes]
    uncertainty = 1.96 * statistics.stdev(case_deltas) / math.sqrt(len(case_deltas)) if len(case_deltas) > 1 else None
    simulation = manifest["provenance"]["payload"]["simulation"] or any(row["simulation"] for row in rows)
    summary = {"schema_version": 1, "candidate_hash": chash, "generation_id": generation_id, "tier": tier, "holdout_id": holdout_id, "holdout_fingerprint": holdout_fingerprint,
               "passed": passed, "simulation": simulation, "samples": len(rows), "cases": len(case_hashes), "repetitions": rules["repetitions"],
               "baseline_quality": baseline_q, "candidate_quality": candidate_q, "quality_gain": quality_gain,
               "baseline_failures": baseline_failures, "candidate_failures": candidate_failures, "hard_regression": hard_regression,
               "resource_improvements": improvements, "uncertainty": {"method": "descriptive normal interval over independent case mean paired differences", "quality_gain_interval": [quality_gain - uncertainty, quality_gain + uncertainty] if uncertainty is not None else None, "warning": "Small samples; interval is descriptive, not a guarantee; undefined with one case"},
               "receipt_hashes": [signing.digest(receipt) for receipt in receipts]}
    evidence = {"summary": summary, "receipts": receipts}
    signing.write_json(_state(workspace, bundle) / (tier + "-validation.json"), signing.sign_payload(workspace, evidence, "playbook-validation"))
    for key in registry_keys:
        prior_tiers = registry.get(key, {}).get("consumed_tiers", [])
        registry[key] = {"generation_id": generation_id, "fingerprint": holdout_fingerprint, "consumed_tiers": sorted(set(prior_tiers) | {tier})}
    signing.write_json(registry_path, registry)
    return summary


def validation_evidence(workspace: Path, bundle: Path, tier: str) -> dict:
    manifest = validate_playbook(workspace, bundle)
    if tier not in TIERS:
        raise ValueError("Unknown tier")
    path = _state(workspace, bundle) / (tier + "-validation.json")
    if not path.exists():
        raise ValueError("Tier requires recorded signed validation")
    evidence = signing.verify_payload(workspace, json.loads(path.read_text(encoding="utf-8")), "playbook-validation")
    summary = evidence["summary"]
    if summary["candidate_hash"] != manifest["tiers"][tier]["candidate_hash"]:
        raise ValueError("Stale validation evidence")
    for receipt in evidence["receipts"]:
        signing.verify_payload(workspace, receipt, "holdout-run")
    if [signing.digest(r) for r in evidence["receipts"]] != summary["receipt_hashes"]:
        raise ValueError("Validation receipt closure mismatch")
    return summary


def activate(workspace: Path, bundle: Path, tier: str = "gold", model: str | None = None, effort: str | None = None) -> dict:
    manifest = validate_playbook(workspace, bundle)
    summary = validation_evidence(workspace, bundle, tier)
    if summary["simulation"]:
        raise ValueError("simulation evidence cannot activate a playbook")
    if not summary["passed"]:
        raise ValueError("Tier validation did not pass")
    pair = manifest["model_policy"][-1]
    runtime = {"schema_version": 1, "selected_tier": tier, "model": model if model is not None else pair["model"], "effort": effort if effort is not None else pair["effort"], "enabled_plugins": [], "candidate_hash": summary["candidate_hash"]}
    validate_runtime(runtime, manifest)
    write_runtime(workspace, bundle, runtime)
    return runtime


def validate_runtime(runtime: dict, manifest: dict | None = None) -> dict:
    if not isinstance(runtime, dict) or set(runtime) != {"schema_version", "selected_tier", "model", "effort", "enabled_plugins", "candidate_hash"} or runtime["schema_version"] != 1 or runtime["selected_tier"] not in TIERS:
        raise ValueError("Malformed runtime configuration")
    if runtime["model"] is not None and (not isinstance(runtime["model"], str) or not runtime["model"].strip()):
        raise ValueError("Invalid runtime model")
    if runtime["effort"] is not None and runtime["effort"] not in EFFORTS:
        raise ValueError("Invalid runtime effort")
    if not isinstance(runtime["enabled_plugins"], list) or any(not isinstance(plugin, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", plugin) for plugin in runtime["enabled_plugins"]) or len(set(runtime["enabled_plugins"])) != len(runtime["enabled_plugins"]):
        raise ValueError("Invalid enabled plugin list")
    if not isinstance(runtime["candidate_hash"], str) or not re.fullmatch(r"[0-9a-f]{64}", runtime["candidate_hash"]):
        raise ValueError("Runtime candidate hash must be SHA256")
    if manifest is not None:
        if {"model": runtime["model"], "effort": runtime["effort"]} not in manifest["model_policy"]:
            raise ValueError("Runtime model/effort is outside signed model policy")
        if runtime["candidate_hash"] != manifest["tiers"][runtime["selected_tier"]]["candidate_hash"]:
            raise ValueError("Runtime candidate hash does not match selected tier")
    return runtime


def write_runtime(workspace: Path, bundle: Path, runtime: dict) -> None:
    document = _document(bundle)
    manifest = signing.verify_payload(workspace, document["signed"], "playbook-manifest")
    document["runtime"] = validate_runtime(runtime, manifest)
    signing.write_json(Path(bundle) / "playbook.json", document)


def inspect_runtime(workspace: Path, bundle: Path) -> dict:
    """Read-only structural inspection; does not authorize tier or plugin execution."""
    manifest = validate_playbook(workspace, bundle)
    return validate_runtime(_document(bundle)["runtime"], manifest)


def get_runtime(workspace: Path, bundle: Path, *, check_plugins: bool = True) -> dict:
    runtime = inspect_runtime(workspace, bundle)
    summary = validation_evidence(workspace, bundle, runtime["selected_tier"])
    if not summary["passed"] or summary["simulation"] or runtime["candidate_hash"] != summary["candidate_hash"]:
        raise ValueError("Runtime tier is not validated")
    if check_plugins and runtime["enabled_plugins"]:
        from .arena_plugins import validate_enabled_plugins
        validate_enabled_plugins(workspace, bundle, runtime["enabled_plugins"])
    return runtime
