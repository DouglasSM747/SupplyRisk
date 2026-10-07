"""Métricas do estudo.

- Brier score (principal), log-loss, AUC e Brier skill score (BSS) contra a climatologia.
- Intervalos de confiança por bootstrap em blocos de ANO: dias do mesmo ano são correlacionados,
  então a unidade reamostrada é o ano inteiro.
- Antecedência: dias entre o início do alerta sustentado (P >= 0,5 até o cruzamento) e o cruzamento.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

LIMIAR_ALERTA = 0.5
N_BOOTSTRAP = 2000


def brier(y, p) -> float:
    y, p = np.asarray(y, float), np.asarray(p, float)
    return float(np.mean((p - y) ** 2))


def log_loss(y, p) -> float:
    y, p = np.asarray(y, float), np.clip(np.asarray(p, float), 1e-3, 1 - 1e-3)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def auc(y, p) -> float:
    y = np.asarray(y)
    return float(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else np.nan


def metricas(y, p, p_ref=None) -> dict:
    saida = {"n": len(y), "positivos": int(np.sum(y)), "brier": brier(y, p), "log_loss": log_loss(y, p), "auc": auc(y, p)}
    if p_ref is not None:
        saida["bss_vs_climatologia"] = 1 - saida["brier"] / brier(y, p_ref)
    return saida


def bootstrap_por_ano(df: pd.DataFrame, coluna_a: str, coluna_b: str | None = None, semente: int = 42) -> dict:
    """IC 95% do Brier de `coluna_a` (e da diferença a - b, se b for dado), reamostrando anos."""
    rng = np.random.default_rng(semente)
    anos = df["ano"].unique()
    por_ano = {
        ano: (g["rotulo"].to_numpy(), g[coluna_a].to_numpy(), g[coluna_b].to_numpy() if coluna_b else None)
        for ano, g in df.groupby("ano")
    }
    valores_a, diferencas = [], []
    for _ in range(N_BOOTSTRAP):
        amostra = rng.choice(anos, size=len(anos), replace=True)
        y = np.concatenate([por_ano[a][0] for a in amostra])
        pa = np.concatenate([por_ano[a][1] for a in amostra])
        valores_a.append(brier(y, pa))
        if coluna_b:
            pb = np.concatenate([por_ano[a][2] for a in amostra])
            diferencas.append(brier(y, pa) - brier(y, pb))
    saida = {"brier_ic95": tuple(np.percentile(valores_a, [2.5, 97.5]).round(4))}
    if coluna_b:
        d = np.array(diferencas)
        saida["diferenca_brier"] = brier(df["rotulo"], df[coluna_a]) - brier(df["rotulo"], df[coluna_b])
        saida["diferenca_ic95"] = tuple(np.percentile(d, [2.5, 97.5]).round(4))
        saida["p_a_melhor"] = float(np.mean(d < 0))
    return saida


def confiabilidade(y, p, bins: int = 10) -> pd.DataFrame:
    """Tabela do diagrama de confiabilidade: probabilidade média prevista × frequência observada."""
    df = pd.DataFrame({"y": y, "p": p})
    df["faixa"] = pd.cut(df["p"], np.linspace(0, 1, bins + 1), include_lowest=True)
    return df.groupby("faixa", observed=True).agg(n=("y", "size"), prevista=("p", "mean"), observada=("y", "mean"))


def primeiros_cruzamentos(serie: pd.Series, limiar: float) -> dict[int, pd.Timestamp]:
    """{ano: primeiro dia de jul-dez com cota <= limiar}, só para anos em que houve cruzamento."""
    vazante = serie[serie.index.month >= 7]
    abaixo = vazante[vazante <= limiar]
    return abaixo.groupby(abaixo.index.year).apply(lambda s: s.index.min()).to_dict()


def antecedencia(df: pd.DataFrame, coluna: str, cruzamentos: dict[int, pd.Timestamp]) -> pd.DataFrame:
    """Para cada ano com cruzamento: dias de alerta sustentado antes do primeiro cruzamento.

    Alerta sustentado: a sequência de dias com P >= 0,5 que termina na véspera do cruzamento.
    `dias_de_alerta` = 0 quando a véspera não estava em alerta.
    """
    linhas = []
    for ano, g in df.sort_values("data").groupby("ano"):
        if ano not in cruzamentos:
            continue
        antes = g[g["data"] < cruzamentos[ano]]
        alerta = antes[coluna].to_numpy() >= LIMIAR_ALERTA
        dias = 0
        for ativo in alerta[::-1]:
            if not ativo:
                break
            dias += 1
        linhas.append({"ano": ano, "cruzamento": cruzamentos[ano].date(), "dias_de_alerta": dias})
    return pd.DataFrame(linhas)


def alarmes_falsos(df: pd.DataFrame, coluna: str) -> int:
    """Anos sem cruzamento em que o método chegou a dar P >= 0,5 em algum dia."""
    sem_evento = df.groupby("ano").filter(lambda g: g["rotulo"].sum() == 0)
    return int(sem_evento.groupby("ano")[coluna].max().ge(LIMIAR_ALERTA).sum())


def _logit(p) -> np.ndarray:
    p = np.clip(np.asarray(p, float), 1e-3, 1 - 1e-3)
    return np.log(p / (1 - p))


def ajustar_platt(y_validacao, p_validacao):
    """Calibração de Platt: regressão logística de y sobre logit(p), ajustada na validação.

    Devolve uma função p -> p calibrada. Dois parâmetros só, estável mesmo com poucos eventos.
    """
    from sklearn.linear_model import LogisticRegression

    modelo = LogisticRegression(C=1e6, max_iter=1000).fit(_logit(p_validacao).reshape(-1, 1), np.asarray(y_validacao))
    return lambda p: np.clip(modelo.predict_proba(_logit(p).reshape(-1, 1))[:, 1], 1e-3, 1 - 1e-3)


def sensibilidade(p_base, p_variante) -> dict:
    """Quanto uma variante muda as respostas: diferença absoluta média e decisões invertidas em 0,5."""
    p_base, p_variante = np.asarray(p_base), np.asarray(p_variante)
    return {
        "dif_abs_media": float(np.mean(np.abs(p_variante - p_base))),
        "decisoes_invertidas": float(np.mean((p_base >= LIMIAR_ALERTA) != (p_variante >= LIMIAR_ALERTA))),
    }
