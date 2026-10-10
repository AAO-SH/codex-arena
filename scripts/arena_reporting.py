"""Read-only reports over immutable game records and execution receipts."""
from pathlib import Path
from scripts.arena_config import contained, read_json
from scripts.arena_ledger import Ledger


def run_report(workspace, run_id, detailed=True):
    from scripts.arena_tournament import report
    workspace = Path(workspace).resolve()
    directory = contained(workspace, f'.scratch/arena/{run_id}')
    ledger = Ledger(workspace/'.memory/arena/state.sqlite')
    state = ledger.load_state(run_id)
    metadata = read_json(directory/'metadata.json')
    result = report(state) if isinstance(state,dict) and 'records' in state else dict(state or {})
    result.update(run_id=run_id,simulation=metadata['simulation'],budget=ledger.budget(run_id),
                  usage_by_role=ledger.usage_summary(run_id),artifact_checks=ledger.check_summary(run_id))
    pause = directory/'pause.json'
    if pause.is_file():
        result['last_pause'] = read_json(pause)
    result['unresolved_jobs'] = [{k:j.get(k) for k in ('id','status','reason','reservation')}
                               for j in ledger.list_jobs(run_id) if j['status'] != 'complete']
    if not detailed or not state or 'records' not in state:
        return result
    entries = {cid:{'id':cid,'wins':0,'losses':0,'failures':0,'ties':0,'metrics':[]} for cid in state['ids']}
    for mid, record in state['records'].items():
        job = state['jobs'][mid]
        for side in ('a','b'):
            entry = entries[job[side]]
            entry[{'W':'wins','L':'losses','F':'failures','T':'ties'}[record[side]]] += 1
            entry['metrics'].append(record['metrics'][job[side]])
    def total(metrics,key):
        return sum(m[key] for m in metrics) if all(m.get(key) is not None for m in metrics) else None
    for entry in entries.values():
        metrics = entry.pop('metrics')
        done = [m for m in metrics if m['complete']]
        def tokens(items):
            a,b = total(items,'input_tokens'),total(items,'output_tokens')
            return None if a is None or b is None else a+b
        count = len(done)
        entry.update(completed=count,task_episodes=len(metrics),total_tokens_all_attempts=tokens(metrics),
                     total_cost_usd=total(metrics,'cost_usd'),
                     mean_tokens_per_completed=None if not count or tokens(done) is None else tokens(done)/count,
                     mean_ms_per_completed=None if not count or total(done,'elapsed_ms') is None else total(done,'elapsed_ms')/count,
                     cost_per_completed=None if not count or total(metrics,'cost_usd') is None else total(metrics,'cost_usd')/count)
        for field in ('wins','losses','failures'):
            entry[field+'_per_completed'] = entry[field]/count if count else None
    result['competitors'] = list(entries.values())
    result['stage_results'] = {stage:{cid:{k:v for k,v in stats.items() if k not in ('metrics','opponents')}
                                    for cid,stats in rows.items()} for stage,rows in state['stage_results'].items()}
    result['current_stage_points'] = {cid:s['points'] for cid,s in state['stats'].items()}
    result['amendments'] = state.get('amendments',[])
    result['cost_basis'] = read_json(directory/'config.json')['price_provenance']['basis']
    return result
