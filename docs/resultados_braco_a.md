# Resultados — Braço A (só números)

**Data:** 06/10/2026 · **Modelo:** `jev-1.13.0` · **Pré-registro:** [PREREGISTRATION.md](../PREREGISTRATION.md) (commit `250faac`, feito antes de qualquer previsão de teste)
**Notebook com gráficos e tabelas:** [02_resultados_braco_a](../notebooks/02_resultados_braco_a.ipynb)

## Resumo

Usado sem nenhum treino nos dados do rio, o Jev tem **habilidade real** para prever se o Rio Negro em Manaus vai cair a 17,70 m em 14 dias. No teste (2015–2024), ele erra bem menos que a climatologia, com IC 95% que exclui o empate. Em 30 dias ele também fica à frente da climatologia, mas o IC encosta no zero.

Contra o melhor método estatístico treinado com o histórico (regressão logística), o Jev **empata dentro da incerteza** nas duas tarefas principais. No valor pontual ele fica um pouco atrás: Brier 0,042 contra 0,035 em 14 dias e 0,115 contra 0,104 em 30 dias.

As respostas do Jev são **estáveis**: trocar o nome ou a ordem das opções inverte no máximo ~2% das decisões. **Não houve sinal de memória:** informar a data e o ano não melhorou as previsões das secas famosas.

No teste final (2025–2026), o Jev deu **um alarme falso** em outubro de 2025: chegou a 67% de chance de cruzar 17,70 m, e o rio parou em 18,90 m. Os baselines não deram esse alarme.

## Como foi o teste

- **Pergunta:** a cota de Manaus vai ficar ≤ L em algum dia dos próximos H dias? Previsões diárias de 1º de julho até o mínimo do ano, só enquanto o rio está acima do limiar.
- **Tarefas:** L = 17,70 m (limiar da sobretaxa da ONE) e 15,0 m (seca extrema); H = 14 e 30 dias. As principais são as de 17,70 m. As de 15,0 m têm só 2 anos com evento no teste (2023 e 2024).
- **Anos:** treino até 1999, validação 2000–2014, **teste 2015–2024**, teste final 2025–2026.
- **Jev:** estado em inglês, sem ano nem data, com os mesmos números que os baselines recebem. O texto foi escolhido na validação entre duas versões (v1 e v2), e só essas duas foram testadas.
- **Concorrentes:** climatologia, tendência, anos análogos, regressão logística e gradient boosting, cada um em duas variantes de features. Os hiperparâmetros foram escolhidos na validação.
- **Métrica:** Brier score (erro quadrático da probabilidade; menor é melhor). O IC 95% vem de bootstrap que reamostra **anos inteiros**, porque os dias de um mesmo ano são correlacionados.
- **Custo:** 13.044 chamadas ao Jev, 17,8 milhões de tokens, **US$ 0,75** no total.

## Comparações principais (teste 2015–2024)

Diferença = Brier do Jev − Brier do outro. Negativo significa que o Jev foi melhor.

| Tarefa | Comparação | Brier Jev | Brier outro | Diferença (IC 95%) | Veredito |
| --- | --- | ---: | ---: | --- | --- |
| **17,70 m / 14 d** | Jev bruto × climatologia | 0,042 | 0,078 | −0,036 (−0,062 a −0,007) | **Jev melhor** |
| **17,70 m / 14 d** | Jev calibrado × regressão logística calibrada | 0,043 | 0,035 | +0,008 (−0,003 a +0,021) | Empate |
| **17,70 m / 30 d** | Jev bruto × climatologia | 0,115 | 0,150 | −0,036 (−0,076 a +0,004) | Empate (P(Jev melhor) = 96%) |
| **17,70 m / 30 d** | Jev calibrado × regressão logística calibrada | 0,122 | 0,104 | +0,018 (−0,006 a +0,048) | Empate |
| 15,0 m / 14 d | Jev bruto × climatologia | 0,009 | 0,023 | −0,014 (−0,043 a +0,007) | Empate |
| 15,0 m / 14 d | Jev calibrado × gradient boosting calibrado | 0,009 | 0,007 | +0,003 (−0,001 a +0,009) | Empate |
| 15,0 m / 30 d | Jev bruto × climatologia | 0,034 | 0,046 | −0,012 (−0,057 a +0,021) | Empate |
| 15,0 m / 30 d | Jev calibrado × gradient boosting calibrado | 0,035 | 0,037 | −0,002 (−0,023 a +0,012) | Empate |

**Como ler:** com só 10 anos de teste, os intervalos são largos. "Empate" quer dizer que os dados não distinguem os dois métodos, não que eles são iguais. Nas tarefas principais, o valor pontual favorece a regressão logística.

## Resultados secundários

- **Calibrar não ajudou o Jev.** Ajustada na validação, a calibração de Platt deixou o Jev um pouco pior no teste (0,042 → 0,043 e 0,115 → 0,122). A correção aprendida em 2000–2014 não se transferiu para 2015–2024. O Jev bruto já sai razoavelmente calibrado com o texto v2.
- **Ordenação:** o AUC do Jev ficou entre 0,90 e 0,99, no nível dos baselines. Em 15,0 m / 14 d foi o maior de todos (0,994).
- **Antecedência (17,70 m / 30 d):** nos 8 anos com cruzamento, o Jev ficou em alerta (P ≥ 0,5) de 4 a 15 dias seguidos antes do cruzamento. A regressão logística ficou de 0 a 28 dias. Nenhum dos dois métodos domina o outro em todos os anos.
- **Alarmes falsos no teste:** em 17,70 m, todos os métodos tiveram 1 ou 2 anos com alarme falso, o Jev incluído. Em 15,0 m, o Jev teve 2 anos com alarme falso e os baselines, nenhum.
- **Variantes dos baselines:** a variante "só Manaus, treino desde 1902" ganhou na validação de quase todas as tarefas. Ter mais anos com seca no treino valeu mais que o dado do Solimões.

## Robustez do Jev

| Variante | Decisões invertidas (17,70 m / 14 d) | (17,70 m / 30 d) | Brier 30 d (principal: 0,115) |
| --- | ---: | ---: | ---: |
| Opções renomeadas para "1"/"0" | 0,9% | 2,1% | 0,115 |
| Opções renomeadas para "yes"/"no" | 0,5% | 2,2% | 0,113 |
| Ordem das opções invertida | 0,9% | 1,9% | 0,118 |
| Pergunta sim/não (Noul) em vez de Choice | 1,7% | 3,9% | 0,104 |

O efeito descrito em arXiv 2609.26758, em que renomear as opções de 0/1 para no/yes inverte as decisões, **não se reproduziu** aqui. Uma explicação plausível é que cada opção tem uma descrição explícita do que significa, e o artigo testa o caso sem essa descrição.

O Noul teve o melhor Brier em 17,70 m / 30 d (0,104), mas isso é uma observação **exploratória**: o Noul não era o método pré-registrado.

## Teste de memória

Com a data e o ano no estado, o Brier **não caiu** nos anos de seca conhecidos. Em 2023 e 2024 ele até subiu um pouco (+0,002 a +0,015). Não há indício de que o Jev "lembre" dessas secas. Também não dá para provar que ele nunca viu esses dados.

## Teste final (2025–2026), rodado uma única vez

Como o pré-registro previa, não há cruzamento com rótulo conhecido no período. O mínimo de 2025 foi 18,90 m (09/11/2025), e em 2026 só entram os dias cujo horizonte já terminou.

- **17,70 m / 30 d:** o Jev deu um **alarme falso** em 2025. Ficou 18 dias acima de 50% em outubro, com pico de 67%. A nota técnica do SGB de setembro de 2025 também tinha 17,70 m como mínimo possível, mas os baselines treinados chegaram no máximo a 42%. Brier: Jev 0,046 contra 0,009 da regressão logística.
- **Nas demais tarefas** todos os métodos acertaram "não cruza", com Brier perto de zero.
- **Poder estatístico:** com 2 anos e nenhum evento, o teste final só mede alarmes falsos e não serve para afirmar superioridade de ninguém.

## Limitações

1. **Poucos anos.** A unidade efetiva de amostra é o ano: são 10 no teste, 8 deles com cruzamento de 17,70 m e só 2 com cruzamento de 15,0 m.
2. **Problema numérico.** O braço A é um terreno desfavorável ao Jev, cuja documentação admite dificuldade com precisão numérica. Mesmo assim ele empatou com os métodos treinados. A vantagem esperada do Jev (ler texto) só aparece no braço B.
3. **Texto do Jev escolhido na validação.** Foram só 2 versões, declaradas no pré-registro. Mesmo assim, a escolha pode favorecer levemente o Jev nos anos de validação. No teste não houve nenhum ajuste.
4. **Fontes diferentes para a mesma régua.** A verdade de 2015 em diante vem do Porto de Manaus. A mesma régua na ANA coincidiu com o porto em 2000–2014: mediana de 0 cm e 90% dos dias com no máximo 2 cm de diferença.
5. **Memória não pode ser descartada por completo.** O teste com datas só mostra que informar o ano não ajudou.

## Conclusão

Num problema numérico, que está fora da especialidade declarada do Jev, ele mostrou habilidade sem nenhum treino e empatou estatisticamente com o melhor método estatístico treinado com 30 a 100 anos de histórico. Ainda assim ficou um pouco atrás no valor pontual e deu um alarme falso no teste final.

Ele foi estável a mudanças de formulação e não mostrou sinais de memória. A comparação ganha interesse no braço B, que acrescenta os boletins do SGB em texto, onde os métodos estatísticos não têm acesso à informação.

## Como reproduzir

```bash
uv run python -m supplyrisk.download        # dados (ANA + Porto de Manaus)
uv run python -m supplyrisk.serie           # série diária
uv run python -m supplyrisk.amostras        # amostras e features
uv run python -m supplyrisk.experimento baselines validacao
uv run python -m supplyrisk.experimento jev validacao
uv run python -m supplyrisk.experimento baselines teste
uv run python -m supplyrisk.experimento jev teste
uv run python -m supplyrisk.analise teste
```

As respostas do Jev estão em `data/jev/` (pedido e resposta brutos). Rodar de novo reaproveita esse cache e não gasta chamadas.
