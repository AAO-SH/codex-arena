---
type: Reference
title: Codex Arena
status: stable
---

<div align="center">
  <h1>Codex Arena</h1>
  <p><strong>Compare métodos para tarefas recorrentes e transforme os vencedores em playbooks executáveis, validados com casos inéditos.</strong></p>
  <a href="https://github.com/AAO-SH/codex-arena"><img alt="Repositório no GitHub" src="https://img.shields.io/badge/GitHub-AAO--SH%2Fcodex--arena-181717?style=for-the-badge&logo=github" /></a>
  <a href="https://github.com/AAO-SH/codex-arena/stargazers"><img alt="Estrelas no GitHub" src="https://img.shields.io/github/stars/AAO-SH/codex-arena?style=for-the-badge&logo=github&color=gold" /></a>
  <a href="https://github.com/AAO-SH/codex-arena/forks"><img alt="Forks no GitHub" src="https://img.shields.io/github/forks/AAO-SH/codex-arena?style=for-the-badge&logo=github" /></a>
  <a href="LICENSE"><img alt="Licença MIT" src="https://img.shields.io/github/license/AAO-SH/codex-arena?style=for-the-badge" /></a>
  <a href="https://github.com/AAO-SH/codex-arena/commits/main"><img alt="Último commit" src="https://img.shields.io/github/last-commit/AAO-SH/codex-arena?style=for-the-badge" /></a>
  <br />
  <img alt="Python 3.11 ou mais recente" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <a href="https://arena.aao.sh"><img alt="Site oficial: arena.aao.sh" src="https://img.shields.io/badge/Site%20oficial-arena.aao.sh-2F5BFF?style=for-the-badge" /></a>
</div>

<hr />

Codex Arena é uma skill de projeto para comparar estratégias, modelos e níveis de esforço em uma família de tarefas. O objetivo é transformar evidências de uma competição em playbooks reutilizáveis, com instruções para o Codex, automações Python e validação em tarefas inéditas.

A instalação, o diagnóstico, a consulta ao catálogo e o planejamento não iniciam inferência. A distribuição requer Python 3.11 ou mais recente. Campanhas reais dependem do Codex CLI, do acesso disponível no ambiente e de um backend de sandbox que aplique o perfil de leitura restrita.

## Instalação

### Pelo prompt

Peça ao Codex para instalar a distribuição pública no projeto atual:

```text
Instale o Codex Arena neste projeto a partir de https://github.com/AAO-SH/codex-arena. Use o instalador do repositório com --bootstrap, configure somente este workspace e execute doctor --json e plan. Não inicie uma campanha durante a instalação.
```

### Manualmente

Use Python 3.11 ou mais recente e clone o repositório:

```bash
git clone https://github.com/AAO-SH/codex-arena.git
cd codex-arena
python --version
```

Instale no workspace de destino, que já deve existir:

```powershell
python scripts/arena.py install --workspace "C:/Projetos/Meu Projeto" --bootstrap
```

O instalador coloca a skill em `.agents/skills/codex-arena`, acrescenta um bloco gerenciado a `.codex/config.toml` e, com `--bootstrap`, cria `.venv` no workspace e instala as dependências de runtime fixadas. Em Linux ou macOS, substitua os caminhos de exemplo pelos do seu projeto. Para desfazer a instalação verificada, use `install --rollback --workspace "C:/Projetos/Meu Projeto"` a partir do repositório.

Depois da instalação, rode os diagnósticos no workspace:

```powershell
.venv/Scripts/python.exe .agents/skills/codex-arena/scripts/arena.py doctor --json
.venv/Scripts/python.exe .agents/skills/codex-arena/scripts/arena.py plan
```

Em Linux ou macOS, use `.venv/bin/python` no lugar de `.venv/Scripts/python.exe`.

## Por que usar

Uma resposta vencedora isolada não mostra se o método funciona de novo. Codex Arena mede uma família de tarefas com regras, testes e evidências registrados; depois compara o candidato a playbook com uma referência em casos inéditos.

- Compare métodos, modelos e esforços usando uma política congelada durante a campanha.
- Separe falhas de execução, derrotas por qualidade e empates; não force um campeão quando a evidência é inconclusiva.
- Gere playbooks com instruções, scripts Python, contratos e tiers: iron, copper, silver e gold.
- Recupere conhecimento do projeto com memória local e busca híbrida, e componha plugins com verificações de compatibilidade.
- Consulte o plano antes de executar e acompanhe reservas, tempo, recibos e resultados pelo CLI.

Use a Arena quando a família de tarefas for recorrente e houver critérios observáveis. Para uma tarefa simples ou única, casos sem rubrica, ou quando não for possível separar dados inéditos para validação, o torneio completo não é apropriado.

## Fluxos principais

O torneio percorre Battle Royal, Swiss e eliminação dupla com séries de dez jogos. A etapa adicional compara o playbook com execução sem playbook, usando casos inéditos.

Para executar os exemplos a partir do clone, prepare também um ambiente Python local nessa pasta:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt -c constraints.txt
```

Nos exemplos abaixo, substitua `python` por `.venv/Scripts/python.exe` no Windows ou `.venv/bin/python` em Linux/macOS. No comando de instalação das dependências acima, Linux/macOS também usa `.venv/bin/python`.

### Experimentar sem inferência

O simulador demonstra a estrutura e os controles do fluxo, mas não mede a qualidade de modelos e não pode aprovar a ativação de um playbook:

```powershell
python scripts/arena.py run --simulate --config examples/rules-smoke.json --cases examples/demo-suite.json --max-tokens 250000 --max-ms 180000
python scripts/arena.py status RUN_ID
python scripts/arena.py report RUN_ID --output relatorio.json
python scripts/arena.py playbook build --demo --name json-contract-demo
python scripts/arena.py playbook verify json-contract-demo
python scripts/arena.py playbook validate json-contract-demo --cases examples/demo-suite.json --tier gold --simulate --max-tokens 100000 --max-ms 120000
```

Os exemplos são públicos e servem para entender os contratos. Eles não são holdouts secretos nem contam como validação inédita. `examples/code-suite.json` mostra o formato de uma família com entregável Python e testes objetivos; o simulador não resolve esses exercícios de código.

### Planejar uma campanha real

1. Copie `assets/default-config.json` e ajuste regras, políticas, critérios e preços. O CLI valida a configuração completa pelo schema.
2. Prepare uma suíte JSON com ao menos cinco casos de competição (`split: train`) e cinco casos reservados (`split: holdout`), conforme `schemas/cases.schema.json`. O comando `run` exige os dois grupos, mas fornece aos competidores somente os casos de competição. Não inclua os holdouts em instruções, plugins, índices ou conhecimento recuperável.
3. Execute `doctor --json` e `models` para verificar o ambiente e as combinações de modelo e esforço anunciadas. Em seguida, use `plan --config regras.json` para estimar confrontos e chamadas antes de iniciar.
4. Inicie com limites explícitos de tokens e tempo: `run --config regras.json --cases suite.json --max-tokens N --max-ms N`. Esses limites são obrigatórios para uma campanha real.
5. Consulte `status` e `report` durante e depois da execução. `resume` exige limites totais novos, não apenas o acréscimo. Se uma chamada puder ter sido despachada sem recibo completo, use `reconcile` antes de decidir o próximo passo.
6. Com uma campanha completa e campeões nos quatro tiers, gere o candidato com `playbook build --from-run RUN_ID --name nome --max-tokens N --max-ms N`. Congele-o e valide-o com `playbook validate nome --cases holdouts.json --tier all --max-tokens N --max-ms N`.
7. Revise a evidência e ative apenas um tier aprovado por validação real, por exemplo `playbook activate nome --tier gold`. Use `playbook show nome` para obter as instruções e os caminhos verificados para consumo.

A validação exige pelo menos cinco casos inéditos e três repetições por caso e variante. Simulação nunca autoriza ativação. O padrão de 100 competidores exige **4.950 confrontos só no Battle Royal**, antes das fases seguintes; dimensione e reduza a campanha após consultar `plan`.

Os limites locais controlam reservas e duração acumulada, mas não garantem o valor final cobrado pelo provedor. Chamadas em andamento podem produzir consumo ainda não recebido. Quando preços de API são usados, o custo é uma estimativa equivalente, não o registro de uma cobrança da conta.

No Windows, o sandbox legado pode não conseguir bloquear leitura na raiz do workspace. Se o backend não aplicar o perfil restrito, o diagnóstico sinaliza a incompatibilidade e a Arena não despacha a inferência. Use um backend que suporte esse perfil, como MXC em um host compatível ou WSL configurado. Consulte [pré-requisitos de execução](references/execution.md).

## Comandos e dados locais

| Comandos | Finalidade |
|---|---|
| `install`, `doctor`, `models`, `plan` | Instalar, diagnosticar, consultar capacidades e estimar uma campanha |
| `run`, `resume`, `status`, `report`, `reconcile` | Executar, acompanhar, retomar e conciliar resultados |
| `playbook build/validate/activate/verify/show` | Gerar, validar, ativar e consultar playbooks |
| `plugin check/enable/disable` | Verificar e alterar combinações de plugins |
| `memory download/index/search/graph` | Preparar embeddings e consultar conhecimento local |
| `keys rotate/revoke` | Gerenciar chaves locais e confiança explicitamente |

Use `python scripts/arena.py --help` e `python scripts/arena.py <comando> --help` para ver opções. Os exemplos acima partem da raiz clonada. Dentro do projeto instalado, use `.venv/Scripts/python.exe .agents/skills/codex-arena/scripts/arena.py <comando>` no Windows ou `.venv/bin/python .agents/skills/codex-arena/scripts/arena.py <comando>` em Linux/macOS.

| Caminho no workspace | Conteúdo |
|---|---|
| `.agents/skills/codex-arena` | Pacote local da skill |
| `.codex/config.toml` | Bloco de configuração gerenciado |
| `.scratch/arena` | Execuções, eventos, debates e candidatos temporários |
| `.memory/arena` | Estado local e índices de conhecimento |
| `.codex/arena` | Chaves, aprovações e cache de embeddings |
| `.playbooks/<nome>` | Playbooks gerados e evidências vinculadas |

## Desenvolvimento e verificação

No ambiente local preparado acima, instale as dependências de desenvolvimento e execute a suíte:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest -q
```

Em Linux/macOS, use `.venv/bin/python`. Os testes usam um executor simulado; não disparam torneios pagos. A CI está configurada para Windows, Linux e macOS, com Python 3.11 e 3.12. Consulte o [relatório de verificação](references/verification.md) para o alcance das evidências e as limitações conhecidas.

## Agradecimentos

Codex Arena adapta o conceito da [Arena original de Jake Schincariol](https://github.com/Jakeschincariol/arena-skill/tree/df07b8e518e10cdecd8cd7712d9958b6f396250e). A atribuição e os termos da licença MIT são mantidos em [`NOTICE.md`](NOTICE.md) e [`LICENSE`](LICENSE).

## Referências

- [Instalação, execução e recuperação](references/execution.md)
- [Competição e contabilidade](references/competition.md)
- [Playbooks, validação e plugins](references/playbooks.md)
- [Memória e recuperação local](references/memory.md)
- [Arquitetura e contratos](references/architecture.md)
- [Verificação da distribuição](references/verification.md)
- [Fontes e decisões de adaptação](references/sources.md)
- [Open Knowledge Format 0.2](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/ad30107c31c06aec8a7d5636e0d1058118604e6f/SPEC.md)

<br />

Desenvolvido e mantido pela comunidade [AAO.sh](https://github.com/AAO-SH). Visite o [site oficial do Codex Arena](https://arena.aao.sh). Distribuído sob a [Licença MIT](LICENSE).
