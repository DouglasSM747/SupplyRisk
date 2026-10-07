"""Executa o braço A: baselines e Jev, por período.

Ordem de execução (o pré-registro fica entre a validação e o teste):
    uv run python -m supplyrisk.experimento baselines validacao
    uv run python -m supplyrisk.experimento jev validacao
    # -> escrever e commitar PREREGISTRATION.md
    uv run python -m supplyrisk.experimento baselines teste
    uv run python -m supplyrisk.experimento jev teste
    uv run python -m supplyrisk.experimento baselines final
    uv run python -m supplyrisk.experimento jev final

As previsões ficam em data/resultados/previsoes_<metodo>_<periodo>.parquet.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from supplyrisk import amostras as am
from supplyrisk import avaliacao as av
from supplyrisk import baselines as bl

RESULTADOS = Path(__file__).resolve().parents[2] / "data" / "resultados"

VARIANTES = {
    # nome: (anos de treino, features)
    "principal": (("treino",), bl.FEATURES_MANAUS + bl.FEATURES_MANACAPURU),
    "so_manaus": (("treino_longo", "treino"), bl.FEATURES_MANAUS),
}

GRADES = {
    "analogos": [{"k": k} for k in (5, 10, 15)],
    "logistica": [{"c": c} for c in (0.01, 0.1, 1.0, 10.0)],
    "gradient_boosting": [{"num_leaves": nl, "n_estimators": ne} for nl in (7, 15) for ne in (100, 300)],
}


def _construir(nome: str, features: list[str], serie: pd.Series, **params):
    if nome == "tendencia":
        return bl.Tendencia()
    if nome == "climatologia":
        return bl.Climatologia()
    if nome == "analogos":
        return bl.Analogos(serie=serie, **params)
    if nome == "logistica":
        return bl.Logistica(features=features, **params)
    if nome == "gradient_boosting":
        return bl.GradientBoosting(features=features, **params)
    raise ValueError(nome)


METODOS = ("climatologia", "tendencia", "analogos", "logistica", "gradient_boosting")


def carregar_amostras() -> pd.DataFrame:
    return pd.read_parquet(am.ARQUIVO)


def escolher_hiperparametros(amostras: pd.DataFrame, serie: pd.Series) -> pd.DataFrame:
    """Para cada variante, método e tarefa: hiperparâmetros com menor Brier na validação."""
    linhas = []
    for variante, (periodos_treino, features) in VARIANTES.items():
        for (limiar, h), tarefa in amostras.groupby(["limiar_cm", "horizonte_dias"]):
            treino = tarefa[tarefa["periodo"].isin(periodos_treino)]
            validacao = tarefa[tarefa["periodo"] == "validacao"]
            for metodo in METODOS:
                for params in GRADES.get(metodo, [{}]):
                    modelo = _construir(metodo, features, serie, **params).ajustar(treino)
                    b = av.brier(validacao["rotulo"], modelo.prever(validacao))
                    linhas.append({"variante": variante, "metodo": metodo, "limiar_cm": limiar,
                                   "horizonte_dias": h, "params": params, "brier_validacao": b})
    tabela = pd.DataFrame(linhas)
    melhor = tabela.loc[tabela.groupby(["variante", "metodo", "limiar_cm", "horizonte_dias"])["brier_validacao"].idxmin()]
    return melhor.reset_index(drop=True)


def prever_baselines(amostras: pd.DataFrame, serie: pd.Series, escolhas: pd.DataFrame, periodo: str) -> pd.DataFrame:
    """Previsões de todos os baselines para um período (modelos ajustados só no treino)."""
    partes = []
    for (limiar, h), tarefa in amostras.groupby(["limiar_cm", "horizonte_dias"]):
        alvo = tarefa[tarefa["periodo"] == periodo]
        if alvo.empty:
            continue
        saida = alvo[["data", "ano", "periodo", "limiar_cm", "horizonte_dias", "rotulo"]].copy()
        for variante, (periodos_treino, features) in VARIANTES.items():
            treino = tarefa[tarefa["periodo"].isin(periodos_treino)]
            for metodo in METODOS:
                linha = escolhas[(escolhas["variante"] == variante) & (escolhas["metodo"] == metodo)
                                 & (escolhas["limiar_cm"] == limiar) & (escolhas["horizonte_dias"] == h)].iloc[0]
                modelo = _construir(metodo, features, serie, **linha["params"]).ajustar(treino)
                saida[f"{metodo}__{variante}"] = modelo.prever(alvo)
        partes.append(saida)
    return pd.concat(partes, ignore_index=True)


def rodar_baselines(periodo: str) -> pd.DataFrame:
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    amostras = carregar_amostras()
    serie, _ = am.carregar_series()
    arquivo_escolhas = RESULTADOS / "hiperparametros.json"
    if arquivo_escolhas.exists():
        escolhas = pd.read_json(arquivo_escolhas)
    else:
        escolhas = escolher_hiperparametros(amostras, serie)
        escolhas.to_json(arquivo_escolhas, orient="records", indent=1, force_ascii=False)
    previsoes = prever_baselines(amostras, serie, escolhas, periodo)
    previsoes.to_parquet(RESULTADOS / f"previsoes_baselines_{periodo}.parquet")
    return previsoes


def resumo(previsoes: pd.DataFrame, colunas: list[str]) -> pd.DataFrame:
    linhas = []
    for (limiar, h), g in previsoes.groupby(["limiar_cm", "horizonte_dias"]):
        ref = g.get("climatologia__principal")
        for c in colunas:
            m = av.metricas(g["rotulo"], g[c], ref)
            linhas.append({"limiar_cm": limiar, "horizonte_dias": h, "metodo": c, **m})
    return pd.DataFrame(linhas)


def main() -> None:
    alvo, periodo = sys.argv[1], sys.argv[2]
    if alvo == "baselines":
        previsoes = rodar_baselines(periodo)
        colunas = [c for c in previsoes.columns if "__" in c]
        if periodo == "validacao":
            print(resumo(previsoes, colunas).round(4).to_string())
        else:
            print(f"{len(previsoes)} previsões gravadas para {periodo}.")
    elif alvo == "jev":
        from supplyrisk import jev

        jev.rodar(periodo)
    else:
        raise SystemExit(f"alvo desconhecido: {alvo}")


if __name__ == "__main__":
    main()
