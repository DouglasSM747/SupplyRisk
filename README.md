# Amazon Supply Risk — avaliando o Jev na vazante do Rio Negro

**Pergunta da pesquisa:** o Jev, um modelo de decisão probabilística (System One Model) que nunca foi treinado com dados de rios, consegue prever com antecedência se o Rio Negro em Manaus vai cair abaixo dos níveis que afetam a navegação? Como ele se compara a métodos tradicionais?

Este é um **estudo de avaliação**, não um produto em produção. O resultado esperado é um repositório reproduzível e um post de divulgação. Se os resultados forem interessantes, o estudo vira um relatório técnico ou preprint.

> Pesquisa original e comparação com o projeto "Amazonas Sentinel": [docs/pesquisa-inicial.md](docs/pesquisa-inicial.md).
> Dados brutos, organização e padronização: [docs/dados.md](docs/dados.md).

## Resultado do braço A (só números) — 06/10/2026

No teste (2015–2024), o Jev **sem nenhum treino** foi melhor que a climatologia em 17,70 m / 14 dias (IC 95% exclui o empate) e **empatou dentro da incerteza** com o melhor método estatístico treinado (regressão logística), ficando um pouco atrás no valor pontual. Ele foi estável a mudanças no nome e na ordem das opções e não mostrou sinal de memória das secas famosas. No teste final deu um alarme falso em outubro de 2025. Custo total: US$ 0,75.

Relatório completo: [docs/resultados_braco_a.md](docs/resultados_braco_a.md) · gráficos: [notebooks/02_resultados_braco_a.ipynb](notebooks/02_resultados_braco_a.ipynb) · pré-registro: [PREREGISTRATION.md](PREREGISTRATION.md)

## Por que esse problema

- A régua de Manaus (ANA, estação **14990000**) tem nível diário desde 1902. Isso dá mais de 120 vazantes e um ground truth sem ambiguidade.
- Os limiares têm consequência econômica real. Abaixo de **17,70 m**, a ONE cobra sobretaxa fixa de US$ 4.592 por contêiner (2026). Abaixo de 17,20 m, a Maersk prevê descarga integral em Itacoatiara.
- Nenhum órgão público publica a probabilidade diária de o rio cruzar esses limiares. O SGB publica previsão de **cheia**. Para a vazante, só há cenários avulsos.

## A tarefa

Uma previsão por dia, de **1º de julho até o mínimo anual**, respondendo:

> Qual a probabilidade de a cota de Manaus ficar **≤ L** em algum dia dos próximos **H** dias?

- **L:** 17,70 m (principal) e 15,0 m (seca extrema)
- **H:** 14 e 30 dias

## Competidores

| Método | Descrição |
| --- | --- |
| Persistência/tendência | Extrapolação linear da descida dos últimos 7 dias |
| Climatologia | Frequência histórica de cruzamento, dado o dia do ano e o nível atual |
| Anos análogos | Vazantes passadas parecidas com a atual (método usado pelo SGB) |
| Regressão logística | Features hidrológicas |
| Gradient boosting (LightGBM) | Mesmas features |
| **Jev** | Zero-shot: estado em texto → decisão tipada com probabilidade |
| SGB (comparação qualitativa) | Só 2024–2026, nas poucas previsões de vazante publicadas |

## Braços do experimento

- **Braço A — só números.** O Jev recebe o mesmo estado numérico que os baselines: nível e taxa de descida em Manaus, nível e taxa de descida do **Solimões em Manacapuru**, climatologia etc. É a comparação justa.
- **Braço B — números + texto.** O Jev também recebe o boletim semanal do SGB mais recente. Testa se ler contexto em texto ajuda. Cobre só **2016–2026**, com previsões semanais nas datas dos boletins. O braço A também é rodado nessas mesmas datas, para comparar os dois em pé de igualdade.

## Divisão temporal

| Uso | Braço A | Braço B |
| --- | --- | --- |
| Treino (baselines) | 1972–1999 | — |
| Validação / calibração | 2000–2014 | 2016–2020 |
| Teste | 2015–2024 | 2021–2024 |
| Teste final (rodado uma única vez) | 2025–2026 | 2025–2026 |

A série de Manacapuru começa em 1972, por isso o treino principal começa nesse ano. Variante de robustez: braço A **só com Manaus**, com treino em 1902–1999. Ela mede quanto o Solimões ajuda e quanto pesa usar um século de dados de um clima diferente do atual. A climatologia e os anos análogos podem usar o histórico de Manaus desde 1902 nas duas versões.

Divisão sempre por ano. Nunca embaralhar dias do mesmo ano.

## Controles de rigor

1. **Contaminação por memória.** O estado enviado ao Jev não tem ano nem data absoluta: só "dia N da vazante". Nos boletins, o ano corrente e as datas viram marcadores relativos, e anos passados viram rótulos ("seca recorde anterior: 12,70 m"). Uma checagem automática garante que não sobrou nenhum `19xx`/`20xx`. Uma versão **com** datas é rodada também, e a diferença entre as duas mede quanto o Jev "lembra".
2. **Nomes das opções.** A versão principal usa nomes neutros e descritivos (`cruza_limiar` / `permanece_acima`). Como robustez, roda também com `0/1` e `sim/não`, replicando o arXiv 2609.26758.
3. **Calibração.** As probabilidades do Jev são reportadas cruas (zero-shot) e calibradas com regressão isotônica nos anos de validação.
4. **Pré-registro.** Um `PREREGISTRATION.md` com métricas e critérios é commitado **antes** de rodar o Jev no conjunto de teste.
5. **Reprodutibilidade.** Toda chamada ao Jev é guardada (entrada e saída brutas) em JSONL versionado, junto com a versão do modelo. Um único comando gera todas as tabelas e figuras.

## Métricas

- **Brier score** e **log-loss**
- **Calibração** (diagrama de confiabilidade)
- **AUC**
- **Antecedência**: dias entre o primeiro alerta de risco alto e o cruzamento real

## Fontes de dados

| Dado | Fonte | Acesso |
| --- | --- | --- |
| Cota diária de Manaus | [HidroWeb — séries históricas](https://www.snirh.gov.br/hidroweb/serieshistoricas), estação 14990000 | Download livre. Conferir se a série começa em 1902 |
| Cota diária (API) | [HidroWebService](https://www.ana.gov.br/hidrowebservice/swagger-ui/index.html) ([manual](https://www.gov.br/ana/pt-br/assuntos/monitoramento-e-eventos-criticos/monitoramento-hidrologico/orientacoes-manuais/manuais/manual-hidrowebservice_publica.pdf)) | Credencial pedida por e-mail para <hidro@ana.gov.br> |
| Cota diária do Solimões em Manacapuru | [HidroWeb](https://www.snirh.gov.br/hidroweb/serieshistoricas), estação 14100000 | Download livre. Série desde 1972 |
| Telemetria recente | [Hidrotelemetria](https://www.snirh.gov.br/hidrotelemetria/) | Livre |
| Boletins semanais do SGB (2016–2026) | [Índice SACE Amazonas](https://www.sgb.gov.br/sace/amazonas_boletins.php) | Livre. Extrair os links do índice e converter os PDFs com `pdftotext` |
| Boletins diários da ANA (~2022–2026) | [Sala de Situação — Rio Amazonas](https://www.gov.br/ana/pt-br/sala-de-situacao/rio-amazonas) | Livre. A data vem dos metadados da página, não do nome do arquivo |
| Cota diária oficial de Manaus (2000–hoje) | [Porto de Manaus](https://portodemanaus.com.br/nivel-do-rio-negro/) | Livre. É a régua de referência das armadoras; substitui o sensor da ANA de 2015 em diante |
| Jev | [TypeSafe AI](https://typesafe.ai/blog/introducing-system-one-models-and-jev) | Lista de espera em console.typesafe.ai. US$ 0,042 por milhão de tokens de entrada |

## Próximos passos

- [x] Pedir acesso ao Jev (console.typesafe.ai) — chave em `.env` (`JEV_API_KEY`)
- [ ] Pedir credenciais da API da ANA (<hidro@ana.gov.br>)
- [x] Baixar as séries das estações 14990000 (Manaus) e 14100000 (Manacapuru) e a régua oficial do porto (ver [docs/dados.md](docs/dados.md))
- [ ] Extrair e anonimizar os boletins do SGB de 2016–2026
- [x] Implementar os baselines e o pipeline de avaliação
- [x] Escrever e commitar o `PREREGISTRATION.md` (braço A)
- [x] Rodar o Jev no braço A, com testes de robustez
- [ ] Braço B: pré-registro próprio e Jev com os boletins do SGB
- [x] Rodar o teste final (2025–2026) uma única vez (braço A)
- [ ] Publicar o repositório e o post

## Limitações conhecidas

- O braço B tem poucos anos de teste (4 de teste e 2 de teste final). Os resultados dele são indicativos.
- O estudo prevê o nível do rio, não o impacto em cada fábrica: não há dados públicos de estoque ou frete negociado.
- Não é possível garantir que o Jev não viu dados de anos recentes. Por isso existem o controle de memória (com e sem datas) e o teste final em 2025–2026.
