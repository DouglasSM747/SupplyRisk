"""Download de séries de cota da ANA pelo serviço público ServiceANA (sem credencial).

Duas fontes, com coberturas complementares:
- HidroSerieHistorica: série convencional diária (leitura de régua), consistida ou bruta.
  Manaus (14990000) vai de 1902 a 2014; Manacapuru (14100000) começa em 1972.
- DadosHidrometeorologicos: telemetria a cada 15 minutos, cobre de ~2014 até o presente.

As respostas XML ficam em cache (gzip) em data/cache/ana, então rodar de novo é barato.
"""

from __future__ import annotations

import calendar
import gzip
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "http://telemetriaws1.ana.gov.br/ServiceANA.asmx"
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "ana"

ESTACOES = {
    14990000: "Manaus (Rio Negro)",
    14100000: "Manacapuru (Rio Solimões)",
}

# Períodos que terminam há menos que isso ainda podem receber dados novos: não usar cache.
_JANELA_SEM_CACHE = timedelta(days=45)


def _get(endpoint: str, params: dict, cache_path: Path, fim: date) -> bytes:
    usar_cache = date.today() - fim > _JANELA_SEM_CACHE
    if usar_cache and cache_path.exists():
        return gzip.decompress(cache_path.read_bytes())

    for tentativa in range(5):
        try:
            resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=180)
            # O serviço devolve 500 quando o banco estoura o timeout; vale tentar de novo.
            if resp.status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(5 * 2**tentativa)
    else:
        raise RuntimeError(f"Falha ao consultar {endpoint} {params}")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(gzip.compress(resp.content))
    return resp.content


def tabela_xml(xml: bytes, tag: str) -> pd.DataFrame:
    """O XML da ANA como tabela, sem nenhuma conversão: um registro por linha, todos os campos como texto."""
    registros = [el for el in ET.fromstring(xml).iter() if el.tag == tag]
    return pd.DataFrame(
        [{campo.tag: (campo.text or "").strip() or None for campo in reg} for reg in registros]
    )


# ---------------------------------------------------------------- convencional


def xml_convencional(codigo: int, ano: int) -> bytes:
    """Resposta original da ANA (HidroSerieHistorica) para um ano: um registro por mês."""
    inicio, fim = date(ano, 1, 1), date(ano, 12, 31)
    return _get(
        "HidroSerieHistorica",
        {
            "codEstacao": codigo,
            "dataInicio": inicio.strftime("%d/%m/%Y"),
            "dataFim": fim.strftime("%d/%m/%Y"),
            "tipoDados": 1,  # cotas
            "nivelConsistencia": "",
        },
        CACHE_DIR / "convencional" / f"{codigo}_{ano}.xml.gz",
        fim,
    )


def ler_convencional(xml: bytes) -> pd.DataFrame:
    """Converte a resposta mensal (colunas Cota01..Cota31) em uma linha por dia.

    Colunas: data, cota_cm, status, consistencia, media_diaria, hora. Os valores não são alterados.
    """
    meses = tabela_xml(xml, "SerieHistorica")
    linhas = []
    for _, reg in meses.iterrows():
        datahora = pd.Timestamp(reg["DataHora"])
        dias_no_mes = calendar.monthrange(datahora.year, datahora.month)[1]
        for dia in range(1, dias_no_mes + 1):
            valor = reg.get(f"Cota{dia:02d}")
            if valor is None or pd.isna(valor):
                continue
            status = reg.get(f"Cota{dia:02d}Status")
            linhas.append(
                (
                    date(datahora.year, datahora.month, dia),
                    float(valor),
                    int(status) if status is not None and not pd.isna(status) else None,
                    int(reg["NivelConsistencia"]),
                    reg["MediaDiaria"] == "1",
                    datahora.hour,
                )
            )

    df = pd.DataFrame(linhas, columns=["data", "cota_cm", "status", "consistencia", "media_diaria", "hora"])
    df["data"] = pd.to_datetime(df["data"])
    return df.astype({"status": "Int64", "consistencia": "int64", "hora": "int64"})


def convencional_ano(codigo: int, ano: int) -> pd.DataFrame:
    return ler_convencional(xml_convencional(codigo, ano))


# ------------------------------------------------------------------ telemetria


def xml_telemetria(codigo: int, ano: int, mes: int) -> bytes:
    """Resposta original da ANA (DadosHidrometeorologicos) para um mês: uma leitura a cada 15 min."""
    inicio = date(ano, mes, 1)
    fim = date(ano, mes, calendar.monthrange(ano, mes)[1])
    return _get(
        "DadosHidrometeorologicos",
        {
            "codEstacao": codigo,
            "DataInicio": inicio.strftime("%d/%m/%Y"),
            "DataFim": fim.strftime("%d/%m/%Y"),
        },
        CACHE_DIR / "telemetria" / f"{codigo}_{ano}{mes:02d}.xml.gz",
        fim,
    )


def ler_telemetria(xml: bytes) -> pd.DataFrame:
    """Converte as leituras em tabela tipada. Colunas: datahora, nivel_cm, vazao, chuva."""
    leituras = tabela_xml(xml, "DadosHidrometereologicos")
    colunas = {"DataHora": "datahora", "Nivel": "nivel_cm", "Vazao": "vazao", "Chuva": "chuva"}
    if leituras.empty:
        return pd.DataFrame(columns=list(colunas.values())).astype(
            {"datahora": "datetime64[ns]", "nivel_cm": "float64", "vazao": "float64", "chuva": "float64"}
        )

    df = leituras.reindex(columns=list(colunas)).rename(columns=colunas)
    df["datahora"] = pd.to_datetime(df["datahora"])
    # Sem o cast, uma coluna toda vazia (vazão em Manaus) viraria texto.
    for col in ("nivel_cm", "vazao", "chuva"):
        df[col] = pd.to_numeric(df[col]).astype("float64")
    return df.sort_values("datahora", ignore_index=True)


def telemetria_mes(codigo: int, ano: int, mes: int) -> pd.DataFrame:
    return ler_telemetria(xml_telemetria(codigo, ano, mes))
