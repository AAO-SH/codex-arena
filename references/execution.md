---
type: Reference
title: Instalação, execução e recuperação
---
# Instalação local

`install --workspace <projeto>` copia somente o pacote gerenciado para `.agents/skills/codex-arena` e mantém inventário de hashes. Repetir a mesma versão é idempotente. Edições locais conflitantes impedem atualização. O bloco gerenciado usa `skills.config`; não altera modelo padrão, credenciais ou confiança global.

`--bootstrap` cria/reusa `.venv` e instala dependências com versões fixadas. Ao mover o projeto, recrie o venv (ele contém caminhos do Python de origem); os dados e pacotes da skill usam caminhos relativos. `memory download` prepara o cache local ONNX; depois a busca funciona offline. `install --rollback` valida backups antes de restaurar, preservando arquivos alheios.

## Modelos e esforços

`models` usa o protocolo app-server `initialize` → `model/list`, incluindo paginação, e retorna esforços por modelo. A consulta não faz inferência. `doctor` informa Python, bibliotecas, CLI, confiança, catálogo, preços e limites da telemetria.

Modifique `models.policy` para trocar a política inicial: luna/medium → sol/high → astra/xhigh. São permitidas até duas escaladas por trabalho. Uma combinação ausente no catálogo é recusada; não há fallback silencioso. Configuração solicitada e efetivamente informada pelo CLI são registradas separadamente. Um campo efetivo não informado permanece `null`.

O adaptador é específico ao protocolo JSONL observado e valida os eventos. Novos formatos desconhecidos param a contabilidade até atualização do adaptador. `ultra` só participa de classificação por custo após validar a abrangência de consumo e incluir o modelo em `models.verified_usage_models`. Este campo é uma declaração operacional que deve ser sustentada por calibração, não autorização para inventar dados.

## Orçamento e estado

Cada chamada reserva tokens atomicamente no SQLite antes do despacho. O número de processos é configurável, quatro por padrão. `max_tokens` limita reservas/consumo conhecido; `max_ms` limita duração acumulada de execução da campanha. Nenhum deles é um teto garantido da fatura externa: jobs em andamento podem produzir consumo ainda não recebido.

Exemplo de retomada:

```text
arena.py status RUN --json
arena.py resume RUN --max-tokens 500000 --max-ms 900000 --json
```

Os limites de `resume` são **totais**, não adicionais. Configuração e arquivos de entrada da campanha ficam congelados. Recibos idênticos são idempotentes; resultados conflitantes são rejeitados. Leases/locks impedem dois supervisores de consumir a mesma execução simultaneamente.

Uma série que esgotou o limite de desempates permanece inconclusiva. Para continuar, forneça `resume RUN --extra-games N` junto dos novos limites totais. A autorização acrescenta uma extensão registrada às séries inconclusivas, sem editar pontuações anteriores ou selecionar campeão artificialmente.

Interrupção após possível despacho é `ambiguous`. `reconcile RUN --job ID` tenta liquidar somente evidência local completa e compatível. Não há comando para assumir consumo zero ou simplesmente reenviar uma chamada incerta. Se o provedor não expôs contadores completos, preserve a pausa e investigue a origem; iniciar uma campanha nova não apaga o custo anterior.

Erros demonstravelmente anteriores ao despacho admitem retentativas limitadas; erros incertos não. Falhas de infraestrutura não viram penalidades esportivas.

## Isolamento

Cada trabalho usa diretório próprio, sessão efêmera, saída estruturada e permissões limitadas. A política de leitura deve bloquear outros casos e variantes. Configuração legada `sandbox_mode` conflita com os perfis modernos: o executor recusa a combinação incompatível. Não afrouxe permissões para contornar uma recusa.

O sandbox Windows legado pode recusar negação de leitura na raiz. É necessário um backend que suporte o perfil, como MXC em um host compatível ou execução dentro de WSL configurado. A skill testa um arquivo permitido e outro bloqueado sem inferência; se o teste falhar, não inicia chamadas pagas. A instalação não modifica o sandbox global nem instala componentes do sistema.

As autorizações já existentes do CLI são reutilizadas sem copiar credenciais. Os comandos de testes objetivos da suíte são código escolhido pelo autor da campanha; revise-os como parte do contrato da tarefa. O conjunto de validação não deve estar em `.docs`, índices, plugins ou instruções de aprendizado.

O adaptador desta versão restringe a competição a arquivos e comandos locais. Browser, MCP, hooks externos, rede dos comandos e delegação interna ficam desativados para manter condições comparáveis e a contabilidade verificável. Tarefas que dependem dessas capacidades precisam de um adaptador e uma calibração próprios; não as avalie fingindo que as ferramentas estavam disponíveis.

Os preços em `assets/default-config.json` são uma fotografia indicada em `price_provenance`. Revise-os antes da campanha. Input, cache e output são precificados separadamente; raciocínio e cache não são novamente somados aos contadores inclusivos.

Contadores agregados de uma sessão não identificam necessariamente o tamanho de cada requisição. Se a agregação ultrapassar o limiar de contexto longo e não houver detalhamento confiável por requisição, o custo permanece desconhecido; não se aplica um multiplicador presumido para classificar o agente.
