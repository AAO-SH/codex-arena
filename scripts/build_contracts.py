"""Regenerate distribution schemas and public fixtures without inference."""
from __future__ import annotations
import json
import sys
from pathlib import Path
if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.arena_config import ROOT, EFFORTS, config_schema, load_config


def object_schema(properties,required=None):
    return {'type':'object','properties':properties,'required':list(properties) if required is None else required,'additionalProperties':False}


def contracts():
    string={'type':'string','minLength':1}
    nullable={'type':['number','null'],'minimum':0}
    pair=object_schema({'model':string,'effort':{'enum':list(EFFORTS)}})
    case=object_schema({'id':string,'split':{'enum':['train','holdout']},'prompt':string,
        'completion':object_schema({'required_files':{'type':'array','items':string},
            'checks':{'type':'array','items':{'type':'array','minItems':1,'items':string}}},[]),
        'reference_answer':{},'reference_answers':{},'context':{'type':'string'},
        'input':{},'inputs':{}},['id','split','prompt'])
    schemas={
        'config':config_schema(),
        'cases':object_schema({'schema_version':{'const':1},'family':string,'cases':{'type':'array','minItems':1,'items':case}}),
        'competitor':object_schema({'id':string,'card':object_schema({'reasoning':string,'workflow':string,'strategy':string}),
            'policy':{'type':'array','minItems':1,'maxItems':3,'items':pair}}),
        'job':object_schema({'id':string,'a':string,'b':string,
            'stage':{'enum':['round_robin','swiss','double_elimination']},
            'tier':{'type':['string','null']},'round':{'type':'integer','minimum':1},
            'game':{'type':'integer','minimum':1},'series':{'type':['string','null']},
            'bracket':{'type':['string','null']}},['id','a','b','stage','round']),
        'metrics':object_schema({**{k:nullable for k in ('input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens','elapsed_ms','cost_usd')},
            'complete':{'type':'boolean'},'usage_verified':{'type':'boolean'}},['complete','elapsed_ms','cost_usd']),
        'deliverable':object_schema({'completed':{'type':'boolean'},'answer':{'type':'string'},
            'files':{'type':'array','items':object_schema({'path':string,'content':{'type':'string'}})},
            'lessons':{'type':'array','items':{'type':'string'}}}),
    }
    for name,schema in schemas.items():
        schema.update({'$schema':'https://json-schema.org/draft/2020-12/schema',
                       '$id':f'urn:codex-arena:{name}:1','title':f'Codex Arena {name} v1'})
    return schemas


def main():
    def write(path,data):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for name,schema in contracts().items(): write(ROOT/'schemas'/f'{name}.schema.json',schema)
    config=load_config()
    config['tournament'].update(entrants=8,cut=0,qualifiers=2,swiss_rounds=2)
    write(ROOT/'examples/rules-smoke.json',config)
    prompts=[
        'Descreva um método verificável para detectar campos ausentes em um objeto JSON de cadastro.',
        'Planeje a normalização de datas ISO em registros JSON sem perder o valor original.',
        'Explique como identificar chaves duplicadas antes de consumir um documento JSON.',
        'Defina uma validação de tipos para um catálogo JSON com preço e quantidade.',
        'Proponha um relatório de erros por linha para uma importação JSONL.',
        'Planeje validar coordenadas geográficas em JSON, com exemplos de casos limite.',
        'Descreva como distinguir nulo, ausente e texto vazio em dados JSON de contatos.',
        'Crie um procedimento para identificar identificadores repetidos em uma coleção JSON.',
        'Defina verificações para intervalos de tempo em registros JSON de agenda.',
        'Explique como validar relações entre objetos JSON com referências por identificador.',
    ]
    suite={'schema_version':1,'family':'PUBLIC-DEMO-json-contracts','cases':[
        {'id':f'demo-{i+1:02d}','split':'train' if i<5 else 'holdout','prompt':p,
         'completion':{'required_files':[],'checks':[]}} for i,p in enumerate(prompts)]}
    write(ROOT/'examples/demo-suite.json',suite)
    samples=[{'name':' Ana ','email':' A@EXAMPLE.COM ','age':'31'},
             {'name':'李 明','email':'M@EXAMPLE.COM','age':0},
             {'name':' Bia ','age':'22','extra':{'a':1}},
             {'name':'','email':' X@Y.BR ','age':99},
             {'name':'João','email':None,'age':None},
             {'name':'  Érica  ','email':'e@EXAMPLE.COM','age':'42'},
             {'email':'  Z@TEST.BR  ','age':'18'},
             {'name':None,'email':None,'note':'preserve'},
             {'name':'  Alice Smith  ','email':'A@HOST.TLD','age':1,'score':0},
             {'name':'Omar','email':'  o@host.tld','age':'120','tags':['x']}]
    code_cases=[]
    for i,sample in enumerate(samples):
        expected=dict(sample)
        if isinstance(expected.get('name'),str): expected['name']=expected['name'].strip()
        if isinstance(expected.get('email'),str): expected['email']=expected['email'].strip().casefold()
        if isinstance(expected.get('age'),str): expected['age']=int(expected['age'])
        check=("import copy,json; from solution import normalize; "
               f"x=json.loads({json.dumps(json.dumps(sample,ensure_ascii=False),ensure_ascii=False)}); "
               f"expected=json.loads({json.dumps(json.dumps(expected,ensure_ascii=False),ensure_ascii=False)}); "
               "original=copy.deepcopy(x); assert normalize(x)==expected; assert x==original")
        prompt=('Crie solution.py com normalize(record: dict) -> dict sem mutar a entrada. '
                'Preserve chaves desconhecidas. Remova espaços das pontas de name e email quando strings; '
                'aplique casefold no email. Converta age de texto numérico não negativo para inteiro; '
                'preserve null e campos ausentes. Entregue código Python e explique seus limites. '
                'Exemplo de entrada desta tarefa: '+json.dumps(sample,ensure_ascii=False))
        code_cases.append({'id':f'code-{i+1:02d}','split':'train' if i<5 else 'holdout','prompt':prompt,
                           'completion':{'required_files':['solution.py'],'checks':[['{python}','-c',check]]}})
    write(ROOT/'examples/code-suite.json',{'schema_version':1,'family':'PUBLIC-EXAMPLE-json-normalization','cases':code_cases})
    # Deliberately no invented calibration measurements.
    write(ROOT/'examples/original-calibration.json',{'profile':'original','original':{
        'min':{'model':'gpt-5.6-luna','effort':'low','throughput':None,'price_per_1m':None},
        'max':{'model':'gpt-6-astra','effort':'ultra','throughput':None,'price_per_1m':None}}})
    print('Schemas v1 and public fixtures written. Calibration nulls require measured values.')


if __name__=='__main__': main()
