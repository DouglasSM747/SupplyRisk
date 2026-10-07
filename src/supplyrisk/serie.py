"""Padroniza as séries brutas (ANA e Porto de Manaus) em uma série diária única por estação.

Prioridade por dia:
1. ANA convencional consistida (média diária)
2. Porto de Manaus, régua oficial (só Manaus, 2000 em diante). É a mesma régua da ANA
   (diferença mediana 0 cm em 2000-2014) e a única leitura oficial depois de 2014.
3. ANA convencional bruta (média diária)
4. ANA convencional bruta (média das leituras avulsas do dia, p. ex. 7h e 17h)
5. ANA telemetria (média diária das leituras de 15 min, após limpeza). Diverge da régua em
   até ~40 cm, por isso fica por último.

Dias sem nenhuma fonte ficam como NaN. Não há interpolação aqui: preencher lacunas usaria
valores do futuro, e o estado de cada previsão só pode usar o que se sabia naquele dia.

Uso: uv run python -m supplyrisk.serie
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from supplyrisk import ana

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

MANAUS = 14990000

# Telemetria: a frequência variou ao longo dos anos (de 1-2 leituras/dia nos primeiros anos a 96,
# uma a cada 15 min). O rio muda devagar, então 2 leituras bastam, como as 7h e 17h da régua.
MIN_LEITURAS_DIA = 2
# Leitura que se afasta mais que isso da mediana móvel de 6 h é tratada como pico espúrio.
LIMIAR_PICO_CM = 30
# Com poucas leituras por dia o filtro de 6 h não pega nada; por isso também se descarta o dia
# cuja média se afasta mais que isso da mediana dos 7 dias em volta (o rio varia até ~30 cm/dia).
LIMIAR_SALTO_DIA_CM = 50


def diaria_convencional(bruto: pd.DataFrame) -> pd.DataFrame:
    medias = bruto[bruto["media_diaria"]]
    leituras = bruto[~bruto["media_diaria"]]

    consistida = medias[medias["consistencia"] == 2].set_index("data")["cota_cm"]
    bruta = medias[medias["consistencia"] == 1].groupby("data")["cota_cm"].mean()
    avulsa = leituras.groupby("data")["cota_cm"].mean()

    partes = [
        consistida.to_frame().assign(fonte="convencional_consistida"),
        bruta.to_frame().assign(fonte="convencional_bruta"),
        avulsa.to_frame().assign(fonte="convencional_leituras"),
    ]
    combinada = pd.concat(partes)
    combinada = combinada[~combinada.index.duplicated(keep="first")]
    combinada.index = pd.to_datetime(combinada.index)
    return combinada.sort_index()


def limpar_telemetria(bruto: pd.DataFrame) -> pd.DataFrame:
    df = bruto.dropna(subset=["nivel_cm"]).set_index("datahora").sort_index()
    df = df[df["nivel_cm"] > 0]
    mediana = df["nivel_cm"].rolling("6h", center=True).median()
    return df[(df["nivel_cm"] - mediana).abs() <= LIMIAR_PICO_CM]


def diaria_telemetria(bruto: pd.DataFrame) -> pd.DataFrame:
    limpo = limpar_telemetria(bruto)
    por_dia = limpo["nivel_cm"].resample("D").agg(["mean", "count"])
    por_dia = por_dia[por_dia["count"] >= MIN_LEITURAS_DIA]
    mediana_semana = por_dia["mean"].rolling("7D", center=True).median()
    por_dia = por_dia[(por_dia["mean"] - mediana_semana).abs() <= LIMIAR_SALTO_DIA_CM]
    return por_dia.rename(columns={"mean": "cota_cm"})[["cota_cm"]].assign(fonte="telemetria")


def diaria_porto() -> pd.DataFrame:
    porto = pd.read_parquet(RAW_DIR / "porto_manaus.parquet").set_index("data")
    return porto[["cota_cm"]].assign(fonte="porto_manaus")


def serie_diaria(codigo: int) -> pd.DataFrame:
    conv = diaria_convencional(pd.read_parquet(RAW_DIR / f"ana_convencional_{codigo}.parquet"))
    tele = diaria_telemetria(pd.read_parquet(RAW_DIR / f"ana_telemetria_{codigo}.parquet"))

    consistida = conv[conv["fonte"] == "convencional_consistida"]
    outras_conv = conv[conv["fonte"] != "convencional_consistida"]
    porto = diaria_porto() if codigo == MANAUS else None
    combinada = pd.concat([consistida, porto, outras_conv, tele])
    combinada = combinada[~combinada.index.duplicated(keep="first")].sort_index()

    calendario = pd.date_range(combinada.index.min(), combinada.index.max(), freq="D")
    combinada = combinada.reindex(calendario)
    combinada.index.name = "data"
    return combinada.reset_index().assign(estacao=codigo)[["data", "estacao", "cota_cm", "fonte"]]


def sobreposicao(codigo: int) -> pd.DataFrame:
    """Dias com convencional e telemetria ao mesmo tempo, para checar se as duas batem."""
    conv = diaria_convencional(pd.read_parquet(RAW_DIR / f"ana_convencional_{codigo}.parquet"))
    tele = diaria_telemetria(pd.read_parquet(RAW_DIR / f"ana_telemetria_{codigo}.parquet"))
    juntas = conv[["cota_cm"]].join(tele[["cota_cm"]], lsuffix="_conv", rsuffix="_tele", how="inner")
    return juntas.assign(diferenca_cm=juntas["cota_cm_tele"] - juntas["cota_cm_conv"])


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    series = pd.concat([serie_diaria(codigo) for codigo in ana.ESTACOES], ignore_index=True)
    series.to_parquet(PROCESSED_DIR / "cotas_diarias.parquet")

    for codigo, nome in ana.ESTACOES.items():
        s = series[series["estacao"] == codigo]
        print(f"{codigo} — {nome}: {s['data'].min():%Y-%m-%d} a {s['data'].max():%Y-%m-%d}")
        print(s["fonte"].value_counts(dropna=False).to_string())
        dif = sobreposicao(codigo)["diferenca_cm"]
        if not dif.empty:
            print(f"  sobreposição: {len(dif)} dias, diferença telemetria − convencional: "
                  f"mediana {dif.median():.1f} cm, p5 {dif.quantile(.05):.1f}, p95 {dif.quantile(.95):.1f}")


if __name__ == "__main__":
    main()
