#!/usr/bin/env python3
"""Codex Arena — torneios verificáveis para produzir playbooks reutilizáveis."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from scripts.arena_config import ROOT, EFFORTS, atomic_json, contained, load_config, read_json


class Parser(argparse.ArgumentParser):
    def error(self,message):
        raise ValueError(message)


def parser():
    common = Parser(add_help=False)
    common.add_argument('--workspace',default=argparse.SUPPRESS,help='Workspace do projeto (padrão: diretório atual)')
    common.add_argument('--config',default=argparse.SUPPRESS,help='Regras JSON completas')
    common.add_argument('--json',action='store_true',default=argparse.SUPPRESS,help='Saída estruturada')
    main = Parser(description=__doc__,parents=[common])
    main.add_argument('--version',action='version',version='codex-arena 1.0.0')
    commands = main.add_subparsers(dest='command',required=True,parser_class=Parser)
    def command(group,name,help): return group.add_parser(name,help=help,parents=[common])
    def budget(p,required=True):
        p.add_argument('--max-tokens',type=int,required=required)
        p.add_argument('--max-ms',type=int,required=required)
    p=command(commands,'install','Instalar ou atualizar no projeto')
    p.add_argument('--source',default=str(ROOT)); p.add_argument('--bootstrap',action='store_true')
    p.add_argument('--download-only',action='store_true'); p.add_argument('--rollback',action='store_true')
    p=command(commands,'doctor','Diagnosticar sem executar inferência'); p.add_argument('--offline',action='store_true')
    command(commands,'models','Consultar catálogo e esforços anunciados')
    p=command(commands,'plan','Estimar confrontos e chamadas sem iniciar')
    p.add_argument('--write-config'); p.add_argument('--train-cases',type=int,default=5)
    p=command(commands,'run','Iniciar campanha com orçamento explícito')
    p.add_argument('--cases',required=True); p.add_argument('--simulate',action='store_true'); p.add_argument('--max-matches',type=int)
    budget(p)
    p=command(commands,'resume','Retomar com os limites totais informados')
    p.add_argument('run_id'); p.add_argument('--max-matches',type=int)
    p.add_argument('--extra-games',type=int,help='Autorizar jogos adicionais para séries inconclusivas, com registro de extensão')
    budget(p)
    for name in ('status','report'):
        p=command(commands,name,'Consultar execução'); p.add_argument('run_id'); p.add_argument('--output')
    p=command(commands,'reconcile','Conciliar recibo local completo de chamada pendente')
    p.add_argument('run_id'); p.add_argument('--job',required=True)
    p=command(commands,'playbook','Gerar, validar e ativar playbooks')
    sub=p.add_subparsers(dest='action',required=True,parser_class=Parser)
    p=command(sub,'build','Destilar campeões ou construir demonstração')
    source=p.add_mutually_exclusive_group(required=True)
    source.add_argument('--from-run'); source.add_argument('--demo',action='store_true')
    p.add_argument('--name',required=True); p.add_argument('--description',default='Métodos derivados de torneio Arena')
    p.add_argument('--playbook-version',default='1.0.0'); p.add_argument('--artifacts'); p.add_argument('--resume-id'); budget(p,False)
    p=command(sub,'validate','Comparar candidato congelado com baseline')
    p.add_argument('name'); p.add_argument('--cases',required=True); p.add_argument('--tier',choices=['all','iron','copper','silver','gold'],default='all')
    p.add_argument('--simulate',action='store_true'); p.add_argument('--resume-id'); budget(p)
    p=command(sub,'activate','Selecionar tier previamente aprovado')
    p.add_argument('name'); p.add_argument('--tier',choices=['iron','copper','silver','gold'],default='gold')
    p.add_argument('--model'); p.add_argument('--effort',choices=EFFORTS)
    for action in ('verify','show'):
        p=command(sub,action,'Verificar conteúdo ou obter instruções ativas'); p.add_argument('name')
    p=command(commands,'plugin','Verificar composição e alterar seleção')
    sub=p.add_subparsers(dest='action',required=True,parser_class=Parser)
    for action in ('check','enable','disable'):
        p=command(sub,action,'Compor plugins verificados'); p.add_argument('name'); p.add_argument('plugins',nargs='*')
        p.add_argument('--review-receipt'); budget(p,False)
    p=command(commands,'memory','Indexação, busca híbrida e grafo locais')
    sub=p.add_subparsers(dest='action',required=True,parser_class=Parser)
    command(sub,'download','Baixar explicitamente o modelo de embeddings')
    p=command(sub,'index','Indexar incrementalmente documentos permitidos')
    p.add_argument('paths',nargs='+'); p.add_argument('--namespace',required=True); p.add_argument('--exclude',action='append',default=[])
    p=command(sub,'search','Recuperar contexto com fontes e limite')
    p.add_argument('query'); p.add_argument('--namespace',required=True); p.add_argument('--topk',type=int); p.add_argument('--context-tokens',type=int)
    p=command(sub,'graph','Consultar links e documentos'); p.add_argument('--namespace')
    p=command(commands,'keys','Rotação e revogação explícitas')
    sub=p.add_subparsers(dest='action',required=True,parser_class=Parser)
    p=command(sub,'rotate','Criar chave local'); p.add_argument('--revoke-previous',action='store_true')
    p=command(sub,'revoke','Revogar chave'); p.add_argument('key_id')
    return main


def dispatch(a):
    workspace=Path(getattr(a,'workspace',Path.cwd())).resolve()
    if a.command=='install':
        from scripts import arena_install as install
        if a.rollback: return install.rollback_install(workspace)
        return install.install_skill(a.source,workspace,bootstrap=a.bootstrap,
                  requirements=Path(a.source).resolve()/'requirements.txt',download_only=a.download_only)
    # Installation and diagnostics must work before third-party dependencies exist.
    if a.command=='doctor':
        config=read_json(getattr(a,'config',None) or ROOT/'assets/default-config.json')
    else:
        config=load_config(getattr(a,'config',None))
    if a.command=='doctor':
        from scripts.arena_doctor import diagnose
        return diagnose(workspace,config,offline=a.offline)
    if a.command=='models':
        from scripts.arena_executor import discover_models
        return discover_models()
    if a.command=='plan':
        from scripts.arena_runner import estimate_plan
        if a.write_config:
            path=Path(a.write_config)
            if path.exists(): raise ValueError('Arquivo já existe; configuração preservada')
            atomic_json(path,config)
        return estimate_plan(config,a.train_cases)
    if a.command=='run':
        from scripts.arena_runner import start_run
        return start_run(workspace,config,read_json(a.cases),max_tokens=a.max_tokens,max_ms=a.max_ms,
                         simulate=a.simulate,max_matches=a.max_matches)
    if a.command=='resume':
        from scripts.arena_runner import resume_run
        return resume_run(workspace,a.run_id,max_tokens=a.max_tokens,max_ms=a.max_ms,max_matches=a.max_matches,extra_games=a.extra_games)
    if a.command in ('status','report'):
        from scripts.arena_reporting import run_report
        result=run_report(workspace,a.run_id,detailed=a.command=='report')
        if a.output: atomic_json(a.output,result)
        return result
    if a.command=='reconcile':
        from scripts.arena_runner import reconcile_job
        return reconcile_job(workspace,a.run_id,a.job)
    if a.command=='playbook':
        from scripts import arena_playbooks as books, arena_workflows as flows
        if a.action=='build':
            if a.demo: return {'bundle':str(flows.build_demo(workspace,a.name)),'simulation':True}
            return flows.build_from_run(workspace,a.from_run,a.name,a.description,a.playbook_version,
                       artifacts=read_json(a.artifacts) if a.artifacts else None,
                       max_tokens=a.max_tokens,max_ms=a.max_ms,resume_id=a.resume_id)
        bundle=contained(workspace,f'.playbooks/{a.name}')
        if a.action=='verify':
            manifest=books.validate_playbook(workspace,bundle)
            return {'verified':True,'bundle':str(bundle),'manifest':manifest}
        if a.action=='validate':
            return flows.validate_bundle(workspace,bundle,read_json(a.cases),config,
                       tiers=None if a.tier=='all' else [a.tier],max_tokens=a.max_tokens,max_ms=a.max_ms,
                       simulate=a.simulate,resume_id=a.resume_id)
        if a.action=='activate':
            from scripts.arena_executor import discover_models,require_pair
            manifest=books.validate_playbook(workspace,bundle)
            pair={'model':a.model or manifest['model_policy'][-1]['model'],
                  'effort':a.effort or manifest['model_policy'][-1]['effort']}
            # Verify evidence first, before a catalog query for an ineligible candidate.
            evidence=books.validation_evidence(workspace,bundle,a.tier)
            if not evidence['passed'] or evidence['simulation']: raise ValueError('Tier sem validação real aprovada')
            require_pair(discover_models(),pair)
            return books.activate(workspace,bundle,a.tier,pair['model'],pair['effort'])
        runtime=books.get_runtime(workspace,bundle)
        tier=bundle/'tier'/runtime['selected_tier']
        return {'runtime':runtime,'readme':str(bundle/'README.md'),'instructions':str(tier/'.agents/_index.md'),
                'scripts':str(tier/'scripts'),'plugins':[str(bundle/'plugins'/n/'main.md') for n in runtime['enabled_plugins']]}
    if a.command=='plugin':
        from scripts import arena_plugins as plugins, arena_playbooks as books, arena_workflows as flows
        bundle=contained(workspace,f'.playbooks/{a.name}')
        if a.action=='check':
            runtime=books.inspect_runtime(workspace,bundle)
            selected=sorted(set(runtime['enabled_plugins'])|set(a.plugins))
            context=plugins.structural_context(workspace,bundle,selected)
            return {'structural_check':'passed','semantic_review_required':bool(selected),'context':context}
        runtime=books.get_runtime(workspace,bundle,check_plugins=False)
        selected=set(runtime['enabled_plugins'])
        selected=selected-set(a.plugins) if a.action=='disable' else selected|set(a.plugins)
        context=plugins.review_context(workspace,bundle,sorted(selected))
        reviewer=None
        if a.max_tokens is not None and a.max_ms is not None:
            reviewer=flows.semantic_reviewer(workspace,config,max_tokens=a.max_tokens,max_ms=a.max_ms)
        return plugins.set_plugins(workspace,bundle,sorted(selected),reviewer,
                     read_json(a.review_receipt) if a.review_receipt else None)
    if a.command=='memory':
        from scripts.arena_memory import MemoryIndex
        memory=MemoryIndex(workspace,model_id=config['memory']['model_id'],model_revision=config['memory']['model_revision'])
        if a.action=='download': return memory.download_model()
        if a.action=='index': return memory.index(a.paths,a.namespace,exclusions=a.exclude)
        if a.action=='graph': return memory.graph(a.namespace)
        return memory.search(a.query,a.namespace,topk=a.topk if a.topk is not None else config['memory']['topk'],
               context_token_budget=a.context_tokens if a.context_tokens is not None else config['memory']['context_token_budget'])
    if a.command=='keys':
        from scripts import arena_signing as signing
        if a.action=='rotate': return {'key_id':signing.rotate_key(workspace,a.revoke_previous)}
        signing.revoke_key(workspace,a.key_id)
        return {'revoked':a.key_id}
    raise ValueError('Unknown command')


def human_output(a,result):
    if a.command=='plan':
        return ('Plano sem inferência\n'
            f"Participantes: {result['entrants']}; pares Battle Royal: {result['battle_matches']}\n"
            f"Jogos Swiss: até {result['swiss_matches_upper_bound']}\n"
            f"Jogos de dupla eliminação sem desempates: {result['double_elimination_games_min']}–{result['double_elimination_games_max_without_tiebreak']}\n"
            f"Chamadas planejadas sem revisões extras: {result['calls_planned_without_extra_reviews']}\n"
            'Informe limites explícitos de tokens e tempo ao iniciar. Use --json para todos os campos.')
    if a.command in ('run','resume','status'):
        budget=result.get('budget',{})
        return (f"Execução: {result['run_id']}\nEstado: {budget.get('status',result.get('status'))}; "
                f"etapa: {result.get('stage','auxiliar')}; confrontos: {result.get('matches',0)}\n"
                f"Simulação: {'sim' if result['simulation'] else 'não'}\n"
                f"Tokens conhecidos: {budget.get('used_tokens',0)}; reservados/pendentes: {budget.get('reserved_tokens',0)}\n"
                f"Tempo acumulado: {budget.get('elapsed_ms',0)} ms\n"
                f"Campeões: {json.dumps(result.get('champions',{}),ensure_ascii=False)}\n"
                'Use report --json para métricas e evidências completas.')
    if a.command=='doctor':
        rows=['Diagnóstico sem inferência; acesso e consumo efetivos exigem execução.']
        for check in result['checks']:
            detail=check['detail']
            if isinstance(detail,dict):
                detail=detail.get('note') or detail.get('version') or detail.get('status') or json.dumps(detail,ensure_ascii=False)
            rows.append(f"[{check['status']}] {check['name']}: {detail}")
        return '\n'.join(rows)
    return json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    structured='--json' in argv
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8')
    try:
        a=parser().parse_args(argv)
        result=dispatch(a)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False) if structured else human_output(a,result))
        return 0
    except (Exception,KeyboardInterrupt) as exc:
        result={'ok':False,'error':str(exc) or 'Interrompido; use status antes de retomar','type':type(exc).__name__}
        if structured: print(json.dumps(result,ensure_ascii=False))
        else: print('Arena: '+result['error'],file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
