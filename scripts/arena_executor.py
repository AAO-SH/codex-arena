"""Codex CLI adapter. Catalog discovery never performs inference."""
from __future__ import annotations

import json
import os
import queue
import shutil
import signal
import sys
import subprocess
import tempfile
import threading
import time
from pathlib import Path
import tomllib
from scripts.arena_config import atomic_json, canonical


class ExecutionUncertain(RuntimeError):
    """The child may have consumed tokens; do not retry without reconciliation."""


class ExecutionNotStarted(RuntimeError):
    """Proven pre-dispatch failure. Only explicitly transient failures may retry."""
    def __init__(self, message, *, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def isolated_config_args(directory, *, sandbox='workspace-write'):
    """Build a fail-closed profile restricted to the exact attempt directory.

    Preserve CODEX_HOME for authentication, but ignore user configuration,
    external skills, plugins, MCP connections, hooks, browser and delegation.
    Legacy --sandbox is deliberately absent because it overrides the profile.
    """
    directory = Path(directory).resolve()
    if sandbox not in ('read-only', 'workspace-write'):
        raise ExecutionNotStarted('Unsupported job sandbox; broad access is forbidden')
    def legacy(value):
        return isinstance(value, dict) and ('sandbox_mode' in value or any(legacy(v) for v in value.values()))
    for ancestor in (directory, *directory.parents):
        path = ancestor/'.codex/config.toml'
        user_config = Path(os.environ.get('CODEX_HOME', Path.home()/'.codex'))/'config.toml'
        if path == user_config.resolve():
            continue  # exec explicitly suppresses this source; sandbox -P selects its profile.
        if path.exists():
            try:
                settings = tomllib.loads(path.read_text(encoding='utf-8-sig'))
            except (OSError, tomllib.TOMLDecodeError) as exc:
                raise ExecutionNotStarted(f'Cannot verify ancestor config {path}: {exc}') from exc
            if legacy(settings):
                raise ExecutionNotStarted(f'Legacy sandbox_mode in ancestor config {path} would override job isolation')
    profile = {'extends': ':workspace', 'filesystem': {':root':'deny', ':minimal':'read',
                ':tmpdir':'deny', ':slash_tmp':'deny', str(directory):'read' if sandbox == 'read-only' else 'write'},
               'network': {'enabled':False}}
    def inline(value):
        if isinstance(value, dict):
            return '{' + ','.join(json.dumps(k)+'='+inline(v) for k,v in value.items()) + '}'
        if isinstance(value, bool):
            return 'true' if value else 'false'
        return json.dumps(value)
    features = {'multi_agent':False,'multi_agent_v2':False,'apps':False,'plugins':False,
                'hooks':False,'browser_use':False,'browser_use_external':False,'computer_use':False,
                'in_app_browser':False,'skill_search':False,'skip_host_skill_discovery':True}
    command = []
    for key,value in {'default_permissions':'arena_job',
                      'permissions.arena_job':profile,'features':features,'mcp_servers':{},
                      'web_search':'disabled','project_doc_max_bytes':0,'approval_policy':'never'}.items():
        command += ['--config',key+'='+inline(value)]
    return command


def build_command(executable, request, directory, *, sandbox='workspace-write'):
    if not isinstance(request.get('model'), str) or not request['model'] or request.get('effort') not in ('low','medium','high','xhigh','max','ultra'):
        raise ExecutionNotStarted('Invalid requested model/effort')
    directory = Path(directory).resolve()
    command = list(executable) + ['exec','--json','--ephemeral','--skip-git-repo-check',
              '--ignore-user-config','--strict-config','--model',request['model'],
              '--config','model_reasoning_effort='+json.dumps(request['effort'])]
    command += isolated_config_args(directory,sandbox=sandbox) + ['--cd',str(directory)]
    if request.get('schema'):
        command += ['--output-schema',str(directory/'response.schema.json')]
    return command + ['-']


def probe_isolation(directory=None, command=None, *, timeout_ms=15000):
    """Run a harmless filesystem canary through Codex sandbox, never inference.

    Fail closed unless the configured runtime can read its own root and rejects
    a known existing sibling file. Native Windows backends that require broad
    root reads return unsupported; no relaxed-profile fallback is permitted.
    """
    base = Path(directory or Path.cwd()/'.scratch/isolation-probes').resolve()
    base.mkdir(parents=True,exist_ok=True)
    executable = command or [shutil.which('codex') or 'codex']
    try:
        with tempfile.TemporaryDirectory(prefix='arena-probe-',dir=base) as temporary:
            parent = Path(temporary)
            own = parent/'job'
            own.mkdir()
            (own/'inside.txt').write_text('inside',encoding='utf-8')
            outside = parent/'outside.txt'
            outside.write_text('outside-secret',encoding='utf-8')
            script = own/'probe.py'
            script.write_text('import json\nfrom pathlib import Path\n'
                'inside=Path(__file__).with_name("inside.txt").read_text()=="inside"\n'
                f'outside=Path({str(outside)!r})\n'
                'try:\n outside.read_text(); denied=False\n'
                'except OSError:\n denied=True\n'
                'print(json.dumps({"inside_read":inside,"outside_denied":denied}))\n',encoding='utf-8')
            python = str(Path(sys.base_prefix)/'python.exe') if os.name == 'nt' else sys.executable
            args = list(executable)+['sandbox','-P','arena_job','--cd',str(own)]
            args += isolated_config_args(own)+['--',python,'-I',str(script)]
            completed = subprocess.run(args,cwd=own,capture_output=True,text=True,encoding='utf-8',errors='replace',
                                       timeout=timeout_ms/1000,**_spawn_options())
            data = None
            for line in reversed(completed.stdout.splitlines()):
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                break
            if completed.returncode == 0 and isinstance(data,dict) and data.get('inside_read') is True and data.get('outside_denied') is True:
                return {'status':'supported','inference':False,**data}
            return {'status':'unsupported','inference':False,
                    'error':(completed.stderr or completed.stdout or 'Filesystem canary did not prove isolation')[-4000:]}
    except (OSError,subprocess.TimeoutExpired,ExecutionNotStarted) as exc:
        return {'status':'unsupported','inference':False,'error':str(exc)}


def _spawn_options():
    if os.name == 'nt':
        return {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {'start_new_session': True}


def _stop(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                       capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _reader(stream, sink):
    try:
        for line in stream:
            sink.put(line)
    finally:
        sink.put(None)


def discover_models(command=None, timeout_ms=15000) -> dict:
    executable = command or [shutil.which('codex') or 'codex']
    process = None
    try:
        process = subprocess.Popen(executable + ['app-server','--listen','stdio://'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', errors='replace', **_spawn_options())
        lines = queue.Queue()
        threading.Thread(target=_reader,args=(process.stdout,lines),daemon=True).start()
        deadline = time.monotonic() + timeout_ms / 1000
        def send(message):
            process.stdin.write(json.dumps(message) + '\n')
            process.stdin.flush()
        def receive(identifier):
            while time.monotonic() < deadline:
                line = lines.get(timeout=max(.01,deadline-time.monotonic()))
                if line is None:
                    raise RuntimeError('app-server closed before returning catalog')
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get('id') == identifier:
                    if 'error' in event:
                        raise RuntimeError(str(event['error']))
                    return event['result']
            raise RuntimeError('model/list timed out')
        send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'codex_arena','version':'1.0.0'}}})
        receive(1)
        send({'method':'initialized','params':{}})
        models, cursor, page = [], None, 2
        seen_cursors = set()
        while True:
            send({'id':page,'method':'model/list','params':{'cursor':cursor} if cursor else {}})
            response = receive(page)
            entries = response.get('data', response.get('models'))
            if not isinstance(entries,list):
                raise RuntimeError('Unrecognized model/list schema')
            for entry in entries:
                model = entry.get('model') or entry.get('id') or entry.get('slug')
                levels = entry.get('supportedReasoningEfforts', [])
                efforts = [v.get('reasoningEffort',v.get('effort')) if isinstance(v,dict) else v for v in levels]
                if not model or not efforts or any(not isinstance(x,str) for x in efforts):
                    raise RuntimeError('Incomplete capability entry')
                models.append({'model':model,'efforts':efforts,
                               'default_effort':entry.get('defaultReasoningEffort')})
            cursor = response.get('nextCursor')
            if not cursor:
                break
            if cursor in seen_cursors or page > 100:
                raise RuntimeError('Invalid catalog pagination')
            seen_cursors.add(cursor)
            page += 1
        return {'status':'known','models':models,'source':'codex app-server model/list',
                'access_verified':False,'observed_at':time.time()}
    except (OSError, RuntimeError, ValueError, queue.Empty) as exc:
        return {'status':'unknown','models':[],'error':str(exc),'access_verified':False}
    finally:
        if process:
            _stop(process)


def require_pair(catalog: dict, pair: dict):
    if catalog.get('status') != 'known':
        raise ValueError('Model capabilities unknown; run doctor/models before paid execution')
    entry = next((m for m in catalog.get('models',[]) if m['model'] == pair['model']),None)
    if entry is None or pair['effort'] not in entry['efforts']:
        raise ValueError(f'Unsupported pair {pair["model"]}/{pair["effort"]}; no automatic substitution')


def parse_events(events: list[dict]) -> dict:
    fields = ('input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens')
    totals = {name:0 for name in fields}
    usage_seen = False
    message, actual_model, actual_effort, thread_id = None,None,None,None
    completed, failed, tools = False,False,[]
    for event in events:
        kind = event.get('type')
        if kind == 'thread.started':
            thread_id = event.get('thread_id')
        if event.get('model'):
            actual_model = event['model']
        if event.get('reasoning_effort'):
            actual_effort = event['reasoning_effort']
        if kind == 'turn.completed':
            completed, usage_seen = True,True
            usage = event.get('usage') or {}
            for name in fields:
                value = usage.get(name)
                if totals[name] is None or not isinstance(value,int) or isinstance(value,bool) or value < 0:
                    totals[name] = None
                else:
                    totals[name] += value
        elif kind in ('turn.failed','error'):
            failed = True
        if kind == 'item.completed':
            item = event.get('item',{})
            if item.get('type') == 'agent_message':
                message = item.get('text')
            elif item.get('type') in ('command_execution','mcp_tool_call','web_search','file_change','collab_tool_call'):
                tools.append({'id':item.get('id'),'type':item.get('type'),'status':item.get('status')})
    if not usage_seen:
        totals = dict.fromkeys(fields)
    if totals['input_tokens'] is not None and totals['cached_input_tokens'] is not None and totals['cached_input_tokens'] > totals['input_tokens']:
        raise ValueError('Cached tokens cannot exceed input tokens')
    if totals['output_tokens'] is not None and totals['reasoning_output_tokens'] is not None and totals['reasoning_output_tokens'] > totals['output_tokens']:
        raise ValueError('Reasoning tokens cannot exceed output tokens')
    payload = None
    if message:
        try:
            payload = json.loads(message)
        except (json.JSONDecodeError,TypeError):
            pass
    total = None if totals['input_tokens'] is None or totals['output_tokens'] is None else totals['input_tokens'] + totals['output_tokens']
    return {'payload':payload,'text':message,'usage':totals,'total_tokens':total,
            'turn_completed':completed,'turn_failed':failed,'thread_id':thread_id,
            'actual_model':actual_model,'actual_effort':actual_effort,'tools':tools}


class CodexExecutor:
    def __init__(self, command=None):
        self.command = command or [shutil.which('codex') or 'codex']
        self._capabilities_checked = False
        self._capability_lock = threading.Lock()

    def _check_capabilities(self, directory):
        with self._capability_lock:
            if self._capabilities_checked:
                return
            try:
                result = subprocess.run(self.command+['exec','--help'],capture_output=True,text=True,
                                        encoding='utf-8',errors='replace',timeout=15,**_spawn_options())
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ExecutionNotStarted(f'CLI capability preflight failed: {exc}',
                    retryable=isinstance(exc, OSError) and not isinstance(exc,(FileNotFoundError,PermissionError))) from exc
            if result.returncode or any(flag not in result.stdout for flag in ('--strict-config','--ignore-user-config')):
                raise ExecutionNotStarted('CLI does not advertise required fail-closed isolation/config flags')
            probe = probe_isolation(directory,command=self.command)
            if probe['status'] != 'supported':
                raise ExecutionNotStarted('Strict job isolation preflight failed: '+probe.get('error','unknown sandbox capability'))
            self._capabilities_checked = True

    def prepare(self, request, directory, *, sandbox='workspace-write'):
        """Verify command/profile and sandbox enforcement before reservation."""
        build_command(self.command,request,directory,sandbox=sandbox)
        self._check_capabilities(directory)

    def execute(self, request: dict, directory: Path | str, *, timeout_ms=900000,
                max_output_chars=120000, sandbox='workspace-write', trusted_receipt_path=None) -> dict:
        directory = Path(directory).resolve()
        start = time.monotonic_ns()
        events, size, process, result, code = [],0,None,None,None
        try:
            if type(timeout_ms) is not int or timeout_ms <= 0 or type(max_output_chars) is not int or max_output_chars <= 0:
                raise ExecutionNotStarted('Execution timeout and output bounds must be positive integers')
            command = build_command(self.command,request,directory,sandbox=sandbox)
            self._check_capabilities(directory)
            directory.mkdir(parents=True,exist_ok=True)
            if request.get('schema'):
                atomic_json(directory/'response.schema.json',request['schema'])
            atomic_json(directory/'request.json',{k:v for k,v in request.items() if k != 'prompt'})
            (directory/'prompt.txt').write_text(request['prompt'],encoding='utf-8')
            with (directory/'stderr.log').open('w',encoding='utf-8') as errors, (directory/'events.jsonl').open('w',encoding='utf-8') as journal:
                process = subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,
                    text=True,encoding='utf-8',errors='replace',cwd=directory,**_spawn_options())
                lines = queue.Queue()
                threading.Thread(target=_reader,args=(process.stdout,lines),daemon=True).start()
                process.stdin.write(request['prompt'])
                process.stdin.close()
                deadline = time.monotonic()+timeout_ms/1000
                while True:
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        raise ExecutionUncertain('CLI timeout after dispatch')
                    try:
                        line = lines.get(timeout=min(remaining,.25))
                    except queue.Empty:
                        continue
                    if line is None:
                        break
                    size += len(line)
                    journal.write(line)
                    journal.flush()
                    if size > max_output_chars:
                        raise ExecutionUncertain('Event output limit exceeded after dispatch')
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        raise ExecutionUncertain('Malformed CLI JSONL event') from exc
                code = process.wait(timeout=max(.01,deadline-time.monotonic()))
            result = parse_events(events)
            result.update({'elapsed_ms':(time.monotonic_ns()-start)//1_000_000,
                           'requested_model':request['model'],'requested_effort':request['effort'],
                           'returncode':code,'mode':'live'})
            result['request_hash'] = request.get('request_hash')
            if code != 0 or result['turn_failed'] or not result['turn_completed'] or result['total_tokens'] is None:
                raise ExecutionUncertain('CLI did not report a settled turn and complete token usage')
            if result['actual_model'] is not None and result['actual_model'] != request['model']:
                raise ExecutionUncertain('Runtime model differs from requested model')
            if result['actual_effort'] is not None and result['actual_effort'] != request['effort']:
                raise ExecutionUncertain('Runtime reasoning effort differs from requested effort')
            return result
        except ExecutionNotStarted:
            raise
        except ExecutionUncertain:
            raise
        except subprocess.TimeoutExpired as exc:
            if process is None:
                raise ExecutionNotStarted('CLI preflight did not settle before deadline') from exc
            raise ExecutionUncertain('CLI process did not settle before deadline') from exc
        except Exception as exc:
            if process is None:
                raise ExecutionNotStarted(f'Execution failed before dispatch: {exc}',
                    retryable=isinstance(exc,OSError) and not isinstance(exc,(FileNotFoundError,PermissionError))) from exc
            raise ExecutionUncertain(f'Execution failed after dispatch: {exc}') from exc
        finally:
            if process:
                _stop(process)
                # Persist host-observed counters after the child has stopped.
                # A trusted path outside the writable job root resists child edits.
                if result is None:
                    try:
                        result = parse_events(events)
                    except Exception as exc:
                        result = {'parse_error':str(exc),'total_tokens':None}
                result.update({'elapsed_ms':(time.monotonic_ns()-start)//1_000_000,
                               'requested_model':request['model'],'requested_effort':request['effort'],
                               'request_hash':request.get('request_hash'),'returncode':code,'mode':'live'})
                atomic_json(directory/'receipt.json',result)
                if trusted_receipt_path is not None:
                    atomic_json(trusted_receipt_path,result)
