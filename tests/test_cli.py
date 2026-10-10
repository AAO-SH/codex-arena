import json
import subprocess
import sys
from pathlib import Path
import pytest

from scripts.arena_config import ROOT, load_config


def cli(*args, ok=True):
    result = subprocess.run([sys.executable, str(ROOT/'scripts/arena.py'), *map(str,args)],
                            capture_output=True,text=True,encoding='utf-8',timeout=60)
    assert (result.returncode == 0) is ok, result.stderr+result.stdout
    return json.loads(result.stdout)


def test_plan_json_and_budget_required(tmp_path):
    data = cli('plan','--json','--workspace',tmp_path)
    assert data['battle_matches'] == 4950
    assert data['calls_lower_bound'] >= 24750
    data = cli('run','--cases',tmp_path/'missing.json','--json',ok=False)
    assert data['ok'] is False


def test_cli_smoke_resume_report_and_demo(tmp_path):
    config = load_config()
    config['tournament'].update(entrants=8,cut=0,qualifiers=2,swiss_rounds=2)
    path = tmp_path/'config.json'
    path.write_text(json.dumps(config),encoding='utf-8')
    suite = {'schema_version':1,'family':'test','cases':[
        {'id':f'{split}-{i}','split':split,'prompt':f'{split} task {i}'}
        for split in ['train','holdout'] for i in range(5)]}
    cases = tmp_path/'suite.json'
    cases.write_text(json.dumps(suite),encoding='utf-8')
    common = ['--workspace',tmp_path,'--json']
    first = cli('run','--simulate','--config',path,'--cases',cases,'--max-tokens',100000,
                '--max-ms',120000,'--max-matches',2,*common)
    assert first['matches'] == 2
    final = cli('resume',first['run_id'],'--max-tokens',200000,'--max-ms',120000,*common)
    assert final['status'] == 'complete'
    assert len([v for v in final['champions'].values() if v]) == 4
    report = cli('report',first['run_id'],*common)
    assert len(report['competitors']) == 8
    assert report['competitors'][0]['completed'] > 0
    assert report['usage_by_role']
    demo = cli('playbook','build','--demo','--name','demo',*common)
    assert Path(demo['bundle']).is_dir()
    assert cli('playbook','verify','demo',*common)['verified']
    assert cli('playbook','activate','demo',*common,ok=False)['ok'] is False


def test_parser_json_even_on_invalid_arguments(tmp_path):
    error = cli('--json','playbook','validate','demo','--workspace',tmp_path,ok=False)
    assert error['ok'] is False


def test_install_works_with_only_standard_library(tmp_path):
    result = subprocess.run([sys.executable,'-S',str(ROOT/'scripts/arena.py'),'install',
                            '--workspace',str(tmp_path),'--json'],capture_output=True,text=True,encoding='utf-8',timeout=60)
    assert result.returncode == 0, result.stdout+result.stderr
    assert (tmp_path/'.agents/skills/codex-arena/SKILL.md').is_file()


def test_malformed_case_entry_is_reported_as_user_input_error(tmp_path):
    suite = tmp_path/'malformed.json'
    suite.write_text(json.dumps({'schema_version':1,'family':'test','cases':[[]]}),encoding='utf-8')
    result = cli('run','--cases',suite,'--max-tokens',100,'--max-ms',100,
                 '--workspace',tmp_path,'--json',ok=False)
    assert result['type'] == 'ValueError'


def test_double_elimination_job_matches_published_job_contract():
    from jsonschema import Draft202012Validator
    from scripts.build_contracts import contracts
    from scripts.arena_tournament import _job

    state = {'next_job':1,'jobs':{}}
    job_id = _job(state,'a','b','double_elimination','gold',1,
                  game=1,series='gold:U1:1',bracket='upper')
    job = state['jobs'][job_id]
    Draft202012Validator(contracts()['job']).validate(job)


def test_memory_cli_does_not_treat_explicit_zero_topk_as_unset(monkeypatch):
    from scripts import arena as arena_cli
    from scripts.arena_memory import MemoryIndex

    observed = {}
    original_search = MemoryIndex.search

    def recording_search(self, query, namespace, topk=8, context_token_budget=1200):
        observed['topk'] = topk
        return original_search(self, query, namespace, topk, context_token_budget)

    monkeypatch.setattr(MemoryIndex, 'search', recording_search)
    args = arena_cli.parser().parse_args(
        ['memory','search','query','--namespace','test','--topk','0']
    )
    with pytest.raises(ValueError, match='topk'):
        arena_cli.dispatch(args)
    assert observed['topk'] == 0
