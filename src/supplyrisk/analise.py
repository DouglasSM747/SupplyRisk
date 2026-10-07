"""Análises pré-registradas (PREREGISTRATION.md, seção 5) para um período avaliado.

Uso: uv run python -m supplyrisk.analise teste      (ou: final)
Gera tabelas em data/resultados/<periodo>/ e imprime um resumo.
"""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from supplyrisk import amostras as am
from supplyrisk import avaliacao as av
from supplyrisk.experimento import RESULTADOS

CHAVES = ["data", "ano", "periodo", "limiar_cm", "horizonte_dias", "rotulo"]
MELHOR_BASELINE = {  # PREREGISTRATION.md, seção 4
    (1770, 14): "logistica__so_manaus",
    (1770, 30): "logistica__so_manaus",
    (1500, 14): "gradient_boosting__so_manaus",
    (1500, 30): "gradient_boosting__so_manaus",
}
REFERENCIA = "climatologia__principal"
TAREFAS_PRINCIPAIS = [(1770, 14), (1770, 30)]


def carregar(periodo: str) -> pd.DataFrame:
    b = pd.read_parquet(RESULTADOS / f"previsoes_baselines_{periodo}.parquet")
    j = pd.read_parquet(RESULTADOS / f"previsoes_jev_{periodo}.parquet")
    return b.merge(j, on=CHAVES)


def metodos(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if "__" in c]


def calibrar(validacao: pd.DataFrame, alvo: pd.DataFrame, colunas: list[str]) -> pd.DataFrame:
    """Acrescenta `<coluna>__cal`: Platt ajustado na validação, por método e tarefa."""
    saida = []
    for tarefa, g in alvo.groupby(["limiar_cm", "horizonte_dias"]):
        g = g.copy()
        v = validacao[(validacao["limiar_cm"] == tarefa[0]) & (validacao["horizonte_dias"] == tarefa[1])]
        for c in colunas:
            if c in v:
                g[f"{c}__cal"] = av.ajustar_platt(v["rotulo"], v[c])(g[c])
        saida.append(g)
    return pd.concat(saida, ignore_index=True)


def tabela_metricas(df: pd.DataFrame, colunas: list[str]) -> pd.DataFrame:
    linhas = []
    for (limiar, h), g in df.groupby(["limiar_cm", "horizonte_dias"]):
        for c in colunas:
            linhas.append({"limiar_cm": limiar, "horizonte_dias": h, "metodo": c,
                           **av.metricas(g["rotulo"], g[c], g[REFERENCIA])})
    return pd.DataFrame(linhas)


def comparacoes_principais(df: pd.DataFrame) -> pd.DataFrame:
    linhas = []
    for (limiar, h), g in df.groupby(["limiar_cm", "horizonte_dias"]):
        tipo = "principal" if (limiar, h) in TAREFAS_PRINCIPAIS else "secundária"
        comparacoes = [
            ("1. Jev bruto × climatologia", "jev__principal", REFERENCIA),
            ("2. Jev calibrado × melhor baseline calibrado", "jev__principal__cal", f"{MELHOR_BASELINE[(limiar, h)]}__cal"),
            ("extra: Jev bruto × melhor baseline bruto", "jev__principal", MELHOR_BASELINE[(limiar, h)]),
        ]
        for nome, a, b in comparacoes:
            r = av.bootstrap_por_ano(g, a, b)
            lo, hi = r["diferenca_ic95"]
            veredito = "Jev melhor" if hi < 0 else "Jev pior" if lo > 0 else "empate (IC contém 0)"
            linhas.append({"tarefa": f"{limiar / 100:.2f} m / {h} d", "tipo": tipo, "comparacao": nome,
                           "brier_jev": av.brier(g["rotulo"], g[a]), "brier_outro": av.brier(g["rotulo"], g[b]),
                           "outro": b, "diferenca": r["diferenca_brier"], "ic95": r["diferenca_ic95"],
                           "p_jev_melhor": r["p_a_melhor"], "veredito": veredito})
    return pd.DataFrame(linhas)


def robustez(df: pd.DataFrame) -> pd.DataFrame:
    linhas = []
    variantes = [c for c in df.columns if c.startswith("jev__") and not c.endswith("__cal") and c != "jev__principal"]
    for (limiar, h), g in df.groupby(["limiar_cm", "horizonte_dias"]):
        for c in variantes:
            linhas.append({"limiar_cm": limiar, "horizonte_dias": h, "variante": c.removeprefix("jev__"),
                           "brier": av.brier(g["rotulo"], g[c]), "brier_principal": av.brier(g["rotulo"], g["jev__principal"]),
                           **av.sensibilidade(g["jev__principal"], g[c])})
    return pd.DataFrame(linhas)


def memoria(df: pd.DataFrame) -> pd.DataFrame:
    if "jev__com_datas" not in df:
        return pd.DataFrame()
    linhas = []
    for (ano, limiar, h), g in df.groupby(["ano", "limiar_cm", "horizonte_dias"]):
        linhas.append({"ano": ano, "limiar_cm": limiar, "horizonte_dias": h, "cruzou": int(g["rotulo"].max()),
                       "brier_sem_datas": av.brier(g["rotulo"], g["jev__principal"]),
                       "brier_com_datas": av.brier(g["rotulo"], g["jev__com_datas"])})
    t = pd.DataFrame(linhas)
    t["com_menos_sem"] = t["brier_com_datas"] - t["brier_sem_datas"]
    return t


def antecedencia_e_alarmes(df: pd.DataFrame, colunas: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    serie, _ = am.carregar_series()
    ante, alarmes = [], []
    for (limiar, h), g in df.groupby(["limiar_cm", "horizonte_dias"]):
        cruz = av.primeiros_cruzamentos(serie, limiar)
        for c in colunas:
            a = av.antecedencia(g, c, cruz)
            if not a.empty:
                ante.append(a.assign(limiar_cm=limiar, horizonte_dias=h, metodo=c))
            alarmes.append({"limiar_cm": limiar, "horizonte_dias": h, "metodo": c,
                            "anos_sem_evento": int(g.groupby("ano")["rotulo"].max().eq(0).sum()),
                            "anos_com_alarme_falso": av.alarmes_falsos(g, c)})
    return (pd.concat(ante, ignore_index=True) if ante else pd.DataFrame()), pd.DataFrame(alarmes)


def main() -> None:
    periodo = sys.argv[1]
    pasta = RESULTADOS / periodo
    pasta.mkdir(parents=True, exist_ok=True)

    validacao, alvo = carregar("validacao"), carregar(periodo)
    colunas = [c for c in metodos(alvo) if c in validacao]
    alvo = calibrar(validacao, alvo, colunas)
    alvo.to_parquet(pasta / "previsoes_com_calibracao.parquet")

    todas = metodos(alvo)
    metricas = tabela_metricas(alvo, todas)
    metricas.to_csv(pasta / "metricas.csv", index=False)
    principais = comparacoes_principais(alvo)
    principais.to_csv(pasta / "comparacoes_principais.csv", index=False)
    rob = robustez(alvo)
    rob.to_csv(pasta / "robustez.csv", index=False)
    mem = memoria(alvo)
    mem.to_csv(pasta / "memoria.csv", index=False)
    destaque = ["climatologia__principal", "analogos__so_manaus", "logistica__so_manaus",
                "gradient_boosting__so_manaus", "jev__principal", "jev__principal__cal"]
    ante, alarmes = antecedencia_e_alarmes(alvo, [c for c in destaque if c in alvo])
    ante.to_csv(pasta / "antecedencia.csv", index=False)
    alarmes.to_csv(pasta / "alarmes_falsos.csv", index=False)

    pd.set_option("display.width", 250)
    print("=== Comparações principais ===")
    print(principais.round(4).to_string())
    print("\n=== Métricas (destaques) ===")
    print(metricas[metricas["metodo"].isin(destaque + [f"{c}__cal" for c in destaque])].round(4).to_string())
    print("\n=== Robustez ===")
    print(rob.round(4).to_string())
    if not mem.empty:
        print("\n=== Memória (com datas − sem datas, Brier) ===")
        print(mem.pivot_table(index="ano", columns=["limiar_cm", "horizonte_dias"], values="com_menos_sem").round(4).to_string())
    if not ante.empty:
        print("\n=== Antecedência (dias de alerta sustentado antes do cruzamento) ===")
        print(ante.pivot_table(index=["limiar_cm", "horizonte_dias", "ano"], columns="metodo", values="dias_de_alerta").to_string())
    print("\n=== Alarmes falsos ===")
    print(alarmes.pivot_table(index=["limiar_cm", "horizonte_dias"], columns="metodo", values="anos_com_alarme_falso").to_string())


if __name__ == "__main__":
    main()
