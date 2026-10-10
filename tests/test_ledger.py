import pytest
from scripts.arena_ledger import Ledger, BudgetExceeded, AmbiguousAttempt


def test_reservations_prevent_concurrent_oversubscription(tmp_path):
    ledger = Ledger(tmp_path / 'state.sqlite')
    ledger.start_run('r', {'x': 1}, 100, 10000)
    ledger.reserve('r', 'job1', 60)
    with pytest.raises(BudgetExceeded):
        ledger.reserve('r', 'job2', 60)
    ledger.finish('r', 'job1', {'ok': True}, 30, 100)
    ledger.reserve('r', 'job2', 60)
    assert ledger.budget('r')['used_tokens'] == 30


def test_receipts_idempotent_and_conflict_rejected(tmp_path):
    ledger = Ledger(tmp_path / 's.sqlite')
    ledger.start_run('r', {}, 100, 10000)
    ledger.reserve('r', 'j', 20)
    ledger.finish('r', 'j', {'answer': 'x'}, 10, 5)
    ledger.finish('r', 'j', {'answer': 'x'}, 10, 5)
    assert ledger.budget('r')['used_tokens'] == 10
    assert ledger.completed('r', 'j') == {'answer': 'x'}
    with pytest.raises(ValueError):
        ledger.finish('r', 'j', {'answer': 'y'}, 10, 5)


def test_unknown_cost_and_crash_never_silently_retried(tmp_path):
    ledger = Ledger(tmp_path / 's.sqlite')
    ledger.start_run('r', {}, 100, 10000)
    ledger.reserve('r', 'j', 20)
    ledger.mark_ambiguous('r', 'j', 'transport lost after dispatch')
    with pytest.raises(AmbiguousAttempt):
        ledger.reserve('r', 'j', 20)
    assert ledger.budget('r')['reserved_tokens'] == 20


def test_checkpoint_roundtrip_and_explicit_budget_extension(tmp_path):
    ledger = Ledger(tmp_path / 's.sqlite')
    ledger.start_run('r', {}, 100, 10000)
    ledger.checkpoint('r', {'round': 2})
    assert ledger.load_state('r') == {'round': 2}
    ledger.extend('r', 200, 20000)
    assert ledger.budget('r')['max_tokens'] == 200


def test_reusable_draft_charged_exactly_once_across_replay(tmp_path):
    ledger = Ledger(tmp_path/'s.sqlite')
    ledger.start_run('r',{},100,10000)
    assert ledger.charge_once('r','draft','match1/a')
    assert ledger.charge_once('r','draft','match1/a')
    assert not ledger.charge_once('r','draft','match2/a')


def test_campaign_lock_is_exclusive_across_processes_and_released(tmp_path):
    import subprocess
    import sys
    from scripts.arena_config import ROOT
    ledger = Ledger(tmp_path/'s.sqlite')
    program = ('from scripts.arena_ledger import Ledger\nimport sys\n'
               'with Ledger(sys.argv[1]).campaign_lock("campaign"):\n'
               ' print("locked",flush=True)\n sys.stdin.readline()\n')
    with ledger.campaign_lock('campaign'):
        process = subprocess.run([sys.executable,'-c',program,str(ledger.path)],cwd=ROOT,
                                 input='release\n',capture_output=True,text=True,timeout=10)
        assert process.returncode != 0 and 'already active' in process.stderr
    process = subprocess.run([sys.executable,'-c',program,str(ledger.path)],cwd=ROOT,
                             input='release\n',capture_output=True,text=True,timeout=10)
    assert process.returncode == 0 and 'locked' in process.stdout


def test_safe_pre_dispatch_failure_releases_reservation_and_preserves_identity(tmp_path):
    ledger = Ledger(tmp_path/'s.sqlite')
    ledger.start_run('r',{},100,10000)
    ledger.reserve('r','j',80,identity_hash='original')
    ledger.pre_dispatch_failed('r','j','process never started')
    assert ledger.budget('r')['reserved_tokens'] == 0
    with pytest.raises(ValueError,match='identity'):
        ledger.reserve('r','j',80,identity_hash='changed')
    assert ledger.reserve('r','j',80,identity_hash='original')
    ledger.finish('r','j',{'request_hash':'original'},10,1)
    with pytest.raises(ValueError,match='identity'):
        ledger.completed('r','j',identity_hash='changed')
