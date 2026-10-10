from pathlib import Path
import pytest
from scripts.arena_workflows import demo_artifacts, build_demo, validate_bundle
from scripts.arena_config import load_config
from scripts.arena_playbooks import validate_playbook, activate


def test_auxiliary_resume_rejects_changed_engine(tmp_path,monkeypatch):
    from scripts import arena_workflows as flows
    config=load_config()
    supervisor=flows._new_aux(tmp_path,config,'validate',10000,10000,True)
    run_id=supervisor.run_id
    flows._close_aux(supervisor)
    monkeypatch.setattr(flows,'source_hashes',lambda:{'changed':'different-engine'})
    with pytest.raises(ValueError,match='Frozen auxiliary'):
        flows._new_aux(tmp_path,config,'validate',10000,10000,True,resume_id=run_id)
from scripts import arena_workflows as workflows, arena_playbooks as books


def holdout_suite():
    return {'schema_version': 1, 'family': 'json', 'cases': [
        {'id': str(i), 'split': 'holdout', 'prompt': f'Analyze distinct case {i}'} for i in range(5)]}


def test_demo_is_executable_and_cannot_be_activated_as_real_evidence(tmp_path):
    bundle = build_demo(tmp_path,'demo')
    manifest = validate_playbook(tmp_path,bundle)
    assert manifest['provenance']['payload']['simulation']
    import subprocess, sys
    for tier in ('iron','copper','silver','gold'):
        result = subprocess.run([sys.executable,str(bundle/'tier'/tier/'scripts/strategy.py'),'--self-test'],capture_output=True,text=True)
        assert result.returncode == 0, result.stderr
    with pytest.raises(ValueError):
        activate(tmp_path,bundle)


def test_paired_validation_records_simulation_without_enabling_it(tmp_path):
    bundle = build_demo(tmp_path,'demo')
    suite = {'schema_version':1,'family':'json','cases':[
        {'id':str(i),'split':'holdout','prompt':f'Analyze distinct case {i}'} for i in range(5)]}
    output = validate_bundle(tmp_path,bundle,suite,load_config(),tiers=['gold'],
                             max_tokens=100000,max_ms=120000,simulate=True)
    assert output['validation']['gold']['samples'] == 15
    assert output['validation']['gold']['simulation']
    with pytest.raises(ValueError):
        activate(tmp_path,bundle)


def test_case_identity_ignores_renamed_ids_and_split():
    case = {'id': 'old', 'split': 'train', 'prompt': 'Solve exactly this case', 'completion': {'checks': [['python', 'check.py']]}}
    renamed = {**case, 'id': 'new', 'split': 'holdout'}
    assert workflows.case_content_hash(case) == workflows.case_content_hash(renamed)


def test_duplicate_content_with_different_ids_rejected(tmp_path):
    bundle = build_demo(tmp_path, 'demo')
    suite = holdout_suite()
    suite['cases'][1]['prompt'] = suite['cases'][0]['prompt']
    with pytest.raises(ValueError, match='distinct'):
        validate_bundle(tmp_path, bundle, suite, load_config(), tiers=['gold'], max_tokens=100000, max_ms=120000, simulate=True)


def test_generated_scripts_tested_before_publication_and_timeout_explicit(tmp_path, monkeypatch):
    source = {'tournament_id': 'demonstration', 'simulation': True, 'champions': [], 'model_policy': load_config()['models']['policy']}
    monkeypatch.setattr(workflows, '_source', lambda workspace, run_id: (source, load_config()))
    generated = demo_artifacts()
    generated['tier/gold/scripts/strategy.py'] = 'import sys\ndef automate(values):\n    return sorted(values)\nif __name__ == "__main__":\n    raise SystemExit(7)\n'
    with pytest.raises(ValueError, match='self-test'):
        workflows.build_from_run(tmp_path, 'demo', 'failed', 'Description', artifacts=generated, self_test_timeout_ms=1000)
    assert not (tmp_path / '.playbooks/failed').exists()
    generated['tier/gold/scripts/strategy.py'] = 'import time\ndef automate(values):\n    return sorted(values)\nif __name__ == "__main__":\n    time.sleep(5)\n'
    with pytest.raises(ValueError, match='timeout'):
        workflows.build_from_run(tmp_path, 'demo', 'timed-out', 'Description', artifacts=generated, self_test_timeout_ms=100)
    assert not (tmp_path / '.playbooks/timed-out').exists()


def test_demo_records_real_script_checks(tmp_path):
    bundle = build_demo(tmp_path, 'demo')
    tests = validate_playbook(tmp_path, bundle)['provenance']['payload']['script_tests']
    assert len(tests) == 4
    assert all(test['passed'] and test['timeout_ms'] > 0 and test['sha256'] for test in tests)
    manifest = validate_playbook(tmp_path, bundle)
    assert manifest['available_plugins'][0]['name'] == 'check-contract'
    assert manifest['available_plugins'][0]['sha256'] == manifest['files']['plugins/check-contract/main.md']


def test_resume_skips_already_published_tier(tmp_path, monkeypatch):
    bundle = build_demo(tmp_path, 'demo')
    suite = holdout_suite()
    original = books.record_validation
    failed = False
    def publish(workspace, bundle, tier, receipts, holdout_id):
        nonlocal failed
        if tier == 'silver' and not failed:
            failed = True
            raise RuntimeError('interrupted before tier publication')
        return original(workspace, bundle, tier, receipts, holdout_id)
    monkeypatch.setattr(books, 'record_validation', publish)
    with pytest.raises(RuntimeError, match='resume evaluation'):
        validate_bundle(tmp_path, bundle, suite, load_config(), tiers=['gold', 'silver'], max_tokens=150000, max_ms=120000, simulate=True)
    directories = list((tmp_path / '.scratch/arena').glob('validate-*'))
    assert len(directories) == 1
    result = validate_bundle(tmp_path, bundle, suite, load_config(), tiers=['gold', 'silver'], max_tokens=150000, max_ms=120000, simulate=True, resume_id=directories[0].name)
    assert set(result['validation']) == {'gold', 'silver'}


def test_task_prompt_does_not_expose_private_evaluator(tmp_path, monkeypatch):
    bundle = build_demo(tmp_path, 'demo')
    suite = holdout_suite()
    for case in suite['cases']:
        case['completion'] = {'checks': [['python', '-c', 'print("SECRET_CHECK")']], 'required_files': []}
        case['expected_answer'] = 'SECRET_EXPECTED'
    observed = []
    original = workflows.Supervisor.policy_call
    def call(self, job_id, prompt, competitor, **kwargs):
        observed.append(prompt)
        return original(self, job_id, prompt, competitor, **kwargs)
    monkeypatch.setattr(workflows.Supervisor, 'policy_call', call)
    validate_bundle(tmp_path, bundle, suite, load_config(), tiers=['gold'], max_tokens=100000, max_ms=120000, simulate=True)
    assert observed
    assert all('SECRET_CHECK' not in prompt and 'SECRET_EXPECTED' not in prompt for prompt in observed)


def test_self_test_disconnected_from_automation_is_rejected():
    artifacts = demo_artifacts()
    artifacts['tier/gold/scripts/strategy.py'] = 'def automate(values):\n    return sorted(values)\nif __name__ == "__main__":\n    print("pretend checks passed")\n'
    with pytest.raises(ValueError, match='does not exercise'):
        workflows.test_generated_scripts(artifacts, timeout_ms=1000)


def test_teacher_evidence_is_copied_verified_and_paths_relative(tmp_path):
    import hashlib
    evidence = tmp_path / 'training-match.json'
    evidence.write_text('{"training": "verified only"}')
    source = {'champions': [{'tier': 'gold', 'evidence': [{'path': str(evidence), 'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest()}]}]}
    job = tmp_path / 'teacher-job'
    materialized = workflows.stage_teacher_evidence(source, job)
    relative = materialized['champions'][0]['evidence'][0]['path']
    assert not Path(relative).is_absolute()
    assert (job / relative).read_bytes() == evidence.read_bytes()
    assert source['champions'][0]['evidence'][0]['path'] == str(evidence)
    evidence.write_text('tampered')
    with pytest.raises(ValueError, match='evidence'):
        workflows.stage_teacher_evidence(source, tmp_path / 'another-job')


def test_renaming_all_case_ids_cannot_reuse_tier(tmp_path):
    bundle = build_demo(tmp_path, 'demo')
    suite = holdout_suite()
    validate_bundle(tmp_path, bundle, suite, load_config(), tiers=['gold'], max_tokens=100000, max_ms=120000, simulate=True)
    for case in suite['cases']:
        case['id'] += '-renamed'
    with pytest.raises(RuntimeError, match='already used'):
        validate_bundle(tmp_path, bundle, suite, load_config(), tiers=['gold'], max_tokens=100000, max_ms=120000, simulate=True)


def test_self_test_accepts_class_automation():
    artifacts = demo_artifacts()
    artifacts['tier/gold/scripts/strategy.py'] = '''import argparse
class Strategy:
    def rank(self, values):
        return sorted(values)
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        assert Strategy().rank([3, 1, 2]) == [1, 2, 3]
if __name__ == '__main__':
    main()
'''
    assert len(workflows.test_generated_scripts(artifacts, timeout_ms=1000)) == 4


def test_invalid_tiers_and_duplicate_case_ids_rejected_before_jobs(tmp_path):
    bundle = build_demo(tmp_path, 'demo')
    with pytest.raises(ValueError, match='tier'):
        validate_bundle(tmp_path, bundle, holdout_suite(), load_config(), tiers=['unknown'], max_tokens=100000, max_ms=120000, simulate=True)
    suite = holdout_suite()
    suite['cases'][1]['id'] = suite['cases'][0]['id']
    with pytest.raises(ValueError, match='case id'):
        validate_bundle(tmp_path, bundle, suite, load_config(), tiers=['gold'], max_tokens=100000, max_ms=120000, simulate=True)
    assert not (tmp_path / '.scratch/arena').exists()


def test_live_self_tests_use_enforced_profile_without_legacy_sandbox(tmp_path, monkeypatch):
    # This test inspects argv; it must not depend on an installed Codex CLI.
    executable = str(tmp_path / 'codex')
    monkeypatch.setattr(workflows.shutil, 'which', lambda name: executable)
    script = tmp_path / 'strategy.py'
    command = workflows.self_test_command(script, tmp_path, isolated=True)
    assert command[0] == executable
    assert 'sandbox' in command
    assert '--permission-profile' in command
    assert 'arena_job' in command
    assert '--sandbox' not in command
    assert ':root' in ' '.join(command)
    assert '--self-test' in command
    assert not any(item.startswith('permissions.arena_job.filesystem."') for item in command)


def test_live_self_test_command_requires_codex_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(workflows.shutil, 'which', lambda name: None)
    with pytest.raises(RuntimeError, match='Codex sandbox is required'):
        workflows.self_test_command(tmp_path / 'strategy.py', tmp_path, isolated=True)


def test_build_from_completed_simulated_eight_entrant_tournament(tmp_path, monkeypatch):
    from scripts.arena_runner import start_run
    config = load_config()
    config['tournament'].update({'entrants': 8, 'cut': 0, 'qualifiers': 1, 'swiss_rounds': 1, 'series_games': 1, 'extra_games': 1})
    suite = holdout_suite()
    suite['cases'] += [{'id': 'train-' + str(i), 'split': 'train', 'prompt': f'Training task {i}'} for i in range(5)]
    prompts = []
    original = workflows.Supervisor.call
    def call(self, job_id, prompt, pair, **kwargs):
        if kwargs.get('role') == 'distillation':
            prompts.append(prompt)
        return original(self, job_id, prompt, pair, **kwargs)
    monkeypatch.setattr(workflows.Supervisor, 'call', call)
    report = start_run(tmp_path, config, suite, max_tokens=100000, max_ms=180000, simulate=True)
    result = workflows.build_from_run(tmp_path, report['run_id'], 'from-tournament', 'Verified simulated provenance', max_tokens=10000, max_ms=60000)
    bundle = Path(result['bundle'])
    manifest = validate_playbook(tmp_path, bundle)
    source = manifest['provenance']['payload']
    assert source['tournament_id'] == report['run_id']
    assert source['simulation']
    assert len(source['champions']) == 4
    assert all(champion['evidence'] for champion in source['champions'])
    assert len(source['script_tests']) == 4
    teacher_prompt = prompts[0]
    assert str(tmp_path) not in teacher_prompt
    assert 'evidence/' in teacher_prompt
    assert all('Training task' not in c['prompt'] for c in suite['cases'] if c['split'] == 'holdout')


def test_judged_fatal_incomplete_candidate_cannot_promote(tmp_path, monkeypatch):
    bundle = build_demo(tmp_path, 'demo')
    monkeypatch.setattr(workflows.Supervisor, 'judge', lambda *args: {
        'a': {'quality': 80, 'completed': True, 'fatal': False},
        'b': {'quality': 95, 'completed': False, 'fatal': True}})
    result = validate_bundle(tmp_path, bundle, holdout_suite(), load_config(), tiers=['gold'], max_tokens=100000, max_ms=120000, simulate=True)
    summary = result['validation']['gold']
    assert not summary['passed']
    assert summary['candidate_failures'] == 15
    assert summary['hard_regression']


def test_configured_rubric_quality_normalized_to_percent(tmp_path, monkeypatch):
    bundle = build_demo(tmp_path, 'demo')
    config = load_config()
    config['rubric'] = {key: value * 2 for key, value in config['rubric'].items()}
    monkeypatch.setattr(workflows.Supervisor, 'judge', lambda *args: {
        'a': {'quality': 160, 'completed': True, 'fatal': False},
        'b': {'quality': 180, 'completed': True, 'fatal': False}})
    result = validate_bundle(tmp_path, bundle, holdout_suite(), config, tiers=['gold'], max_tokens=100000, max_ms=120000, simulate=True)
    summary = result['validation']['gold']
    assert summary['baseline_quality'] == 80
    assert summary['candidate_quality'] == 90
