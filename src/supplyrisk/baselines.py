"""Baselines do braço A. Todos recebem as mesmas features (só passado) e devolvem P(cruzar).

Cada tarefa (limiar, horizonte) é um problema separado. `ajustar` usa só as amostras de treino;
hiperparâmetros são escolhidos pelo Brier na validação (ver experimento.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

P_MIN, P_MAX = 0.001, 0.999

FEATURES_MANAUS = [
    "nivel_cm", "var_7d_cm", "var_14d_cm", "var_30d_cm", "taxa_7d_cm_dia", "pico_cheia_cm",
    "dias_desde_pico", "anomalia_cm", "dia_vazante", "distancia_cm", "dias_ate_limiar_no_ritmo",
]
FEATURES_MANACAPURU = ["mcp_nivel_cm", "mcp_var_7d_cm", "mcp_var_14d_cm"]


def _clip(p) -> np.ndarray:
    return np.clip(np.asarray(p, dtype=float), P_MIN, P_MAX)


@dataclass
class Tendencia:
    """Extrapola a descida dos últimos 7 dias e converte em probabilidade com os erros do treino.

    Projeção do mínimo no horizonte: nível + min(0, taxa_7d) * H. O erro (mínimo real - projeção) no
    treino forma uma distribuição empírica; P(cruzar) = P(projeção + erro <= limiar).
    """

    erros: np.ndarray = field(default=None, repr=False)

    @staticmethod
    def _projecao(df: pd.DataFrame) -> np.ndarray:
        taxa = df["taxa_7d_cm_dia"].fillna(0).clip(upper=0)
        return (df["nivel_cm"] + taxa * df["horizonte_dias"]).to_numpy()

    def ajustar(self, treino: pd.DataFrame) -> "Tendencia":
        self.erros = np.sort((treino["minimo_futuro_cm"] - self._projecao(treino)).dropna().to_numpy())
        return self

    def prever(self, df: pd.DataFrame) -> np.ndarray:
        folga = df["limiar_cm"].to_numpy() - self._projecao(df)
        return _clip(np.searchsorted(self.erros, folga, side="right") / len(self.erros))


@dataclass
class Climatologia:
    """Frequência de cruzamento entre amostras de treino da mesma época (±7 dias) e nível parecido.

    A janela de nível começa em ±25 cm e dobra até reunir ao menos `minimo_vizinhos` amostras.
    """

    minimo_vizinhos: int = 30
    treino: pd.DataFrame = field(default=None, repr=False)

    def ajustar(self, treino: pd.DataFrame) -> "Climatologia":
        self.treino = treino[["dia_vazante", "nivel_cm", "rotulo"]].reset_index(drop=True)
        return self

    def prever(self, df: pd.DataFrame) -> np.ndarray:
        dia_t, nivel_t, rotulo_t = (self.treino[c].to_numpy() for c in ("dia_vazante", "nivel_cm", "rotulo"))
        base = (rotulo_t.sum() + 0.5) / (len(rotulo_t) + 1)
        saida = []
        for dia, nivel in zip(df["dia_vazante"], df["nivel_cm"]):
            perto_no_tempo = np.abs(dia_t - dia) <= 7
            p = base
            for janela in (25, 50, 100, 200, 400):
                vizinhos = perto_no_tempo & (np.abs(nivel_t - nivel) <= janela)
                if vizinhos.sum() >= self.minimo_vizinhos:
                    p = (rotulo_t[vizinhos].sum() + 0.5) / (vizinhos.sum() + 1)
                    break
            saida.append(p)
        return _clip(saida)


@dataclass
class Analogos:
    """Anos análogos (método usado pelo SGB): as K vazantes do treino cuja cota nos 30 dias até a
    mesma data do ano mais se parece com a atual (RMSE). A trajetória futura de cada análogo é
    deslocada para começar no nível atual; P = fração de análogos que cruzam (com suavização).
    """

    serie: pd.Series
    k: int = 10
    anos_treino: list[int] = field(default=None, repr=False)

    def ajustar(self, treino: pd.DataFrame) -> "Analogos":
        self.anos_treino = sorted(treino["ano"].unique())
        # Matriz ano x dia do ano (1..366) para acesso rápido.
        s = self.serie
        tabela = pd.DataFrame({"ano": s.index.year, "doy": s.index.dayofyear, "cota": s.to_numpy()})
        self._matriz = tabela.pivot(index="ano", columns="doy", values="cota").reindex(columns=range(1, 367))
        return self

    def prever(self, df: pd.DataFrame) -> np.ndarray:
        pool = self._matriz.loc[self._matriz.index.intersection(self.anos_treino)].to_numpy()
        anos_pool = np.array(self._matriz.index.intersection(self.anos_treino))
        saida = []
        for t, ano, limiar, h in zip(df["data"], df["ano"], df["limiar_cm"], df["horizonte_dias"]):
            doy = t.dayofyear
            atual = self.serie[t - pd.Timedelta(days=29): t].to_numpy()
            passado = pool[:, doy - 30: doy]  # colunas doy-29..doy (índice 0 = doy 1)
            futuro = pool[:, doy: doy + h]
            validos = (anos_pool != ano) & ~np.isnan(passado).any(axis=1) & ~np.isnan(futuro).all(axis=1)
            if len(atual) != 30 or np.isnan(atual).any() or validos.sum() == 0:
                saida.append(np.nan)
                continue
            dist = np.sqrt(np.nanmean((passado[validos] - atual) ** 2, axis=1))
            ordem = np.argsort(dist)[: self.k]
            deslocado = futuro[validos][ordem] - passado[validos][ordem][:, -1:] + atual[-1]
            cruzam = (np.nanmin(deslocado, axis=1) <= limiar).sum()
            saida.append((cruzam + 0.5) / (len(ordem) + 1))
        return _clip(pd.Series(saida).fillna(0.5))


@dataclass
class Logistica:
    features: list[str]
    c: float = 1.0
    modelo: object = field(default=None, repr=False)

    def ajustar(self, treino: pd.DataFrame) -> "Logistica":
        self.modelo = make_pipeline(
            SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=self.c, max_iter=2000)
        ).fit(treino[self.features], treino["rotulo"])
        return self

    def prever(self, df: pd.DataFrame) -> np.ndarray:
        return _clip(self.modelo.predict_proba(df[self.features])[:, 1])


@dataclass
class GradientBoosting:
    features: list[str]
    num_leaves: int = 15
    n_estimators: int = 200
    modelo: object = field(default=None, repr=False)

    def ajustar(self, treino: pd.DataFrame) -> "GradientBoosting":
        self.modelo = lgb.LGBMClassifier(
            num_leaves=self.num_leaves, n_estimators=self.n_estimators, learning_rate=0.05,
            min_child_samples=50, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
            random_state=42, verbose=-1,
        ).fit(treino[self.features], treino["rotulo"])
        return self

    def prever(self, df: pd.DataFrame) -> np.ndarray:
        return _clip(self.modelo.predict_proba(df[self.features])[:, 1])
