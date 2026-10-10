---
type: Reference
title: Fontes e decisões de adaptação
---
# Fontes fixadas

- [Arena original](https://github.com/Jakeschincariol/arena-skill/tree/df07b8e518e10cdecd8cd7712d9958b6f396250e), revisão `df07b8e518e10cdecd8cd7712d9958b6f396250e`, MIT.
- [OKF 0.2 canônico](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/ad30107c31c06aec8a7d5636e0d1058118604e6f/SPEC.md), revisão `ad30107c31c06aec8a7d5636e0d1058118604e6f`.
- [Skills Codex](https://learn.chatgpt.com/docs/build-skills), [execução não interativa](https://learn.chatgpt.com/docs/non-interactive-mode), [configuração](https://learn.chatgpt.com/docs/config-file/config-reference), [permissões](https://learn.chatgpt.com/docs/permissions): contratos consultados em 2026-10-10 e verificados contra `codex --help`, `exec --help` e `model/list` locais.
- [Catálogo de modelos e preços](https://developers.openai.com/api/docs/models/compare): valores são uma fotografia, com origem e data no JSON. Não equivalem à cobrança de uma assinatura ChatGPT.
- [Modelos FastEmbed](https://qdrant.github.io/fastembed/examples/Supported_Models/): `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, vetores de 384 dimensões. Artefatos baixados são identificados por SHA-256 no índice.

# O que mudou

A Arena original resolve uma tarefa e busca uma entrega vencedora. Suas cartas diversificam métodos e seus debates ajudam a expor defeitos. Isso foi preservado como princípio, sem depender das ferramentas e nomes de agentes do Claude Code.

Codex Arena organiza competição por família, separa falha de derrota e custo de qualidade, reinicia pontos entre formatos e trata séries inconclusivas sem forçar campeão. Seu produto é uma estratégia executável validada em casos novos. A arquitetura utiliza contratos Python, SQLite, envelopes assinados e recuperação seletiva; não confia apenas em estado descrito no prompt.

O perfil padrão corrige dois problemas do índice original: maior geração de tokens não implica melhor conclusão, e throughput multiplicado por preço não mede gasto por tarefa. As fórmulas originais permanecem como opção calibrada e rotulada separadamente.
