---
type: Reference
title: Playbooks, validação e plugins
---
# Do campeão ao método

`playbook build --from-run` verifica a campanha e sua cadeia de evidências. O gerador recebe estratégias e arquivos de confrontos; extrai procedimentos, verificações, ferramentas, condições de escalada e limites. A saída precisa conter automação Python substantiva para cada tier, instruções `.agents/_index.md` e `strategy.md`, README e índices OKF. Scripts vazios são recusados. A automação `strategy.py --self-test` exercita comportamento antes de publicação do candidato.

O torneio pode terminar sem campeões em alguns tiers. Nesse caso, não invente um método campeão para completar a estrutura: corrija a família/participação e realize outra campanha.

## Validação pareada

Congela-se o candidato antes de avaliar pelo menos cinco casos inéditos, três repetições por caso e variante. Baseline e candidato usam a mesma política, ferramentas e contratos. Avaliam-se conclusão, requisitos obrigatórios, qualidade, tokens e tempo. A amostra e incerteza acompanham o relatório.

Promove-se somente quando não há regressão obrigatória, falhas não aumentam, qualidade média não cai e ocorre ganho mínimo de cinco pontos de qualidade **ou** redução de 10% em tokens/tempo. Os valores ficam no JSON e no manifesto assinado. Evidência simulada nunca autoriza ativação.

`playbook validate <nome> --tier all` compara os quatro tiers. Uma geração congelada pode avaliar tiers ainda não avaliados no mesmo conjunto. Após revisar o candidato com base no resultado, use outro conjunto inédito. Renomear casos não os torna inéditos. O registro local rejeita reuso reconhecido de conteúdo.

Para retomar validação interrompida, repita o comando com `--resume-id <id>` e os mesmos candidato, conjunto, tiers e configuração. As chamadas concluídas são reutilizadas por identidade; chamadas incertas exigem conciliação.

## Seleção e confiança

`playbook.json` contém `signed`, envelope Ed25519 com manifesto imutável, e `runtime`, seleção operacional validada separadamente. Hashes SHA-256 cobrem inventário completo, regras, procedência e conteúdo de todos os tiers/plugins. Evidências de validação são envelopes assinados vinculados ao hash do candidato, fora do conteúdo congelado.

As chaves e a lista de confiança ficam em `.codex/arena/keys`, fora do pacote. `keys rotate` cria nova chave; `keys revoke <id>` invalida confiança explicitamente. Assinatura prova integridade e procedência local, não a verdade universal de uma estratégia. Distribuição entre workspaces exige transportar confiança por um canal confiável, não aceitar automaticamente uma chave embutida no pacote.

`activate` exige validação real aprovada. `show` reverifica assinaturas, seleção e plugins antes de fornecer caminhos para o agente consumir. Se arquivos mudarem, construa nova versão; não edite hashes manualmente.

## Plugins

O plugin deve integrar o inventário **antes** de assinar o candidato. Veja `examples/plugins/check-contract/main.md`. Frontmatter declara `requires`, `capabilities`, `effects`, `invariants`, `incompatible`. O corpo apresenta pseudocódigo de alto nível e pode apontar a outros módulos Markdown.

`plugin check <playbook> <plugin...>` realiza verificações estruturais e retorna o contexto da combinação, inclusive quando o playbook ainda é candidato. A checagem é somente leitura e não equivale a aprovação semântica. `plugin enable` e `disable` exigem tier validado e revisão semântica assinada para toda combinação não vazia; use orçamento explícito ou `--review-receipt` compatível já disponível. Resultado `unknown` ou `conflict` bloqueia.

A aprovação fica vinculada ao conteúdo, regras, tier, modelos/esforços e conjunto de plugins. Mudanças invalidam a revisão. Desabilitar todos não exige inferência. Não adicione instruções que violem a invariância do playbook ou dependam de um plugin ausente.
