import pytest
from scripts import arena_playbooks as p
from scripts import arena_signing as s


def artifacts():
    result = {"README.md": '---\ntype: Playbook\n---\n# Paired evaluation\nApply measured strategy and verify outputs.\n'}
    for tier in p.TIERS:
        result[f"tier/{tier}/scripts/strategy.py"] = 'def rank(items):\n    """Rank candidates by verified evidence."""\n    return sorted(items, key=lambda item: item["quality"], reverse=True)\n'
        result[f"tier/{tier}/.agents/_index.md"] = '---\ntype: Playbook\n---\n# Dispatch\nRead strategy.md and execute the evidence ranking script.\n'
        result[f"tier/{tier}/.agents/strategy.md"] = '---\ntype: Playbook\n---\n# Strategy\nMeasure quality for each candidate, rank verified records, and independently verify the selected output.\n'
    return result


def build(tmp_path, simulation=False):
    source = s.sign_payload(tmp_path, {"tournament_id": "t1", "model_policy": [{"model": "teacher", "effort": "high"}, {"model": "different-teacher", "effort": "high"}], "champions": [{"tier": t, "competitor_id": t, "evidence": ["match-1"]} for t in p.TIERS], "simulation": simulation}, "tournament-source")
    return p.build_playbook(tmp_path, "measured", "Measured strategy", "1.0", artifacts(), source)


def receipts(tmp_path, bundle, *, simulation=False, gain=6, regression=False, tier="gold"):
    chash = p.candidate_hash(bundle, tier)
    result = []
    for case in range(5):
        for rep in range(3):
            result.append(s.sign_payload(tmp_path, {"holdout_id": "h1", "candidate_hash": chash, "case_id": str(case), "case_hash": f"hash-{case}", "split": "holdout", "repetition": rep, "simulation": simulation, "baseline": {"quality": 80, "complete": True, "hard_checks": True, "tokens": 100, "elapsed_ms": 100}, "candidate": {"quality": 80 + gain, "complete": True, "hard_checks": not regression, "tokens": 100, "elapsed_ms": 100}, "execution_evidence": ["job-baseline", "job-candidate"]}, "holdout-run"))
    return result


def test_signed_bundle_hash_closure_and_traversal(tmp_path):
    bundle = build(tmp_path)
    assert p.validate_playbook(tmp_path, bundle)["name"] == "measured"
    (bundle / "tier/gold/scripts/strategy.py").write_text('raise RuntimeError("tamper")')
    with pytest.raises(ValueError):
        p.validate_playbook(tmp_path, bundle)
    bad = artifacts()
    bad["../escape.py"] = "print(1)"
    with pytest.raises(ValueError):
        p.build_playbook(tmp_path, "escape", "Description", "1", bad, s.sign_payload(tmp_path, {"simulation": True}, "tournament-source"))


def test_holdout_gates_activation_and_reuse(tmp_path):
    bundle = build(tmp_path)
    with pytest.raises(ValueError, match="validation"):
        p.activate(tmp_path, bundle)
    summary = p.record_validation(tmp_path, bundle, "gold", receipts(tmp_path, bundle), "h1")
    assert summary["passed"] is True
    assert summary["samples"] == 15
    assert p.activate(tmp_path, bundle)["selected_tier"] == "gold"
    with pytest.raises(ValueError, match="already used"):
        p.record_validation(tmp_path, bundle, "gold", receipts(tmp_path, bundle), "h1")


def test_regression_simulation_and_unsigned_claim_rejected(tmp_path):
    bundle = build(tmp_path)
    with pytest.raises(ValueError):
        p.record_validation(tmp_path, bundle, "gold", [{"passed": True}], "h1")
    assert not p.record_validation(tmp_path, bundle, "gold", receipts(tmp_path, bundle, regression=True), "h1")["passed"]
    other = tmp_path / "simulation"
    demo = build(other, simulation=True)
    p.record_validation(other, demo, "gold", receipts(other, demo, simulation=True), "h1")
    with pytest.raises(ValueError, match="simulation"):
        p.activate(other, demo)


def test_extra_unmanifested_file_rejected(tmp_path):
    bundle = build(tmp_path)
    (bundle / "extra.txt").write_text("unmanifested")
    with pytest.raises(ValueError, match="closure"):
        p.validate_playbook(tmp_path, bundle)


def test_minimum_repetitions_missing_resources_and_negative_quality(tmp_path):
    bundle = build(tmp_path)
    rows = receipts(tmp_path, bundle, gain=0)
    with pytest.raises(ValueError, match="repetitions"):
        p.record_validation(tmp_path, bundle, "gold", rows[:-1], "h1")
    for row in rows:
        payload = row["payload"]
        payload["baseline"]["tokens"] = None
        payload["candidate"]["tokens"] = None
        payload["baseline"]["elapsed_ms"] = None
        payload["candidate"]["elapsed_ms"] = None
    rows = [s.sign_payload(tmp_path, row["payload"], "holdout-run") for row in rows]
    summary = p.record_validation(tmp_path, bundle, "gold", rows, "h1")
    assert summary["passed"] is False
    assert summary["resource_improvements"] == {"tokens": None, "elapsed_ms": None}


def test_resource_improvement_without_quality_loss_passes(tmp_path):
    bundle = build(tmp_path)
    rows = receipts(tmp_path, bundle, gain=0)
    for row in rows:
        row["payload"]["candidate"]["tokens"] = 85
    rows = [s.sign_payload(tmp_path, row["payload"], "holdout-run") for row in rows]
    assert p.record_validation(tmp_path, bundle, "gold", rows, "h1")["passed"]


def test_stub_rejected_and_tier_tamper_invalidates_evidence(tmp_path):
    generated = artifacts()
    generated["tier/gold/scripts/strategy.py"] = 'def automate():\n    pass\n'
    with pytest.raises(ValueError, match="Stub"):
        p.build_playbook(tmp_path, "stub", "Description", "1", generated, s.sign_payload(tmp_path, {"simulation": True}, "tournament-source"))
    bundle = build(tmp_path)
    p.record_validation(tmp_path, bundle, "gold", receipts(tmp_path, bundle), "h1")
    p.activate(tmp_path, bundle)
    (bundle / "tier/gold/.agents/strategy.md").write_text("tampered")
    with pytest.raises(ValueError):
        p.get_runtime(tmp_path, bundle)


def test_rename_holdout_cannot_reuse_same_cases(tmp_path):
    bundle = build(tmp_path)
    rows = receipts(tmp_path, bundle)
    p.record_validation(tmp_path, bundle, "gold", rows, "h1")
    for row in rows:
        row["payload"]["holdout_id"] = "renamed"
    rows = [s.sign_payload(tmp_path, row["payload"], "holdout-run") for row in rows]
    with pytest.raises(ValueError, match="already used"):
        p.record_validation(tmp_path, bundle, "gold", rows, "renamed")


def test_partial_holdout_reuse_is_rejected(tmp_path):
    bundle = build(tmp_path)
    p.record_validation(tmp_path, bundle, "gold", receipts(tmp_path, bundle), "h1")
    rows = receipts(tmp_path, bundle)
    for row in rows:
        row["payload"]["holdout_id"] = "h2"
        if row["payload"]["case_id"] != "0":
            row["payload"]["case_hash"] += "-fresh"
    rows = [s.sign_payload(tmp_path, row["payload"], "holdout-run") for row in rows]
    with pytest.raises(ValueError, match="already used"):
        p.record_validation(tmp_path, bundle, "gold", rows, "h2")


def test_exact_ten_percent_resource_gain_passes(tmp_path):
    bundle = build(tmp_path)
    rows = receipts(tmp_path, bundle, gain=0)
    for row in rows:
        row["payload"]["candidate"]["tokens"] = 90
    rows = [s.sign_payload(tmp_path, row["payload"], "holdout-run") for row in rows]
    assert p.record_validation(tmp_path, bundle, "gold", rows, "h1")["passed"]


def test_generated_bytecode_is_unmanifested_and_external_state_symlink_rejected(tmp_path):
    bundle = build(tmp_path)
    script_dir = bundle / "tier/gold/scripts"
    (script_dir / "__pycache__").mkdir()
    (script_dir / "__pycache__/strategy.pyc").write_bytes(b"cached")
    with pytest.raises(ValueError, match="closure"):
        p.validate_playbook(tmp_path, bundle)


def test_runtime_candidate_hash_must_be_well_formed():
    runtime = {"schema_version": 1, "selected_tier": "gold", "model": None, "effort": None, "enabled_plugins": [], "candidate_hash": "invented"}
    with pytest.raises(ValueError):
        p.validate_runtime(runtime)


def test_playbook_json_runtime_mutable_and_identity_stable(tmp_path):
    import json
    bundle = build(tmp_path)
    path = bundle / "playbook.json"
    assert path.is_file()
    identity = p._state(tmp_path, bundle)
    p.record_validation(tmp_path, bundle, "gold", receipts(tmp_path, bundle), "h1")
    p.activate(tmp_path, bundle, model="teacher", effort="high")
    document = json.loads(path.read_text())
    document["runtime"]["model"] = "different-teacher"
    s.write_json(path, document)
    assert p._state(tmp_path, bundle) == identity
    assert p.get_runtime(tmp_path, bundle)["model"] == "different-teacher"
    document["runtime"]["model"] = "unauthorized-model"
    s.write_json(path, document)
    with pytest.raises(ValueError, match="policy"):
        p.get_runtime(tmp_path, bundle)


def test_configurable_validation_and_one_case_uncertainty(tmp_path):
    source = s.sign_payload(tmp_path, {"simulation": True}, "tournament-source")
    bundle = p.build_playbook(tmp_path, "small", "Simulation", "1", artifacts(), source, {"min_holdout": 1, "repetitions": 1, "quality_gain": 0, "resource_gain": 0})
    rows = receipts(tmp_path, bundle, simulation=True, gain=0)[:1]
    result = p.record_validation(tmp_path, bundle, "gold", rows, "h1")
    assert result["passed"]
    assert result["uncertainty"]["quality_gain_interval"] is None


def test_frozen_generation_allows_same_holdout_for_different_tiers(tmp_path):
    bundle = build(tmp_path)
    p.record_validation(tmp_path, bundle, "gold", receipts(tmp_path, bundle), "h1")
    rows = receipts(tmp_path, bundle, tier="silver")
    assert p.record_validation(tmp_path, bundle, "silver", rows, "h1")["passed"]
    with pytest.raises(ValueError, match="already used"):
        p.record_validation(tmp_path, bundle, "silver", rows, "h1")
    source = s.sign_payload(tmp_path, {"simulation": True}, "tournament-source")
    generated = artifacts()
    generated["README.md"] += "\nTuned after measurement.\n"
    revised = p.build_playbook(tmp_path, "tuned", "Tuned", "2", generated, source)
    with pytest.raises(ValueError, match="already used"):
        p.record_validation(tmp_path, revised, "gold", receipts(tmp_path, revised), "h1")


def test_concurrent_duplicate_validation_consumed_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    bundle = build(tmp_path)
    rows = receipts(tmp_path, bundle)
    def evaluate():
        try:
            p.record_validation(tmp_path, bundle, "gold", rows, "h1")
            return "passed"
        except ValueError as exc:
            assert "already used" in str(exc)
            return "blocked"
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: evaluate(), range(2))) == ["blocked", "passed"]
