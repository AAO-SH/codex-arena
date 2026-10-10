---
type: Reference
title: Arquitetura e contratos
---
# Módulos

| Módulo | Responsabilidade |
|---|---|
| `arena.py`, `arena_doctor.py` | Interface estável e diagnóstico |
| `arena_config.py` | Regras completas, validação, caminhos e hashes |
| `arena_install.py` | Instalação portátil transacional |
| `arena_executor.py` | App-server e execução JSONL do Codex |
| `arena_ledger.py` | SQLite, reservas, idempotência e estado |
| `arena_runner.py` | Rascunhos, debates, escaladas e supervisão |
| `arena_tournament.py`, `arena_scoring.py` | Estado puro dos formatos e pontuação |
| `arena_reporting.py` | Métricas por conclusão e tentativas |
| `arena_workflows.py` | Destilação e avaliação pareada |
| `arena_playbooks.py`, `arena_signing.py` | Manifestos, promoção e integridade |
| `arena_plugins.py`, `arena_okf.py` | Composição e validação documental |
| `arena_memory.py` | Documentos, FTS5, vetores e grafo |

## Dados e recuperação

Contratos usam `schema_version: 1`, JSON canônico UTF-8 e números finitos. A configuração completa é congelada por execução. Eventos e reservas ficam no SQLite com transações; artefatos e recibos são endereçados por identidade de trabalho e hashes. `next_matches` avança barreiras/pareamentos; só `record_match` aceita resultados esportivos válidos.

Todo snapshot de rodada usa a mesma matriz de referência. Uma nova rodada não reescreve pontos antigos. O relatório agrega os registros de jogos, não deduz vitórias por modelos ou custos. Casos administrativos não criam telemetria de execução.

## Testar e estender

O backend simulado retorna consumo explicitamente sintético e não constitui evidência real. Testes do motor puro verificam 100 participantes sem milhares de chamadas externas. Testes do CLI verificam instalação/execução/retomada/relatórios, e a validação simulada testa a rejeição de ativação indevida.

Para adaptar outra versão do CLI, acrescente fixtures JSONL reais com valores desconhecidos preservados, atualize o adaptador e teste a cobertura do consumo. Para trocar embeddings, selecione modelo suportado, fixe revisão e reconstrua o índice; não misture espaços vetoriais.

O cache de rascunhos é reutilização de artefato dentro de uma campanha. Não há cache de ataque/defesa/julgamento entre confrontos. O cache de conteúdo do provedor é reportado quando exposto; a skill não promete seu acionamento.
