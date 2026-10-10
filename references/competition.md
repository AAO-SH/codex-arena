---
type: Reference
title: Competição e contabilidade
---
# Competição

O competidor combina três cartas de estratégia com uma política de escalada congelada. A distribuição equilibra quinze formas de raciocínio observável, doze fluxos e doze prioridades. A seed determina sorteios e desempates estáveis, não torna as respostas do modelo determinísticas.

## Jogo e julgamento

Rascunhos iniciais podem ser reutilizados por competidor/caso. Cada par recebe dois ataques novos, duas defesas/revisões novas e julgamento cego. Arquivos e recibos têm identidade por confronto. Testes objetivos verificam o contrato de conclusão antes da comparação subjetiva.

`F` significa não concluir; `L` significa concluir e perder por qualidade. `W` é vitória; `T` empate. Falha não acumula derrota. Ambos podem falhar. Velocidade e custo não elegem o vencedor de um jogo.

A rubrica soma correção 30, completude 25, robustez 20, especificidade 15 e clareza 10. Diferença de até cinco pontos ou alegação fatal aciona segunda avaliação nova com posições invertidas; discordância de resultado aciona arbitragem. Fatal precisa de evidência observável. O julgamento de modelo não substitui testes objetivos.

## Etapas

1. **Battle Royal:** round-robin com todos os pares únicos, sem eliminação. O padrão 100 produz 99 rodadas e 4.950 jogos.
2. **Corte:** saem 20, por mais falhas, mais derrotas, menor pontuação e seed. Os 80 restantes formam faixas ascendentes de 20: iron, copper, silver, gold.
3. **Swiss:** cinco rodadas por tier, quatro marcas de derrota/falha eliminam. Pareamento minimiza primeiro revanches, depois diferença de campanha. A exceção de revanche fica registrada. Bye dá três pontos administrativos; não inventa vitória ou tarefa. Classificam os oito melhores elegíveis, ou menos quando necessário.
4. **Dupla eliminação:** duas derrotas de série eliminam. A final sofre reset se o finalista inferior vencer o invicto. Sem elegíveis, não há campeão.
5. **+1:** os métodos destilados são avaliados contra baseline em casos inéditos.

Os pontos reiniciam entre etapas; resultados anteriores, snapshots e eventos permanecem. Desempate de classificação: pontos, menos falhas, mais vitórias, força dos adversários, seed.

O pareamento Swiss exato usa programação dinâmica. O tamanho padrão de vinte por tier é apropriado; aumentar muito o grupo amplia exponencialmente seu custo computacional.

## Dez jogos completos

Cada série executa dez jogos, sem encerramento antecipado:

```text
S = 3 × W − 3 × L − 5 × F
```

Em empate, vence quem falhou menos e depois quem venceu mais. Persistindo, até cinco jogos extras. Ainda igual: série inconclusiva e retomável, sem vencedor artificial. O histórico não é alterado para forçar conclusão.

## Eficiência

No perfil padrão, ao encerrar uma rodada, uma fotografia comum normaliza médias dos participantes:

```text
velocidade = 1 − 2 × (média_ms − mínimo_ms) / (máximo_ms − mínimo_ms)
despesa = 2 − 4 × (custo_por_conclusão − mínimo) / (máximo − mínimo)
pontos = 3W − 3L − 5F + Σvelocidade + Σdespesa + administrativos
```

Intervalo nulo dá contribuição zero. Sem conclusão, não há bônus. Uma falha na rodada atual não recebe bônus por conclusões antigas. O custo por conclusão inclui todas as tentativas próprias, inclusive as malsucedidas. Rascunhos reutilizados são contabilizados uma única vez; juízes, geração e validação têm rubricas administrativas separadas.

Tokens de cache já pertencem à entrada; raciocínio já pertence à saída. Contadores ausentes não viram zero. As médias das conclusões são diferentes do consumo de todas as tentativas; `report` expõe ambas, além de vitórias, derrotas e falhas por conclusão.

## Perfil original

`scoring.profile="original"` mantém throughput = tokens médios / milissegundos médios × 1000; normalização de −1 a +1. Seu índice de custo = throughput × preço equivalente por milhão, normalizado de +2 a −2. Não é dinheiro por tarefa.

Exige `scoring.original.min` e `.max` com modelo, esforço, throughput e preço por milhão medidos: `gpt-5.6-luna/low` e `gpt-6-astra/ultra`. Consulte `examples/original-calibration.json`. Todos os competidores precisam de throughput conhecido antes do cálculo. Sem calibração completa, a campanha é recusada antes de inferência.
