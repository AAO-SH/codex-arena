import pytest
from scripts.arena_config import load_config
from scripts.arena_runner import judge_outcomes, simulated_catalog, make_competitors, estimate_plan, UsageReceiptError


def test_quality_not_efficiency_decides_winner_and_failures_are_separate():
    a = {'completed':True,'fatal':False,'quality':70}
    b = {'completed':True,'fatal':False,'quality':80}
    assert judge_outcomes(a,b) == ('L','W')
    assert judge_outcomes({'completed':False}, b) == ('F','W')
    assert judge_outcomes({'completed':False},{'completed':False}) == ('F','F')
    assert judge_outcomes(a,a) == ('T','T')
    assert judge_outcomes(dict(b,fatal=True),a) == ('L','W')


def test_unique_competitors_and_plan_accounts_for_md10():
    config = load_config()
    competitors = make_competitors(config)
    assert len(competitors) == len({c['id'] for c in competitors}) == 100
    assert len({str(c['card']) for c in competitors}) == 100
    plan = estimate_plan(config,train_cases=5)
    assert plan['battle_matches'] == 4950
    assert plan['double_elimination_games_max_without_tiebreak'] == 600
    assert plan['calls_lower_bound'] >= 24750 + 2800


def supervisor(tmp_path, *, simulate=True):
    from scripts.arena_runner import Supervisor
    from scripts.arena_ledger import Ledger
    cfg = load_config()
    Ledger(tmp_path/'.memory/arena/state.sqlite').start_run('r',cfg,100000,100000)
    return Supervisor(tmp_path,'r',cfg,simulate=simulate,catalog=simulated_catalog(cfg))


def test_cached_call_requires_identical_prompt_model_schema_and_role(tmp_path):
    sup = supervisor(tmp_path)
    pair = sup.config['models']['policy'][0]
    sup.call('job','original',pair,simulated_payload={'completed':True})
    with pytest.raises(ValueError,match='identity'):
        sup.call('job','changed',pair,simulated_payload={'completed':True})
    with pytest.raises(ValueError,match='identity'):
        sup.call('job','original',pair,role='attack',simulated_payload={'completed':True})
    assert sup.ledger.budget('r')['used_tokens'] == 90


def test_safe_pre_dispatch_failure_retries_but_uncertain_execution_never_retries(tmp_path):
    from scripts import arena_executor as executor
    sup = supervisor(tmp_path,simulate=False)
    sup.executor.prepare = lambda *a,**k: None  # Transport double, no real inference.
    calls = []
    def execute(request,folder,**options):
        calls.append(request)
        if len(calls) == 1:
            raise executor.ExecutionNotStarted('transient spawn error',retryable=True)
        return {'payload':{'completed':True},'usage':{'input_tokens':60,'cached_input_tokens':20,
                  'output_tokens':30,'reasoning_output_tokens':10},'total_tokens':90,'elapsed_ms':10,'tools':[]}
    sup.executor.execute = execute
    sup.config['execution']['retry_backoff_ms'] = 0
    pair = sup.config['models']['policy'][0]
    sup.call('safe','task',pair)
    assert len(calls) == 2 and sup.ledger.budget('r')['used_tokens'] == 90
    def uncertain(*args,**kwargs):
        calls.append('uncertain')
        raise executor.ExecutionUncertain('may have consumed tokens')
    sup.executor.execute = uncertain
    with pytest.raises(executor.ExecutionUncertain):
        sup.call('uncertain','task',pair)
    assert len(calls) == 3
    assert next(j for j in sup.ledger.list_jobs('r') if j['id'] == 'uncertain')['status'] == 'ambiguous'


def started_run(tmp_path):
    from scripts.arena_runner import start_run
    cfg = load_config()
    cfg['tournament'].update(entrants=8,cut=0,qualifiers=2,swiss_rounds=1)
    suite = {'schema_version':1,'family':'test','cases':[
        {'id':f'{split}-{n}','prompt':'produce a brief answer','split':split,
         'completion':{'required_files':[],'checks':[]}}
        for split in ('train','holdout') for n in range(5)]}
    summary = start_run(tmp_path,cfg,suite,max_tokens=100000,max_ms=100000,simulate=True,max_matches=0)
    return cfg, suite, summary['run_id']


@pytest.mark.parametrize('kind',['training','competitors','code'])
def test_resume_refuses_changed_frozen_inputs_before_recovery(tmp_path,monkeypatch,kind):
    from scripts import arena_runner as runner
    from scripts.arena_config import read_json, atomic_json
    cfg, suite, run_id = started_run(tmp_path)
    directory = tmp_path/'.scratch/arena'/run_id
    if kind == 'code':
        monkeypatch.setattr(runner,'source_hashes',lambda: {'tampered.py':'changed'})
    else:
        path = directory/f'{kind}.json'
        value = read_json(path)
        if kind == 'training':
            value['cases'][0]['prompt'] = 'changed'
        else:
            value[0]['card']['reasoning'] = 'changed'
        atomic_json(path,value)
    with pytest.raises(ValueError,match='Frozen'):
        runner.resume_run(tmp_path,run_id,max_tokens=100000,max_ms=100000,max_matches=0)


def test_value_error_pauses_actionably_and_preserves_completed_match_receipt(tmp_path,monkeypatch):
    from scripts import arena_runner as runner
    from scripts import arena_tournament as tournament
    from scripts.arena_config import read_json
    from scripts.arena_ledger import Ledger
    cfg,suite,run_id = started_run(tmp_path)
    monkeypatch.setattr(tournament,'record_match',lambda *a,**k: (_ for _ in ()).throw(ValueError('invalid scored metrics')))
    summary = runner.resume_run(tmp_path,run_id,max_tokens=100000,max_ms=100000,max_matches=1)
    directory = tmp_path/'.scratch/arena'/run_id
    assert summary['budget']['status'] == 'paused'
    assert 'invalid scored metrics' in read_json(directory/'pause.json')['reason']
    assert list((directory/'matches').glob('*/result.json'))
    assert Ledger(tmp_path/'.memory/arena/state.sqlite').budget(run_id)['used_tokens'] > 0


def test_completion_contract_failure_escalates_and_cached_checks_are_not_reexecuted(tmp_path):
    sup = supervisor(tmp_path)
    competitor = {'policy':sup.config['models']['policy']}
    checked = []
    def completion(payload,directory):
        checked.append(directory)
        return {'completed':len(checked) > 1,'checks':[{'passed':len(checked) > 1}]}
    payload,receipts = sup.policy_call('task','solve',competitor,simulated_payload={'completed':True},completion_check=completion)
    assert len(receipts) == 2
    assert receipts[0]['completion_check']['completed'] is False
    assert receipts[1]['completion_check']['completed'] is True
    sup.policy_call('task','solve',competitor,simulated_payload={'completed':True},completion_check=completion)
    assert len(checked) == 2


def test_reconcile_only_accepts_trusted_settled_receipt_without_new_inference(tmp_path):
    from scripts import arena_runner as runner
    from scripts.arena_config import atomic_json,digest
    sup = supervisor(tmp_path)
    pair = sup.config['models']['policy'][0]
    good = sup.call('known','task',pair,simulated_payload={'completed':True})
    sup.ledger.reserve('r','uncertain',100,identity_hash=good['request_hash'])
    sup.ledger.mark_ambiguous('r','uncertain','transport lost after settled receipt')
    atomic_json(sup.directory/'receipts'/f'{digest("uncertain")}.json',dict(good,job_id='uncertain',turn_completed=True,turn_failed=False,returncode=0))
    atomic_json(sup.directory/'config.json',sup.config)
    result = runner.reconcile_job(tmp_path,'r','uncertain')
    assert result['status'] == 'complete'
    assert sup.ledger.budget('r')['used_tokens'] == 180
    runner.reconcile_job(tmp_path,'r','uncertain')
    assert sup.ledger.budget('r')['used_tokens'] == 180
    sup.ledger.reserve('r','missing',100,identity_hash='missing')
    sup.ledger.mark_ambiguous('r','missing','no settled token usage')
    with pytest.raises((RuntimeError,ValueError),match='receipt'):
        runner.reconcile_job(tmp_path,'r','missing')


def test_call_telemetry_separates_execution_and_queue_wait(tmp_path):
    sup = supervisor(tmp_path)
    receipt = sup.call('job','task',sup.config['models']['policy'][0],simulated_payload={'completed':True})
    assert receipt['wait_ms'] >= 0
    assert receipt['execution_ms'] == receipt['elapsed_ms'] == 10
    assert receipt['end_to_end_ms'] == receipt['execution_ms'] + receipt['wait_ms']


def test_large_aggregate_turn_cannot_claim_per_request_long_context_price():
    from scripts.arena_runner import _cost
    cfg = load_config()
    assert _cost({'input_tokens':300000,'cached_input_tokens':0,'output_tokens':100},'gpt-6-luna',cfg) is None
    assert _cost({'input_tokens':200000,'cached_input_tokens':0,'output_tokens':100},'gpt-6-luna',cfg) == pytest.approx(.02005)


def test_unsupported_isolation_blocks_before_any_token_reservation(tmp_path,monkeypatch):
    from scripts.arena_executor import ExecutionNotStarted
    sup = supervisor(tmp_path,simulate=False)
    def denied(*args,**kwargs):
        raise ExecutionNotStarted('strict isolation unavailable')
    sup.executor.prepare = denied
    sup.executor.execute = lambda *a,**k: pytest.fail('inference must not be dispatched')
    with pytest.raises(ExecutionNotStarted,match='strict isolation'):
        sup.call('job','task',sup.config['models']['policy'][0])
    assert sup.ledger.list_jobs('r') == []
    assert sup.ledger.budget('r')['used_tokens'] == sup.ledger.budget('r')['reserved_tokens'] == 0


def test_completed_match_replay_uses_durable_result_and_no_paid_calls(tmp_path):
    from scripts.arena_runner import Supervisor,resume_run
    from scripts.arena_ledger import Ledger
    from scripts.arena_config import read_json
    cfg,suite,run_id = started_run(tmp_path)
    directory = tmp_path/'.scratch/arena'/run_id
    ledger = Ledger(tmp_path/'.memory/arena/state.sqlite')
    state = ledger.load_state(run_id)
    from scripts.arena_tournament import next_matches
    job = next_matches(state,cfg)[0]
    sup = Supervisor(tmp_path,run_id,cfg,simulate=True)
    competitors = {c['id']:c for c in read_json(directory/'competitors.json')}
    case = read_json(directory/'training.json')['cases'][0]
    outcome = sup.match(job,competitors,case)
    sup.call = lambda *a,**k: pytest.fail('completed match must not repeat model calls')
    assert sup.match(job,competitors,case) == outcome
    used = ledger.budget(run_id)['used_tokens']
    summary = resume_run(tmp_path,run_id,max_tokens=100000,max_ms=100000,max_matches=1)
    assert summary['matches'] == 1 and ledger.budget(run_id)['used_tokens'] == used


def test_match_public_prompts_exclude_answer_keys_and_private_checks(tmp_path):
    sup = supervisor(tmp_path)
    case = {'id':'case','prompt':'write solution','context':'public context',
            'reference_answer':'PRIVATE_ANSWER','completion':{'required_files':[],
            'checks':[['PRIVATE_CHECK']]}}
    sup.check_artifact = lambda *a: {'completed':True,'checks':[]}
    captured = []
    call = sup.call
    def capture(job,prompt,pair,**kwargs):
        captured.append((kwargs.get('role'),prompt))
        return call(job,prompt,pair,**kwargs)
    sup.call = capture
    competitors = make_competitors(sup.config)[:2]
    sup.match({'id':'m','a':competitors[0]['id'],'b':competitors[1]['id']},
              {c['id']:c for c in competitors},case)
    for role,prompt in captured:
        if role != 'judge':
            assert 'PRIVATE_ANSWER' not in prompt and 'PRIVATE_CHECK' not in prompt
            assert 'public context' in prompt
    assert any('PRIVATE_ANSWER' in prompt for role,prompt in captured if role == 'judge')


def test_escalation_preserves_public_blocker_and_prior_work_only(tmp_path):
    sup = supervisor(tmp_path)
    prompts = []
    call = sup.call
    def capture(job,prompt,pair,**kwargs):
        prompts.append(prompt)
        return call(job,prompt,pair,**kwargs)
    sup.call = capture
    checks = iter([{'completed':False,'missing':['solution.py'],'public_reason':'Missing required deliverable',
                   'reason':'PRIVATE_COMMAND','checks':[{'output':'PRIVATE_OUTPUT'}]}, {'completed':True}])
    sup.policy_call('solve','task',{'policy':sup.config['models']['policy']},
                    simulated_payload={'completed':True,'answer':'Prior implemented solution'},
                    completion_check=lambda *a:next(checks))
    assert 'solution.py' in prompts[1] and 'Missing required deliverable' in prompts[1]
    assert 'Prior implemented solution' in prompts[1]
    assert 'PRIVATE_COMMAND' not in prompts[1] and 'PRIVATE_OUTPUT' not in prompts[1]


def test_all_configured_prices_checked_before_first_live_dispatch(tmp_path):
    sup = supervisor(tmp_path,simulate=False)
    sup.config['prices'].pop(sup.config['models']['arbiter']['model'])
    sup.executor.prepare = lambda *a,**k:pytest.fail('preflight must reject missing later model price')
    with pytest.raises(UsageReceiptError,match='price'):
        sup.call('first','task',sup.config['models']['policy'][0])
    assert sup.ledger.list_jobs('r') == []


def test_reconciliation_accepts_unknown_optional_reasoning_counter(tmp_path):
    from scripts.arena_runner import reconcile_job
    from scripts.arena_config import atomic_json,digest
    sup = supervisor(tmp_path)
    receipt = sup.call('known','task',sup.config['models']['policy'][0],simulated_payload={'completed':True})
    receipt['usage']['reasoning_output_tokens'] = None
    sup.ledger.reserve('r','uncertain',100,identity_hash=receipt['request_hash'])
    sup.ledger.mark_ambiguous('r','uncertain','settled turn, optional reasoning unknown')
    atomic_json(sup.directory/'receipts'/f'{digest("uncertain")}.json',receipt)
    atomic_json(sup.directory/'config.json',sup.config)
    assert reconcile_job(tmp_path,'r','uncertain')['status'] == 'complete'
    assert sup.ledger.completed('r','uncertain')['usage']['reasoning_output_tokens'] is None
