"""Cota oficial do Rio Negro publicada pelo Porto de Manaus (régua do porto), de 2000 até hoje.

É a referência usada pelas armadoras (limiares de 17,70 m etc.) e pelos recordes divulgados
(p. ex. 12,11 m em 09/10/2024). A partir de 2015 a ANA só tem o sensor telemétrico, que chega
a divergir ~20 cm dessa régua, por isso o porto é a fonte oficial no período recente.

O site (WordPress + JetEngine) publica uma tabela por mês. A página de nível aceita o filtro
por ano na URL (JetSmartFilters) e mostra 6 meses por página.

Uso: uv run python -m supplyrisk.porto
"""

from __future__ import annotations

import calendar
import gzip
import re
import time
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd
import requests
from lxml import html

SITE = "https://portodemanaus.com.br"
PAGINA_NIVEL = f"{SITE}/nivel-do-rio-negro/"
RAIZ = Path(__file__).resolve().parents[2]
CACHE_DIR = RAIZ / "data" / "cache" / "porto"
RAW_DIR = RAIZ / "data" / "raw"
HEADERS = {"User-Agent": "Mozilla/5.0 (pesquisa academica; supplyrisk)"}

MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def anos_disponiveis() -> dict[int, int]:
    """{ano: id do termo 'ano' no WordPress}."""
    resp = requests.get(f"{SITE}/wp-json/wp/v2/ano", params={"per_page": 100}, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    return {int(t["name"]): t["id"] for t in resp.json()}


def html_ano(ano: int, termo_id: int, pagina: int) -> bytes:
    """HTML da página de nível filtrada por ano. Anos encerrados ficam em cache."""
    cache = CACHE_DIR / f"{ano}_p{pagina}.html.gz"
    usar_cache = ano < date.today().year
    if usar_cache and cache.exists():
        return gzip.decompress(cache.read_bytes())

    params = {"jsf": "jet-engine:result", "tax": f"ano:{termo_id}", "pagenum": pagina}
    for tentativa in range(5):
        try:
            resp = requests.get(PAGINA_NIVEL, params=params, headers=HEADERS, timeout=90)
            if resp.status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(5 * 2**tentativa)
    else:
        raise RuntimeError(f"Falha ao baixar {ano} página {pagina}")

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(gzip.compress(resp.content))
    time.sleep(1)  # site institucional: sem pressa
    return resp.content


def ler_pagina(conteudo: bytes, ano_filtro: int) -> pd.DataFrame:
    """Extrai as tabelas mensais de uma página. Uma linha por linha de tabela, valores como publicados.

    O ano vem do filtro da URL (a classificação do próprio site), não do título: há títulos errados,
    como abril de 2026 publicado como "Abril 2023".
    """
    arvore = html.fromstring(conteudo)
    linhas = []
    for item in arvore.xpath('//*[contains(@class,"jet-listing-grid__item") and @data-post-id]'):
        tabelas = item.xpath(".//table")
        if len(tabelas) != 1:
            continue
        textos = [t.strip() for t in item.xpath(".//text()") if t.strip()]
        titulo = textos[0]  # p. ex. "Outubro 2024", "SETEMBRO 2024"; às vezes sem ano
        normalizado = _sem_acento(titulo).lower()
        mes = next(numero for nome, numero in MESES.items() if nome in normalizado)

        ordem = 0
        for tr in tabelas[0].xpath(".//tr")[1:]:
            celulas = [" ".join(td.xpath(".//text()")).strip() for td in tr.xpath("./td")]
            if len(celulas) < 2 or not celulas[0].isdigit() or not celulas[1]:
                continue
            ordem += 1
            linhas.append(
                {
                    "ano": ano_filtro,
                    "mes": mes,
                    "dia_publicado": int(celulas[0]),
                    "linha": ordem,
                    "cota_m_texto": celulas[1],
                    "variacao_texto": celulas[2] if len(celulas) > 2 else None,
                    "titulo": titulo,
                    "post_id": int(item.get("data-post-id")),
                }
            )
    return pd.DataFrame(linhas)


def corrigir_datas(bruto: pd.DataFrame) -> pd.DataFrame:
    """Monta a data de cada linha e corrige erros de digitação do site, registrando cada correção.

    - Título com ano diferente do ano em que o site classifica o mês: vale a classificação.
    - Dias fora de sequência (p. ex. 18, 20, 20, 21) num mês com o número certo de linhas:
      a data passa a ser a posição da linha.
    """
    partes = []
    for _, mes in bruto.groupby("post_id", sort=False):
        mes = mes.copy()
        ano, numero_mes = int(mes["ano"].iloc[0]), int(mes["mes"].iloc[0])
        dias_no_mes = calendar.monthrange(ano, numero_mes)[1]
        correcoes = pd.Series("", index=mes.index)

        ano_titulo = re.search(r"(19|20)\d{2}", mes["titulo"].iloc[0])
        if ano_titulo and int(ano_titulo.group()) != ano:
            correcoes += f"título diz {ano_titulo.group()}, site classifica em {ano}; "

        sequencia_ok = mes["dia_publicado"].tolist() == list(range(1, len(mes) + 1))
        if not sequencia_ok and len(mes) == dias_no_mes:
            mes["dia"] = mes["linha"]
        else:
            mes["dia"] = mes["dia_publicado"]
        mudou = mes["dia"] != mes["dia_publicado"]
        correcoes[mudou] += "dia publicado " + mes.loc[mudou, "dia_publicado"].astype(str) + ", data pela posição da linha; "

        mes["correcao"] = correcoes.str.rstrip("; ").replace("", None)
        partes.append(mes)

    df = pd.concat(partes, ignore_index=True)
    df["data"] = pd.to_datetime(dict(year=df["ano"], month=df["mes"], day=df["dia"]))
    df["data_publicada"] = pd.to_datetime(
        dict(year=df["ano"], month=df["mes"], day=df["dia_publicado"]), errors="coerce"
    )
    return df


def baixar() -> pd.DataFrame:
    partes = []
    for ano, termo_id in sorted(anos_disponiveis().items()):
        vistos: set[int] = set()
        for pagina in range(1, 4):  # 12 meses, 6 por página
            df = ler_pagina(html_ano(ano, termo_id, pagina), ano)
            novos = df[~df["post_id"].isin(vistos)] if not df.empty else df
            if novos.empty:
                break
            vistos.update(novos["post_id"])
            partes.append(novos)
        print(f"  {ano}: {len(vistos)} meses")

    bruto = corrigir_datas(pd.concat(partes, ignore_index=True))
    bruto["cota_cm"] = pd.to_numeric(bruto["cota_m_texto"].str.replace(",", "."), errors="coerce") * 100
    bruto["cota_cm"] = bruto["cota_cm"].round(1)
    colunas = ["data", "cota_cm", "cota_m_texto", "variacao_texto", "data_publicada", "correcao", "titulo", "post_id"]
    return bruto[colunas].sort_values("data", ignore_index=True)


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    bruto = baixar()
    bruto.to_parquet(RAW_DIR / "porto_manaus.parquet")
    print(f"{len(bruto)} dias, de {bruto['data'].min():%Y-%m-%d} a {bruto['data'].max():%Y-%m-%d}")
    duplicados = bruto["data"].duplicated(keep=False).sum()
    sem_valor = bruto["cota_cm"].isna().sum()
    print(f"datas repetidas: {duplicados}; valores não numéricos: {sem_valor}")


if __name__ == "__main__":
    main()
