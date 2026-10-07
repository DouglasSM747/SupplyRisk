# Dados do projeto

Este documento explica de onde vêm os dados, como chegam (brutos) e como são organizados até virar a série diária que os modelos usam.

## De onde vêm

Duas instituições, duas estações:

| Código | Estação | Rio | Por que importa |
| --- | --- | --- | --- |
| **14990000** | Manaus | Negro | É a régua do porto. Os limiares do estudo (17,70 m e 15,0 m) são medidos nela. |
| **14100000** | Manacapuru | Solimões | O Solimões "represa" o Negro na confluência. A queda dele rio acima costuma antecipar a queda em Manaus. |

São três fontes, que cobrem períodos diferentes e se complementam:

| Fonte | Quem publica | Manaus | Manacapuru |
| --- | --- | --- | --- |
| 1. Régua (série convencional) | ANA | 1902–2014 | 1972–2025 |
| 2. Régua oficial do porto | Porto de Manaus | 2000–hoje | — |
| 3. Sensor automático (telemetria) | ANA | 2009–hoje | 2008–hoje |

### Fonte 1 — ANA, série convencional (`HidroSerieHistorica`)

É a leitura da régua feita por um observador: a régua graduada no rio, lida à mão. Vem do serviço público da ANA, que não exige credencial (`http://telemetriaws1.ana.gov.br/ServiceANA.asmx`).

- **Manaus:** de 15/09/1902 a 30/12/2014.
- **Manacapuru:** de 1972 a setembro de 2025. De 2024 em diante, só na versão bruta.
- **Unidade:** centímetros (`1770` = 17,70 m).
- A ANA devolve **um registro por mês**, com uma coluna por dia (`Cota01` … `Cota31`).

Cada mês pode aparecer em mais de uma versão:

| Versão | O que é | Quanto confiar |
| --- | --- | --- |
| Consistência **2** (consistido) | Dado revisado pela ANA: erros de leitura e de digitação corrigidos | Maior |
| Consistência **1** (bruto) | Dado como foi lido no campo | Menor |
| **Média diária** | Um valor por dia | Usado por padrão |
| **Leituras avulsas** (7h e 17h) | As duas leituras do dia, em registros separados (Manaus, 1997–2014) | Só se faltar a média |

Exemplo real: em 01/10/2010, Manaus tem quatro valores para o mesmo dia. A média bruta é 1669,5 cm, a média consistida é 1670 cm, a leitura das 7h é 1672 cm e a das 17h é 1667 cm.

### Fonte 2 — Porto de Manaus, régua oficial

É a cota que o Porto de Manaus publica todo dia em [portodemanaus.com.br/nivel-do-rio-negro](https://portodemanaus.com.br/nivel-do-rio-negro/). É **a referência usada pelas armadoras** (limiar de 17,70 m da ONE, 17,20 m da Maersk) e pelos recordes divulgados, como 12,11 m em 09/10/2024.

- **Cobertura:** de 01/01/2000 até hoje. Faltam só 3 dias: 31/05/2006, 15/12/2012 e 21/12/2012.
- **Unidade:** metros, com duas casas decimais (`12,11`). No `raw/` é convertido para centímetros.
- **Formato:** o site publica **uma tabela por mês** (dia, cota, variação em relação ao dia anterior). A página aceita filtro por ano na URL e mostra 6 meses por página.
- **É a mesma régua da ANA:** nos 5.469 dias de 2000–2014 em que as duas existem, a diferença mediana é **0 cm**, e 90% dos dias diferem no máximo 2 cm. Por isso o porto é a continuação oficial da série da ANA depois de 2014.
- **Erros de digitação do site**, corrigidos e registrados linha a linha (coluna `correcao`):
  - abril de 2026 foi publicado com o título "Abril 2023". Vale a classificação de ano do próprio site (2026), confirmada pela continuidade com março e maio de 2026;
  - 10 meses têm um número de dia repetido (p. ex. 18, 20, 20, 21). Como o mês tem o número certo de linhas, a data passa a ser a posição da linha. São 18 linhas corrigidas no total.

### Fonte 3 — ANA, telemetria (`DadosHidrometeorologicos`)

É um sensor automático que transmite o nível do rio.

- **Cobertura:** Manaus de 2009 a hoje; Manacapuru de 2008 a hoje.
- **Frequência:** variou ao longo dos anos. Eram de 1 a 10 leituras por dia até 2012, e 96 (uma a cada 15 minutos) de 2017 em diante.
- **Unidade:** centímetros.
- **Campos:** `Nivel` (cota), `Vazao` (vazão: vazia em Manaus, preenchida em Manacapuru) e `Chuva`.
- **Qualidade:** é dado bruto de sensor, com falhas, picos espúrios e dias incompletos. **Em Manaus, diverge da régua oficial em até ~40 cm** (ver [Problemas conhecidos](#problemas-conhecidos)). Por isso é a última opção na série padronizada.

## Arquitetura dos dados

**Resumo:** não é um arquivo baixado que vira outros. São **centenas de consultas** a duas instituições. Elas viram **5 tabelas pré-formatadas** (2 estações × 2 fontes da ANA, mais o porto), que viram **1 série final**.

```text
ANA — dois serviços                                      Porto de Manaus — site
│                                                        │
├── HidroSerieHistorica (régua)   → 1 consulta por       └── página de nível filtrada por ano
│                                   estação e por ANO        → 2 páginas por ano (6 meses cada)
└── DadosHidrometeorologicos      → 1 consulta por             (2000–hoje)
    (sensor)                        estação e por MÊS
        │                                                        │
        │  ana.py: xml_convencional / xml_telemetria             │  porto.py: html_ano
        ▼                                                        ▼
CAMADA 1 — data/cache/               respostas originais, como vieram (compactadas)
  ├── ana/convencional/14990000_2010.xml.gz      um arquivo por estação e ano
  ├── ana/telemetria/14990000_202310.xml.gz      um arquivo por estação e mês
  └── porto/2024_p1.html.gz                      um arquivo por ano e página
        │                                                        │
        │  ana.py: tabela_xml → ler_convencional / ler_telemetria│  porto.py: ler_pagina → corrigir_datas
        │  download.py: repete para todos os períodos e junta    │
        ▼                                                        ▼
CAMADA 2 — data/raw/                 5 tabelas, valores iguais aos publicados
  ├── ana_convencional_14990000.parquet     régua de Manaus (ANA)      1902–2014
  ├── ana_telemetria_14990000.parquet       sensor de Manaus           2009–hoje
  ├── porto_manaus.parquet                  régua oficial do porto     2000–hoje
  ├── ana_convencional_14100000.parquet     régua de Manacapuru        1972–2025
  └── ana_telemetria_14100000.parquet       sensor de Manacapuru       2008–hoje
        │
        │  serie.py: escolhe a melhor fonte de cada dia e limpa o sensor
        ▼
CAMADA 3 — data/processed/           1 tabela, é o que os modelos usam
  └── cotas_diarias.parquet                 um valor por dia e por estação
```

### As três camadas

| Camada | Pasta | O que tem | Muda os valores? | Vai para o git? |
| --- | --- | --- | --- | --- |
| 1. Cache | `data/cache/` | A resposta da ANA e do porto exatamente como veio, compactada | Não | Não (pode ser baixada de novo) |
| 2. Pré-formatado | `data/raw/` | Uma linha por medição, com tipos corretos | **Não.** Muda só o formato e o tipo. No porto, as datas com erro de digitação são corrigidas e a correção fica registrada | Sim |
| 3. Padronizado | `data/processed/` | Uma linha por dia e por estação, com a fonte escolhida | **Sim.** Escolhe entre fontes e versões, faz a média do sensor no dia e descarta picos | Sim |

- **Cache:** rodar o download de novo reaproveita o cache e só consulta as fontes para o período recente, que ainda pode mudar (últimos 45 dias na ANA, ano corrente no porto). Consultas que falham não entram no cache e são tentadas de novo na próxima execução. O cache também registra o que foi baixado.
- **Pré-formatado:** na ANA, um mês com 31 colunas vira 31 linhas, e texto vira número ou data. Na telemetria, leituras repetidas (mesmo horário) ficam uma vez só. Ficam de fora os resumos mensais que a ANA já calcula (máxima, mínima, média) e a data de inserção no sistema (`DataIns`). No porto, cada linha de tabela vira uma linha, guardando também o texto original da cota e da variação. O passo a passo, com os 5 primeiros registros de cada etapa, está no notebook [00_dados_brutos](../notebooks/00_dados_brutos.ipynb).
- **Padronizado:** as regras estão na seção [Como a série diária é montada](#como-a-série-diária-é-montada-padronização).

### Por que tantas consultas

- **A ANA não aceita pedidos grandes.** Pedir a série inteira de uma vez estoura o tempo limite do banco deles. Por isso o download pede um ano por vez para a régua e um mês por vez para o sensor.
- **Régua e sensor são serviços diferentes**, com formatos diferentes e períodos que se complementam.
- **O porto publica por mês**, numa página que mostra 6 meses de cada vez.
- **O serviço da ANA é instável.** Por isso há 4 consultas em paralelo, até 5 tentativas por consulta e o cache.

### Onde está o código de cada etapa

| Etapa | Arquivo | Funções |
| --- | --- | --- |
| Consultar a ANA e guardar no cache | [`ana.py`](../src/supplyrisk/ana.py) | `_get`, `xml_convencional`, `xml_telemetria` |
| XML da ANA → tabela pré-formatada | [`ana.py`](../src/supplyrisk/ana.py) | `tabela_xml`, `ler_convencional`, `ler_telemetria` |
| Baixar o site do porto e guardar no cache | [`porto.py`](../src/supplyrisk/porto.py) | `anos_disponiveis`, `html_ano` |
| HTML do porto → tabela pré-formatada | [`porto.py`](../src/supplyrisk/porto.py) | `ler_pagina`, `corrigir_datas` |
| Rodar tudo e gravar `data/raw/` | [`download.py`](../src/supplyrisk/download.py) | `main` |
| Pré-formatado → série diária (`data/processed/`) | [`serie.py`](../src/supplyrisk/serie.py) | `diaria_convencional`, `diaria_porto`, `limpar_telemetria`, `diaria_telemetria`, `serie_diaria` |

Os notebooks não têm cópia dessa lógica. Eles importam essas mesmas funções, então o que mostram é o que o pipeline faz.

## Dicionário de dados

### `raw/ana_convencional_<código>.parquet` — régua (ANA)

Uma linha por dia **e por versão**. O mesmo dia pode aparecer até quatro vezes: média bruta, média consistida, leitura das 7h e leitura das 17h.

| Coluna | Tipo | Significado | Exemplo |
| --- | --- | --- | --- |
| `data` | `datetime64` (dia) | Dia da medição | `2010-10-01` |
| `cota_cm` | `float64` | Nível do rio na régua, em **centímetros** (1770 = 17,70 m). Pode ter meio centímetro quando é média de leituras | `1669.5` |
| `status` | `Int64` (aceita vazio) | Marca de qualidade do valor naquele dia. Convenção do HidroWeb (**a confirmar com a ANA**): 0 = em branco, 1 = real, 2 = estimado, 3 = duvidoso, 4 = régua seca. Muitos dados brutos vêm sem status (`<NA>`) | `1` |
| `consistencia` | `int64` | Nível de revisão da ANA: **1** = bruto (como foi lido no campo), **2** = consistido (revisado e corrigido) | `2` |
| `media_diaria` | `bool` | **True** = valor é a média do dia. **False** = leitura avulsa feita num horário específico (ver `hora`) | `True` |
| `hora` | `int64` | Hora da leitura avulsa: **7** ou **17**. Vale **0** quando `media_diaria` é True | `7` |

### `raw/porto_manaus.parquet` — régua oficial do Porto de Manaus

Uma linha por dia.

| Coluna | Tipo | Significado | Exemplo |
| --- | --- | --- | --- |
| `data` | `datetime64` (dia) | Dia da medição, já com as correções de digitação aplicadas | `2024-10-09` |
| `cota_cm` | `float64` | Nível do rio na régua do porto, em **centímetros**, convertido de `cota_m_texto` | `1211.0` |
| `cota_m_texto` | `string` | A cota exatamente como o site publica, em metros | `12.11` |
| `variacao_texto` | `string` | A coluna "Encheu/Vazou (cm)" exatamente como publicada. Tem erros de digitação (`-1100` no lugar de `-11,00`) e anotações (`0.00 PARADO`). **Não é usada**, já que a variação pode ser calculada a partir da cota | `-6.00` |
| `data_publicada` | `datetime64` (dia) | A data como o site publicou, antes da correção. Igual a `data` quando não houve correção | `2024-10-09` |
| `correcao` | `string` | O que foi corrigido nesta linha e por quê. Vazio quando não houve correção | `dia publicado 20, data pela posição da linha` |
| `titulo` | `string` | Título do mês no site | `Outubro 2024` |
| `post_id` | `int64` | Identificador do mês no site, para rastrear a origem | `1298` |

### `raw/ana_telemetria_<código>.parquet` — sensor automático (ANA)

Uma linha por leitura (até 96 por dia).

| Coluna | Tipo | Significado | Exemplo |
| --- | --- | --- | --- |
| `datahora` | `datetime64` | Data e hora da leitura do sensor | `2023-10-01 00:15:00` |
| `nivel_cm` | `float64` | Nível do rio medido pelo sensor, em **centímetros**. É a mesma grandeza que `cota_cm` da régua | `1548.0` |
| `vazao` | `float64` | Volume de água que passa, em **m³/s**. Vazio (`NaN`) em Manaus; preenchido em Manacapuru | `91116.58` |
| `chuva` | `float64` | Chuva medida no pluviômetro da estação, em **mm** (provavelmente o acumulado do intervalo de 15 min; a confirmar). Não é usada no estudo por enquanto | `0.0` |

### `processed/cotas_diarias.parquet` — série padronizada

Uma linha por estação e por dia, sem buracos no calendário: dias sem medição aparecem com `cota_cm` vazio.

| Coluna | Tipo | Significado | Exemplo |
| --- | --- | --- | --- |
| `data` | `datetime64` (dia) | Dia | `2024-10-09` |
| `estacao` | `int64` | Código ANA da estação: **14990000** = Manaus, **14100000** = Manacapuru | `14990000` |
| `cota_cm` | `float64` | Nível do rio no dia, em **centímetros**. `NaN` quando nenhuma fonte tem dado | `1211.0` |
| `fonte` | `string` | De onde veio o valor: `convencional_consistida`, `porto_manaus`, `convencional_bruta`, `convencional_leituras` ou `telemetria`. Vazio quando `cota_cm` é `NaN` | `porto_manaus` |

## Como a série diária é montada (padronização)

Código: [`src/supplyrisk/serie.py`](../src/supplyrisk/serie.py)

Para cada dia, usa-se a melhor fonte disponível, nesta ordem:

1. ANA, régua consistida
2. Porto de Manaus, régua oficial (só Manaus)
3. ANA, régua bruta (média diária)
4. ANA, régua bruta (média das leituras das 7h e 17h)
5. ANA, sensor (média do dia)

A coluna `fonte` registra de onde veio cada valor.

**Resultado:**

- **Manaus:** completa de 15/09/1902 a hoje, **sem nenhum dia vazio**. Usa a régua consistida da ANA até 2014 e o porto daí em diante. O sensor não chega a ser usado.
- **Manacapuru:** de 1972 a hoje. Usa a régua da ANA (consistida até 2023, bruta em 2024–2025) e o sensor a partir de outubro de 2025. São 53 dias vazios.

**Limpeza do sensor**, quando ele é usado:

- descarta leituras vazias ou iguais a zero;
- descarta picos que se afastam mais de 30 cm da mediana das 6 horas em volta;
- aceita o dia se ele tiver ao menos **2 leituras**. Como o rio muda devagar, 2 leituras bastam, o mesmo que a régua (7h e 17h);
- descarta o dia cuja média se afasta mais de 50 cm da mediana dos 7 dias em volta. Isso pega erros que o filtro de 6 h não vê quando há poucas leituras.

**Lacunas não são preenchidas.** Dia sem dado fica vazio (`NaN`). Preencher uma lacuna exigiria usar valores posteriores a ela, e cada previsão do estudo só pode usar o que se sabia naquele dia.

## Problemas conhecidos

Encontrados na exploração ([notebook 01](../notebooks/01_exploracao_dados.ipynb)), em 06/10/2026:

- **O sensor da ANA em Manaus não bate com a régua oficial.** A diferença sensor − porto tem mediana de −2 cm, mas varia muito: só 29% dos dias ficam a até 2 cm, e há dias com −42 cm. Exemplo: em 09/10/2024 o porto registrou 12,11 m (o recorde), e o sensor marcava 12,31 m. **Resolvido:** em Manaus, a série usa o porto de 2015 em diante e o sensor fica de fora.
- **Manacapuru:** régua e sensor coincidem (mediana 0 cm), mas o sensor tem valores absurdos em 2008–2014 (até +8 m). Isso não afeta a série padronizada, porque nesses anos a régua tem prioridade. Em 2024–2025 a régua de Manacapuru só existe na versão bruta (não revisada), e depois de setembro de 2025 só há o sensor.
- **Significado dos códigos de `status` da ANA:** ainda a confirmar com a documentação oficial.

## Como regenerar

```bash
uv run python -m supplyrisk.download   # baixa da ANA e do porto → data/raw
uv run python -m supplyrisk.serie      # padroniza → data/processed
```
