---
type: Reference
title: Verificação da entrega
status: stable
---
# Evidências locais — 10 de outubro de 2026

Ambiente: Windows, Python 3.12.2, Codex CLI `0.162.0-alpha.17.2`.

## Testes automatizados

A distribuição com os instaladores npm/PyPI passou com **167 testes em cada uma das seis combinações** de Windows, Linux e macOS com Python 3.11 e 3.12 no [GitHub Actions](https://github.com/AAO-SH/codex-arena/actions/runs/38077264501). A suíte cobre também a inspeção de plugins em candidatos e os bloqueios de ativação. Comandos:

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m compileall -q scripts
.venv/Scripts/python.exe -m pip check
```

A compilação Python, a consistência das dependências e o validador de estrutura de skills do Codex também passaram.

Os testes de empacotamento instalam a distribuição npm, instalam a wheel em um ambiente Python isolado e reconstroem a wheel a partir do sdist. Verificam caminhos com espaços e Unicode, arquivos incluídos, exclusão de dados locais e os comandos de instalação e diagnóstico. O tarball npm também foi executado com `npx` e `--bootstrap` em um workspace descartável: o ambiente foi criado e o CLI instalado retornou o plano de 100 competidores sem inferência. A verificação `twine check --strict` aprovou os metadados da wheel e do sdist.

A skill foi instalada neste workspace em `.agents/skills/codex-arena`, com registro local em `.codex/config.toml`. O comando `plan --json` executado a partir da cópia instalada retornou o planejamento de 100 competidores sem inferência.

| Área | Evidência exercitada |
|---|---|
| Competição | 100 participantes, 4.950 pares únicos em 99 rodadas, corte de 20, quatro tiers, Swiss e quatro campeões; MD10, reset da final, byes e desempates inconclusivos |
| Pontuação | Falha distinta de derrota, falha dupla, zero conclusões, intervalo nulo, preços ausentes e snapshots imutáveis |
| Execução | Orçamentos, reservas, interrupção, retomada, recibos duplicados, resultados incertos, escaladas e combinações de modelo/esforço |
| Instalação | Repetição, atualização, rollback, preservação de configuração, caminhos com espaços/Unicode e execução inicial sem dependências externas |
| Playbooks | Autotestes comportamentais, comparação pareada, rejeição de ativação simulada, assinatura, adulteração, rotação/revogação e conflitos de plugins |
| Conhecimento | OKF 0.2, indexação incremental, exclusões antes do índice, namespaces, grafo e recuperação híbrida |

## Verificações fora do simulador

O catálogo `model/list` respondeu com os modelos GPT disponíveis e os esforços anunciados. Isso confirma a consulta de capacidades, não o acesso efetivo por inferência nem a abrangência da telemetria de consumo.

O FastEmbed/ONNX foi executado localmente com o modelo multilíngue de 384 dimensões. Busca em português, inglês e entre idiomas recuperou as notas esperadas, com `semantic: true` e `sqlite-vec`. Os resultados e o fingerprint do modelo estão em [memória](memory.md).

O playbook demonstrativo `json-contract-demo` contém os quatro tiers, automação JSON funcional e um plugin de exemplo. Seus três autotestes passaram. A avaliação simulada de gold executou cinco casos com três repetições pareadas; o candidato permaneceu reprovado e sua ativação foi corretamente rejeitada. Números simulados não demonstram eficácia de um método.

## Limites desta verificação

**Nenhuma inferência paga nem torneio real foi executado.** O diagnóstico sem inferência retorna `ready: false` neste host: o sandbox Windows disponível recusa a restrição de leitura necessária, com `elevated Windows sandbox requires effective :root read access`. O executor interrompe o fluxo antes de despachar modelos. Os requisitos do backend estão em [execução](execution.md).

Windows, Linux e macOS foram verificados nos runners do GitHub Actions; as verificações de catálogo e embeddings descritas acima ocorreram no host Windows. A validação de comportamento entre variantes foi exercitada com o executor simulado; medir melhoria real exige uma campanha pequena com orçamento explícito, backend compatível e novos casos reservados.
