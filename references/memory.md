# Memória local

O Arena mantém a memória no workspace. O banco padrão é `.memory/arena/knowledge.sqlite`; o ledger de execuções continua em `.memory/arena/state.sqlite`. O modelo ONNX fica em `.codex/arena/models`. Esses caminhos são locais ao projeto e não usam o banco de estado do usuário.

## Comandos

O primeiro comando baixa explicitamente o modelo. Ele precisa de rede e não chama um modelo de linguagem:

```powershell
python scripts/arena.py memory download --workspace .
```

Depois do download, indexação, busca e grafo executam com o modelo local. Informe sempre os caminhos que deseja indexar e um namespace:

```powershell
python scripts/arena.py memory index .docs .playbooks --namespace experimento --workspace .
python scripts/arena.py memory index .docs --namespace experimento --exclude .docs/holdout --workspace .
python scripts/arena.py memory search "como validar um playbook" --namespace experimento --topk 8 --context-tokens 3000 --workspace .
python scripts/arena.py memory graph --namespace experimento --workspace .
```

O mesmo fluxo está disponível na API Python:

```python
from pathlib import Path
from scripts.arena_memory import MemoryIndex

workspace = Path.cwd()
memory = MemoryIndex(workspace)
memory.download_model()  # ação explícita; requer rede somente para baixar o ONNX
memory.index([".docs", ".playbooks"], namespace="experimento", exclusions=[".docs/holdout"])
results = memory.search("como validar um playbook", "experimento", topk=8, context_token_budget=3000)
graph = memory.graph("experimento")
```

`MemoryIndex` também aceita `db_path`, um `embedding_backend` injetado para testes e os parâmetros `chunk_size_tokens` e `chunk_overlap_tokens`. Os tamanhos padrão são 96 e 12 tokens. A janela não pode ultrapassar o limite informado pelo tokenizer do modelo; textos maiores são repartidos antes da inferência, sem truncamento silencioso. A busca soma tokens de chunks inteiros e deixa de fora um chunk que não caiba no orçamento.

## Corpus, isolamento e atualização

Somente arquivos Markdown dentro de `.docs`, `.playbooks` e `.memory` podem entrar no índice. A chamada precisa indicar o arquivo ou a pasta; não há varredura implícita do workspace. O frontmatter `type` é obrigatório, salvo para `index.md` e `log.md`. Tipos `private`, `secret` e `holdout`, caminhos com `scratch` ou `holdout`, exclusões explícitas, links simbólicos, junctions e caminhos que escapem do workspace são rejeitados antes da leitura do conteúdo ou da atualização do FTS. Reindexar uma pasta com uma nova exclusão remove os chunks antigos daquele arquivo do FTS e dos vetores.

O namespace é obrigatório para indexação e busca. FTS e busca vetorial são filtrados por namespace; a busca combina os rankings com reciprocal rank fusion. `sqlite-vec` faz a busca vetorial quando a extensão está disponível. Sem ela, o Arena calcula cosseno com NumPy e mantém o filtro de namespace antes da ordenação. O grafo resolve wikilinks do Obsidian e links Markdown relativos dentro do namespace.

Arquivos inalterados, identificados por SHA-256 do Markdown, não são re-embutidos. Arquivos removidos do escopo são retirados do namespace. Uma mudança de modelo, revisão, dimensões ou fingerprint dos arquivos locais provoca reconstrução do namespace.

## Modelo, proveniência e limites

O modelo padrão é `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, executado pelo FastEmbed/ONNX em 384 dimensões. O comando de download é a única operação deste módulo que busca o modelo. Indexação e busca normais só carregam os arquivos já presentes no cache e falham com instrução para baixar se eles faltarem ou se o fingerprint não corresponder; elas não usam fallback de embeddings falsos. Backends determinísticos injetados nos testes são marcados como `semantic: false`.

Cada namespace registra JSON de proveniência no banco, incluindo horário, modo semântico, mecanismo vetorial, janela de chunks e identificador, revisão, dimensões e SHA-256 dos artefatos do modelo. Resultados incluem essa proveniência e, por chunk, o caminho relativo, título/seção, offsets de caracteres no Markdown, hash do documento e revisão/fingerprint usados. O fingerprint resume os arquivos existentes em `.codex/arena/models`; ele detecta mudanças locais, mas não prova a origem do arquivo nem substitui uma assinatura de fornecedor.

O Arena não faz inferência de LLM nem envia documentos, consultas ou embeddings para uma API remota. O modo sem rede exige que o modelo já tenha sido baixado. O corpus escolhido continua sob responsabilidade de quem chama a API: não inclua segredos ou dados que não deseja indexar.

## Verificação offline em PT/EN

Em 10 de outubro de 2026, o modelo foi baixado uma vez por `memory download` para `.codex/arena/models` e testado por FastEmbed/ONNX local, sem API de LLM. O cache foi identificado pelo SHA-256 `8e4f2ad53130cff6ab08007f0f4d83f9a7a8c04250bc062ab96532b356d2943d`. O índice `bilingual-smoke` continha duas notas: uma em inglês sobre a órbita da Terra e outra em português sobre a ebulição da água. A consulta em inglês `planet revolves around its star` colocou `.docs/earth.md` em primeiro, com cosseno `0.5290`; `ponto de ebulição da água` colocou `.docs/agua.md` em primeiro, com `0.7116`; e a consulta em inglês `boiling point of water` recuperou a nota em português primeiro, com `0.7346`. Todas as três respostas reportaram `semantic: true` e usaram `sqlite-vec`.

As dependências de execução estão fixadas em `requirements.txt`: jsonschema `4.26.0`, tomlkit `0.15.1`, PyYAML `6.0.3`, cryptography `50.0.2`, NumPy `2.3.5`, FastEmbed `0.9.0` e sqlite-vec `0.1.9`. `requirements-dev.txt` fixa pytest `9.1.1`. O cache do modelo está fora do banco e permanece em `.codex/arena/models` para uso offline.
