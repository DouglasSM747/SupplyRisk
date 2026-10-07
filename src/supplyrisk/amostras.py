"""Monta as amostras do braço A: uma linha por (dia de previsão, limiar, horizonte).

Dia de previsão t: de 1º de julho até o dia do mínimo anual (janela jul-dez), apenas enquanto a cota
de Manaus em t está ACIMA do limiar. Depois do cruzamento a pergunta "vai cruzar?" seria trivial.

Rótulo: 1 se a cota de Manaus fica <= limiar em algum dia de t+1 a t+H. `minimo_futuro_cm` guarda o
mínimo observado nesse intervalo (é alvo, nunca feature).

Features: só usam dados até t (inclusive). A climatologia de referência vem dos anos de treino
(1972-1999), fixa para todos os anos.

Uso: uv run python -m supplyrisk.amostras
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from supplyrisk import serie

MANAUS, MANACAPURU = 14990000, 14100000
LIMIARES_CM = (1770, 1500)
HORIZONTES = (14, 30)

PERIODOS = {
    "treino": (1972, 1999),
    "treino_longo": (1902, 1999),  # variante só com Manaus
    "validacao": (2000, 2014),
    "teste": (2015, 2024),
    "final": (2025, 2026),
}
ANOS_CLIMATOLOGIA = PERIODOS["treino"]

ARQUIVO = serie.PROCESSED_DIR / "amostras.parquet"


def periodo_do_ano(ano: int) -> str:
    for nome in ("treino", "validacao", "teste", "final"):
        inicio, fim = PERIODOS[nome]
        if inicio <= ano <= fim:
            return nome
    return "treino_longo"  # 1902-1971: só entra na variante com treino longo


def carregar_series() -> tuple[pd.Series, pd.Series]:
    cotas = pd.read_parquet(serie.PROCESSED_DIR / "cotas_diarias.parquet")
    manaus = cotas[cotas["estacao"] == MANAUS].set_index("data")["cota_cm"].asfreq("D")
    manacapuru = cotas[cotas["estacao"] == MANACAPURU].set_index("data")["cota_cm"].asfreq("D")
    return manaus, manacapuru


def climatologia(manaus: pd.Series) -> pd.DataFrame:
    """Mediana e percentis 10/90 da cota por dia do ano, nos anos de referência."""
    inicio, fim = ANOS_CLIMATOLOGIA
    ref = manaus[(manaus.index.year >= inicio) & (manaus.index.year <= fim)]
    doy = np.minimum(ref.index.dayofyear, 365)
    return ref.groupby(doy).quantile([0.1, 0.5, 0.9]).unstack().rename(
        columns={0.1: "clima_p10", 0.5: "clima_mediana", 0.9: "clima_p90"}
    )


def pico_da_cheia(manaus: pd.Series) -> pd.DataFrame:
    """Para cada dia: maior cota desde 1º de março do mesmo ano até o dia, e há quantos dias foi."""
    partes = []
    for ano, s in manaus.groupby(manaus.index.year):
        s = s[s.index >= pd.Timestamp(ano, 3, 1)]
        maximo = s.cummax()
        data_max = s.index.to_series().where(s >= maximo).ffill()
        partes.append(pd.DataFrame({
            "pico_cheia_cm": maximo,
            "dias_desde_pico": (s.index - pd.DatetimeIndex(data_max)).days,
        }, index=s.index))
    return pd.concat(partes)


def features_do_dia(manaus: pd.Series, manacapuru: pd.Series, clima: pd.DataFrame) -> pd.DataFrame:
    """Features para todos os dias da série (cada uma usa só o passado de cada dia)."""
    f = pd.DataFrame(index=manaus.index)
    f["nivel_cm"] = manaus
    for d in (7, 14, 30):
        f[f"var_{d}d_cm"] = manaus - manaus.shift(d)
    f["taxa_7d_cm_dia"] = f["var_7d_cm"] / 7
    f = f.join(pico_da_cheia(manaus))

    doy = np.minimum(manaus.index.dayofyear, 365)
    for coluna in clima:
        f[coluna] = clima[coluna].reindex(doy).to_numpy()
    f["anomalia_cm"] = f["nivel_cm"] - f["clima_mediana"]
    inicio_vazante = pd.to_datetime(pd.DataFrame({"year": manaus.index.year, "month": 7, "day": 1}))
    f["dia_vazante"] = (manaus.index - pd.DatetimeIndex(inicio_vazante)).days

    f["mcp_nivel_cm"] = manacapuru.reindex(manaus.index)
    f["mcp_var_7d_cm"] = f["mcp_nivel_cm"] - f["mcp_nivel_cm"].shift(7)
    f["mcp_var_14d_cm"] = f["mcp_nivel_cm"] - f["mcp_nivel_cm"].shift(14)
    return f


def montar(hoje: date | None = None) -> pd.DataFrame:
    hoje = pd.Timestamp(hoje or date.today())
    manaus, manacapuru = carregar_series()
    feats = features_do_dia(manaus, manacapuru, climatologia(manaus))

    linhas = []
    for ano in range(1902, hoje.year + 1):
        janela = manaus[f"{ano}-07-01":f"{ano}-12-31"].dropna()
        if janela.empty:
            continue
        fim_amostra = janela.idxmin() if ano < hoje.year else janela.index.max()
        for t in janela[:fim_amostra].index:
            nivel = manaus[t]
            for limiar in LIMIARES_CM:
                if nivel <= limiar:
                    continue
                for h in HORIZONTES:
                    futuro = manaus[t + pd.Timedelta(days=1): t + pd.Timedelta(days=h)]
                    cruzou = bool((futuro <= limiar).any())
                    # Ano corrente: só vale se o horizonte inteiro já foi observado (ou já cruzou).
                    conhecido = (t + pd.Timedelta(days=h) <= hoje) or cruzou
                    if not conhecido:
                        continue
                    if len(futuro.dropna()) < h and not cruzou:
                        continue
                    linhas.append((t, ano, limiar, h, int(cruzou), futuro.min()))

    amostras = pd.DataFrame(linhas, columns=["data", "ano", "limiar_cm", "horizonte_dias", "rotulo", "minimo_futuro_cm"])
    amostras["periodo"] = amostras["ano"].map(periodo_do_ano)
    amostras = amostras.join(feats, on="data")
    amostras["distancia_cm"] = amostras["nivel_cm"] - amostras["limiar_cm"]
    queda = (-amostras["taxa_7d_cm_dia"]).clip(lower=0.1)
    amostras["dias_ate_limiar_no_ritmo"] = (amostras["distancia_cm"] / queda).clip(upper=365)
    return amostras


def main() -> None:
    amostras = montar()
    amostras.to_parquet(ARQUIVO)
    resumo = amostras.groupby(["periodo", "limiar_cm", "horizonte_dias"]).agg(
        amostras=("rotulo", "size"), anos=("ano", "nunique"), taxa_positivos=("rotulo", "mean")
    )
    print(resumo.round(3).to_string())


if __name__ == "__main__":
    main()
