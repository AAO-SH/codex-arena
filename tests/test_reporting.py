from scripts.arena_config import atomic_json
from scripts.arena_ledger import Ledger
from scripts.arena_reporting import run_report


def test_report_unknowns_and_failures_are_not_success_averages(tmp_path):
    run='metrics'
    d=tmp_path/'.scratch/arena'/run
    atomic_json(d/'metadata.json',{'simulation':True})
    atomic_json(d/'config.json',{'price_provenance':{'basis':'api_equivalent_estimate'}})
    ledger=Ledger(tmp_path/'.memory/arena/state.sqlite')
    ledger.start_run(run,{},1000,1000)
    successful={'complete':True,'input_tokens':20,'output_tokens':10,'elapsed_ms':100,'cost_usd':2}
    failed={'complete':False,'input_tokens':40,'output_tokens':10,'elapsed_ms':500,'cost_usd':3}
    empty={'complete':False,'input_tokens':None,'output_tokens':None,'elapsed_ms':None,'cost_usd':None}
    state={'status':'running','stage':'round_robin','round':1,'ids':['a','b'],'records':{},'jobs':{},
           'removed':[],'tiers':{},'qualifiers':{},'champions':{},'series':{},'snapshots':[],
           'administrative':[],'stage_results':{},'stats':{'a':{'points':0},'b':{'points':-10}}}
    for i,(outcome,metric) in enumerate([('W',successful),('F',failed)]):
        mid=str(i)
        state['jobs'][mid]={'a':'a','b':'b'}
        state['records'][mid]={'a':outcome,'b':'F','metrics':{'a':metric,'b':empty}}
    ledger.checkpoint(run,state)
    result=run_report(tmp_path,run)
    a,b=result['competitors']
    assert a['mean_tokens_per_completed']==30
    assert a['total_tokens_all_attempts']==80
    assert a['mean_ms_per_completed']==100
    assert a['cost_per_completed']==5
    assert a['failures_per_completed']==1
    assert b['completed']==0
    assert b['mean_tokens_per_completed'] is None
    assert b['total_tokens_all_attempts'] is None
