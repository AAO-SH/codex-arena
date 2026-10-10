"""Read-only capability diagnosis: never claims model access from a catalog."""
import importlib.metadata
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from scripts.arena_config import ROOT


def diagnose(workspace, config, *, offline=False):
    from scripts.arena_executor import discover_models, require_pair, probe_isolation
    checks = []
    def add(name,status,detail):
        checks.append({'name':name,'status':status,'detail':detail})
    add('python','ok' if sys.version_info >= (3,11) else 'error',sys.version.split()[0])
    for line in (ROOT/'requirements.txt').read_text().splitlines():
        if '==' not in line or line.startswith('#'): continue
        name,expected = line.split('==')
        try:
            actual = importlib.metadata.version(name)
            add('dependency:'+name,'ok' if expected==actual else 'warning',{'installed':actual,'pinned':expected})
        except importlib.metadata.PackageNotFoundError:
            add('dependency:'+name,'error','Missing; install requirements in project-local environment')
    cli = shutil.which('codex')
    add('codex','ok' if cli else 'error',cli or 'CLI not found on PATH')
    if cli:
        try:
            version = subprocess.run([cli,'--version'],capture_output=True,text=True,timeout=10)
            help_result = subprocess.run([cli,'exec','--help'],capture_output=True,text=True,timeout=10)
            options = ['--json','--ephemeral','--output-schema','--ignore-user-config','--strict-config']
            missing = [o for o in options if o not in help_result.stdout]
            add('executor_flags','error' if missing else 'ok',{'version':version.stdout.strip(),'missing':missing})
        except (OSError,subprocess.TimeoutExpired) as exc:
            add('executor_flags','error',str(exc))
        if not offline:
            isolation=probe_isolation()
            add('job_read_isolation','ok' if isolation['status']=='supported' else 'error',isolation)
        else:
            add('job_read_isolation','warning','not_checked in offline diagnosis')
    workspace = Path(workspace).resolve()
    local = workspace/'.codex/config.toml'
    try:
        document = tomllib.loads(local.read_text(encoding='utf-8')) if local.exists() else {}
        add('project_config','warning' if 'sandbox_mode' in document else 'ok',
            'Legacy sandbox_mode conflicts with isolated Arena permission profiles' if 'sandbox_mode' in document else 'Valid TOML; global settings unchanged')
    except (ValueError,OSError) as exc:
        add('project_config','error',str(exc))
    # Read only trust metadata, never authentication material.
    global_config = Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'config.toml'
    try:
        global_data = tomllib.loads(global_config.read_text(encoding='utf-8')) if global_config.exists() else {}
        trusts = global_data.get('projects',{})
        trust = next((v.get('trust_level') for p,v in trusts.items() if Path(p).resolve()==workspace),'unknown')
        add('project_trust','ok' if trust=='trusted' else 'warning',trust)
    except (OSError,ValueError):
        add('project_trust','warning','unknown')
    pairs = config['models']['policy']+[config['models']['judge'],config['models']['arbiter']]
    missing_prices = sorted({p['model'] for p in pairs if p['model'] not in config['prices']})
    add('prices','error' if missing_prices else 'ok',{'missing':missing_prices,'provenance':config['price_provenance']})
    catalog = {'status':'not_checked','access_verified':False} if offline else discover_models()
    add('model_catalog','ok' if catalog['status']=='known' else 'warning',catalog)
    if catalog['status']=='known':
        for pair in pairs:
            try:
                require_pair(catalog,pair)
                add(pair['model']+'/'+pair['effort'],'ok','Advertised; access confirmed only by an actual job')
            except ValueError as exc:
                add(pair['model']+'/'+pair['effort'],'error',str(exc))
    add('telemetry','warning',{'status':'unverified_until_job','source':'codex exec --json',
        'ultra_calibrated_models':config['models']['verified_usage_models'],
        'note':'Absent counters stay unknown. Catalog is not proof of complete usage accounting.'})
    return {'ready':not any(c['status']=='error' for c in checks),'checks':checks,
            'inference_performed':False,'platform':sys.platform}
