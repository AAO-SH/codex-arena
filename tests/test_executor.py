import json
import sys
import pytest
from scripts.arena_executor import parse_events, require_pair, CodexExecutor, ExecutionUncertain


def test_usage_does_not_double_count_cache_or_reasoning():
    events = [
        {'type':'thread.started','thread_id':'t'},
        {'type':'item.completed','item':{'id':'m','type':'agent_message','text':'{"completed":true}'}},
        {'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':80,'output_tokens':20,'reasoning_output_tokens':10}}]
    result = parse_events(events)
    assert result['total_tokens'] == 120
    assert result['payload']['completed'] is True
    assert result['actual_model'] is None


def test_missing_usage_is_not_zero():
    parsed = parse_events([{'type':'turn.completed','usage':{'input_tokens':10}}])
    assert parsed['total_tokens'] is None
    assert parsed['usage']['output_tokens'] is None


def test_unsupported_or_unknown_effort_never_downgrades():
    catalog = {'status':'known','models':[{'model':'gpt-6-luna','efforts':['medium','max']}]}
    require_pair(catalog, {'model':'gpt-6-luna','effort':'max'})
    with pytest.raises(ValueError):
        require_pair(catalog, {'model':'gpt-6-luna','effort':'ultra'})
    with pytest.raises(ValueError):
        require_pair({'status':'unknown','models':[]}, {'model':'gpt-6-luna','effort':'max'})


def test_external_cli_stream_parsed_and_timeout_is_uncertain(tmp_path,monkeypatch):
    # Transport double is not a real sandbox; isolation is covered separately.
    monkeypatch.setattr('scripts.arena_executor.probe_isolation',lambda *a,**k: {'status':'supported'})
    fake = tmp_path / 'fake.py'
    fake.write_text('import json,sys\nif "--help" in sys.argv:\n print("--strict-config --ignore-user-config --ignore-rules"); sys.exit(0)\nprint(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"{\\"ok\\":true}"}}))\nprint(json.dumps({"type":"turn.completed","usage":{"input_tokens":4,"cached_input_tokens":0,"output_tokens":2,"reasoning_output_tokens":0}}))\n')
    executor = CodexExecutor([sys.executable,str(fake)])
    receipt = executor.execute({'prompt':'task','model':'x','effort':'high'}, tmp_path/'work', timeout_ms=3000)
    assert receipt['total_tokens'] == 6
    assert receipt['payload'] == {'ok':True}
    fake.write_text('import time\ntime.sleep(10)\n')
    with pytest.raises(ExecutionUncertain):
        executor.execute({'prompt':'task','model':'x','effort':'high'}, tmp_path/'slow', timeout_ms=100)


def test_missing_executable_is_provably_not_dispatched(tmp_path):
    from scripts import arena_executor as executor
    with pytest.raises(executor.ExecutionNotStarted):
        executor.CodexExecutor([str(tmp_path/'missing-executable')]).execute(
            {'prompt':'task','model':'x','effort':'high'},tmp_path/'work')


def test_isolated_argv_denies_sibling_reads_and_does_not_inherit_user_config(tmp_path):
    from scripts import arena_executor as executor
    directory = tmp_path/'job'
    directory.mkdir()
    argv = executor.build_command(['codex'],{'model':'x','effort':'high'},directory)
    assert '--sandbox' not in argv
    assert '--ignore-rules' not in argv
    assert '--ignore-user-config' in argv and '--strict-config' in argv
    overrides = [argv[i+1] for i,item in enumerate(argv[:-1]) if item == '--config']
    profile = next(v.split('=',1)[1] for v in overrides if v.startswith('permissions.arena_job='))
    import tomllib
    parsed = tomllib.loads('profile='+profile)['profile']
    assert parsed['extends'] == ':workspace'
    assert parsed['filesystem'][':root'] == 'deny'
    assert parsed['filesystem'][':minimal'] == 'read'
    assert parsed['filesystem'][':tmpdir'] == 'deny'
    assert parsed['filesystem'][str(directory.resolve())] == 'write'
    assert parsed['network']['enabled'] is False


def test_ancestor_legacy_sandbox_config_refuses_execution_before_spawn(tmp_path):
    from scripts import arena_executor as executor
    config = tmp_path/'.codex'
    config.mkdir()
    (config/'config.toml').write_text('sandbox_mode="workspace-write"')
    with pytest.raises(executor.ExecutionNotStarted,match='ancestor'):
        executor.build_command(['codex'],{'model':'x','effort':'high'},tmp_path/'job')
