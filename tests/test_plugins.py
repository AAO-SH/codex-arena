import pytest
from scripts import arena_plugins as plugins
from tests.test_playbooks import build, receipts
from scripts import arena_playbooks as p
from scripts import arena_signing as s


def plugin_text():
    return '---\ntype: Playbook\nname: audit\nrequires: []\ncapabilities: [inspect]\neffects: [write-report]\ninvariants: [preserve-evidence]\nincompatible: []\n---\n# Pseudocode\n1. Collect evidence.\n2. Verify each record.\n3. Write a report.\n'


def test_parse_requires_structured_semantics(tmp_path):
    file = tmp_path / "main.md"
    file.write_text(plugin_text())
    assert plugins.parse_plugin(file)["name"] == "audit"
    file.write_text('---\ntype: Playbook\nname: audit\n---\n# Pseudocode\n')
    with pytest.raises(ValueError):
        plugins.parse_plugin(file)


def test_semantic_review_unknown_denies_and_hash_bound_cache(tmp_path):
    from tests.test_playbooks import artifacts
    generated = artifacts()
    generated["plugins/audit/main.md"] = plugin_text()
    provenance = s.sign_payload(tmp_path, {"tournament_id": "t1", "model_policy": [{"model": "teacher", "effort": "high"}, {"model": "different-teacher", "effort": "high"}], "simulation": False, "champions": [{"tier": t, "competitor_id": t, "evidence": ["m1"]} for t in p.TIERS]}, "tournament-source")
    bundle = p.build_playbook(tmp_path, "with-plugin", "Measured", "1", generated, provenance)
    p.record_validation(tmp_path, bundle, "gold", receipts(tmp_path, bundle), "h1")
    p.activate(tmp_path, bundle, model="teacher", effort="high")
    with pytest.raises(ValueError, match="review"):
        plugins.set_plugins(tmp_path, bundle, ["audit"])
    with pytest.raises(ValueError, match="unknown"):
        plugins.set_plugins(tmp_path, bundle, ["audit"], reviewer=lambda context: {"decision": "unknown", "explanation": "Ambiguous effects"})
    calls = []
    def review(context):
        calls.append(context)
        return {"decision": "compatible", "explanation": "Evidence preserved and report isolated"}
    assert plugins.set_plugins(tmp_path, bundle, ["audit"], reviewer=review)["enabled_plugins"] == ["audit"]
    assert plugins.set_plugins(tmp_path, bundle, ["audit"])["enabled_plugins"] == ["audit"]
    assert len(calls) == 1
    assert p.get_runtime(tmp_path, bundle)["enabled_plugins"] == ["audit"]
    import json
    path = bundle / "playbook.json"
    document = json.loads(path.read_text())
    document["runtime"]["model"] = "different-teacher"
    s.write_json(path, document)
    with pytest.raises(ValueError, match="semantic review"):
        p.get_runtime(tmp_path, bundle)
    assert plugins.set_plugins(tmp_path, bundle, [])["enabled_plugins"] == []
    p.activate(tmp_path, bundle, model="different-teacher", effort="high")
    with pytest.raises(ValueError, match="review"):
        plugins.set_plugins(tmp_path, bundle, ["audit"])


def test_declared_conflict_and_dependency_deny_before_review(tmp_path):
    from tests.test_playbooks import artifacts
    generated = artifacts()
    generated["plugins/audit/main.md"] = plugin_text().replace("requires: []", "requires: [missing]")
    provenance = s.sign_payload(tmp_path, {"tournament_id": "t1", "simulation": False, "champions": [{"tier": t, "competitor_id": t, "evidence": ["m1"]} for t in p.TIERS]}, "tournament-source")
    bundle = p.build_playbook(tmp_path, "dependent", "Measured", "1", generated, provenance)
    p.record_validation(tmp_path, bundle, "gold", receipts(tmp_path, bundle), "h1")
    p.activate(tmp_path, bundle)
    with pytest.raises(ValueError, match="required plugin"):
        plugins.set_plugins(tmp_path, bundle, ["audit"], reviewer=lambda context: pytest.fail("Review must not run on structural conflict"))


def test_candidate_structural_check_does_not_authorize_enable_or_disable(tmp_path):
    from scripts.arena_workflows import build_demo
    from scripts import arena as cli
    bundle = build_demo(tmp_path, 'candidate')
    before = (bundle/'playbook.json').read_bytes()
    args = cli.parser().parse_args(['plugin', 'check', 'candidate', 'check-contract', '--workspace', str(tmp_path), '--json'])
    result = cli.dispatch(args)
    assert result['structural_check'] == 'passed'
    assert result['semantic_review_required'] is True
    assert result['context']['enabled'] == ['check-contract']
    assert (bundle/'playbook.json').read_bytes() == before
    assert not p._state(tmp_path, bundle).exists()
    for operation in ('enable', 'disable'):
        args = cli.parser().parse_args(['plugin', operation, 'candidate', 'check-contract', '--workspace', str(tmp_path), '--json'])
        with pytest.raises(ValueError, match='validation'):
            cli.dispatch(args)
    with pytest.raises(ValueError, match='validation'):
        plugins.set_plugins(tmp_path, bundle, ['check-contract'], reviewer=lambda context: pytest.fail('Unvalidated tier cannot reach semantic reviewer'))


def test_candidate_structural_check_still_rejects_tampering(tmp_path):
    from scripts.arena_workflows import build_demo
    bundle = build_demo(tmp_path, 'candidate')
    path = bundle/'plugins/check-contract/main.md'
    path.write_text(path.read_text(encoding='utf-8')+'\nChanged effects\n', encoding='utf-8')
    with pytest.raises(ValueError, match='closure'):
        plugins.structural_context(tmp_path, bundle, ['check-contract'])
