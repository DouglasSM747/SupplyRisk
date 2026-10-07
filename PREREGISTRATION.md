# Pré-registro — Braço A (só números)

**Data:** 06/10/2026, antes de gerar qualquer previsão para os anos de teste (2015–2024) e de teste final (2025–2026).
**Commit:** este arquivo é commitado junto com o código, os hiperparâmetros e as previsões de validação. Tudo o que vier depois (previsões de teste) entra em commits posteriores.

## 1. Pergunta

O Jev (`jev-1.13.0`), sem treino nos dados do rio, prevê se a cota do Rio Negro em Manaus vai cruzar limiares de navegação com qualidade comparável à de métodos estatísticos treinados com o histórico?

## 2. Tarefa

- **Dia de previsão `t`:** de 1º de julho até o dia do mínimo anual (janela jul–dez), apenas enquanto a cota em `t` está **acima** do limiar. No ano corrente (2026), só os dias cujo horizonte já foi observado (ou em que o cruzamento já ocorreu).
- **Rótulo:** 1 se a cota fica ≤ limiar em algum dia de `t+1` a `t+H`.
- **Tarefas:** limiar 17,70 m e 15,0 m × horizonte 14 e 30 dias.
- **Verdade:** série diária padronizada (`data/processed/cotas_diarias.parquet`). ANA consistida até 2014 e régua oficial do Porto de Manaus depois; ver `docs/dados.md`.
- **Informação disponível:** só dados até `t` (inclusive). A climatologia de referência usa 1972–1999.

## 3. Divisão dos anos

| Uso | Anos |
| --- | --- |
| Treino dos baselines (variante principal) | 1972–1999 |
| Treino dos baselines (variante só Manaus) | 1902–1999 |
| Validação: hiperparâmetros, texto do Jev, calibração, escolha do melhor baseline | 2000–2014 |
| **Teste** | **2015–2024** |
| **Teste final** (rodado uma única vez, depois de tudo) | **2025–2026** |

## 4. Métodos

**Baselines** (`src/supplyrisk/baselines.py`), cada um em duas variantes de features e treino:

- `principal`: features de Manaus e de Manacapuru, treino 1972–1999;
- `so_manaus`: só features de Manaus, treino 1902–1999.

Os métodos são climatologia condicional, tendência (extrapolação dos últimos 7 dias com a distribuição empírica de erros), anos análogos, regressão logística e gradient boosting (LightGBM). Os hiperparâmetros foram escolhidos pelo Brier na validação e estão congelados em `data/resultados/hiperparametros.json`.

**Jev** (`src/supplyrisk/jev.py`): modelo fixado em `jev-1.13.0`.

- **Estado:** em inglês e sem ano nem data. Traz os mesmos números das features e as contas feitas em código: distância ao limiar e dias até o limiar no ritmo atual.
- **Pergunta:** uma Choice por tarefa, com as opções `crosses_threshold` / `stays_above`.
- **Texto (versão v2):** escolhido na validação contra **uma única** alternativa (v1). A v2 acrescenta ao contexto uma frase dizendo que a descida desacelera perto do mínimo. Brier médio na validação: v1 0,0466; v2 0,0328. Nenhuma outra versão foi testada.

**Melhor baseline por tarefa**, escolhido pelo menor Brier bruto na validação entre os 10 baselines:

| Tarefa | Melhor baseline |
| --- | --- |
| 17,70 m / 14 d | `logistica__so_manaus` |
| 17,70 m / 30 d | `logistica__so_manaus` |
| 15,0 m / 14 d | `gradient_boosting__so_manaus` |
| 15,0 m / 30 d | `gradient_boosting__so_manaus` |

**Calibração:** escalonamento de Platt (regressão logística sobre o logit da probabilidade), ajustado nos anos de validação para cada método e tarefa, e aplicado no teste. O plano original falava em regressão isotônica. Troquei por Platt antes de ver o teste porque a validação tem poucos eventos (28 a 240 positivos por tarefa) e a isotônica fica instável nessas condições.

## 5. Análises

**Métrica principal:** Brier score no teste (2015–2024).

**Tarefas principais:** 17,70 m com 14 e 30 dias. As tarefas de 15,0 m são **secundárias**: o teste tem só 2 anos com esse evento (2023 e 2024), poder estatístico baixo.

**Comparações principais**, para cada tarefa principal:

1. **Habilidade sem treino:** o Brier skill score (BSS) do Jev **bruto** contra a `climatologia__principal`. Há habilidade se o IC 95% da diferença de Brier (Jev − climatologia) ficar inteiro abaixo de 0.
2. **Jev contra o melhor baseline:** o Jev **calibrado** contra o melhor baseline **calibrado**. Pela diferença de Brier (Jev − baseline):
   - **superior** se o IC 95% ficar inteiro abaixo de 0;
   - **inferior** se ficar inteiro acima de 0;
   - **equivalente dentro da incerteza** se contiver o 0.

**Intervalos de confiança:** bootstrap em blocos de **ano**, com 2.000 reamostragens e semente 42 (`avaliacao.bootstrap_por_ano`).

**Análises secundárias**, reportadas em todas as tarefas:

- **Métricas adicionais:** log-loss, AUC, BSS e diagrama de confiabilidade de todos os métodos, brutos e calibrados.
- **Antecedência:** dias de alerta sustentado (P ≥ 0,5) antes do primeiro cruzamento, em cada ano com cruzamento.
- **Alarmes falsos:** anos sem cruzamento em que P ≥ 0,5 em algum dia.
- **Variante só Manaus × principal:** quanto Manacapuru ajuda os baselines.

**Robustez do Jev**, rodada no período de teste:

| Variante | O que muda |
| --- | --- |
| `nomes_01` | opções renomeadas para "1"/"0", mesmas descrições |
| `nomes_sim_nao` | opções renomeadas para "yes"/"no" |
| `ordem_invertida` | `stays_above` antes de `crosses_threshold` |
| `noul` | pergunta sim/não em vez de Choice |
| `com_datas` | data e ano no estado (teste de memória) |

Para cada variante, reporto o Brier, a diferença absoluta média de probabilidade em relação à principal e a fração de decisões invertidas em P = 0,5.

**Teste de memória:** a diferença de Brier entre `com_datas` e `principal`, ano a ano. Se `com_datas` for claramente melhor nos anos de secas conhecidas (2015, 2023, 2024), é indício de que o Jev lembra esses eventos.

**Teste final (2025–2026):** rodado uma única vez, depois de todo o resto, com os mesmos métodos e calibrações. Expectativa declarada antes: não há cruzamento de 17,70 m em 2025 (mínimo de cerca de 18,8 m), e em 2026 os dias com rótulo conhecido também não têm cruzamento. Logo, o teste final mede **só alarmes falsos e calibração em dias sem evento**.

## 6. O que não muda depois deste commit

Ficam congeladas as definições de tarefa e rótulo, a divisão dos anos, as features, os hiperparâmetros, o texto do Jev (v2), o modelo `jev-1.13.0`, o melhor baseline por tarefa, o método de calibração, as métricas e os critérios de decisão.

Qualquer análise não listada aqui será marcada como **exploratória** no relatório.

## 7. Limitações conhecidas antes do teste

- Poucos eventos de 15,0 m em todos os períodos.
- Os dias de um mesmo ano são fortemente correlacionados. A unidade efetiva de amostra é o ano: o teste tem 10.
- Não dá para garantir que o Jev não viu dados recentes no treino. Por isso existe o teste de memória.
- A série de 2015 em diante vem do Porto de Manaus, não da ANA: são fontes diferentes da mesma régua.
