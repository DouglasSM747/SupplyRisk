"""Jev no braço A: monta o estado (só números, sem ano nem data), pergunta e guarda tudo.

Seguindo a documentação do Jev (jev-1.13 "struggles with numeric precision"; "keep the arithmetic in
code"; inglês é a língua principal), o estado traz os mesmos números que os baselines recebem, e as
contas (distância ao limiar, dias até o limiar no ritmo atual) são feitas em código.

Uma chamada por dia de previsão, com uma pergunta por tarefa (limiar, horizonte) aplicável naquele dia.
Cada chamada (pedido e resposta brutos) fica em data/jev/<variante>/<periodo>.jsonl; rodar de novo
reaproveita o que já foi perguntado.

Versão do texto: v2, escolhida na validação contra uma única alternativa (v1, sem a última frase do
CONTEXTO). Brier médio nas 4 tarefas da validação: v1 0,0466; v2 0,0328. Ver data/jev/dev_v1 e dev_v2.

Variantes:
    principal        Choice com opções descritivas `crosses_threshold` / `stays_above`
    nomes_01         mesmas descrições, opções renomeadas para "1" / "0"
    nomes_sim_nao    opções renomeadas para "yes" / "no"
    ordem_invertida  `stays_above` antes de `crosses_threshold`
    noul             pergunta sim/não (Noul) em vez de Choice
    com_datas        principal + data e ano no estado (teste de memória)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from typesafe_sdk import AsyncTypeSafeClient

from supplyrisk import amostras as am

MODELO = "jev-1.13.0"
RAIZ = Path(__file__).resolve().parents[2]
PASTA = RAIZ / "data" / "jev"
RESULTADOS = RAIZ / "data" / "resultados"
CHAMADAS_SIMULTANEAS = 16

CONTEXTO = (
    "Daily water level of the Rio Negro at the port of Manaus (Amazonas, Brazil). The dry season runs "
    "from about July to November: the level falls through the season and usually reaches its yearly "
    "minimum in October or November, then starts rising again. The fall usually slows down as the yearly "
    "minimum approaches, so extending the recent fall rate in a straight line usually overstates how far "
    "the level will drop."
)
PERGUNTA = (
    "Will the river level at Manaus fall to `threshold_m` or below on at least one day within the next "
    "`horizon_days` days?"
)
DESCRICAO_CRUZA = "The level will be at or below `threshold_m` on at least one day in the next `horizon_days` days."
DESCRICAO_FICA = "The level will stay above `threshold_m` on every day of the next `horizon_days` days."

OPCOES = {
    # variante: (chave que significa "cruza", chave que significa "fica acima", cruza vem primeiro?)
    "principal": ("crosses_threshold", "stays_above", True),
    "nomes_01": ("1", "0", True),
    "nomes_sim_nao": ("yes", "no", True),
    "ordem_invertida": ("crosses_threshold", "stays_above", False),
    "com_datas": ("crosses_threshold", "stays_above", True),
}
VARIANTES = (*OPCOES, "noul")


def _m(cm: float) -> float:
    return round(float(cm) / 100, 2)


def _cm(valor: float) -> float | None:
    return None if pd.isna(valor) else round(float(valor), 1)


def estado(linha: pd.Series, com_datas: bool = False) -> dict:
    """Estado de um dia de previsão. Só números conhecidos até o dia; sem ano nem data."""
    taxa = linha["taxa_7d_cm_dia"]
    if pd.isna(taxa):
        tendencia = "unknown"
    elif taxa < 0:
        tendencia = f"falling {abs(taxa):.1f} cm per day on average over the last 7 days"
    elif taxa > 0:
        tendencia = f"rising {taxa:.1f} cm per day on average over the last 7 days"
    else:
        tendencia = "stable over the last 7 days"
    anomalia = linha["anomalia_cm"]
    s = {
        "context": CONTEXTO,
        "dry_season_day": f"day {int(linha['dia_vazante']) + 1} of the dry season (counting from 1 July)",
        "current_level_m": _m(linha["nivel_cm"]),
        "trend": tendencia,
        "level_change_cm": {
            "last_7_days": _cm(linha["var_7d_cm"]),
            "last_14_days": _cm(linha["var_14d_cm"]),
            "last_30_days": _cm(linha["var_30d_cm"]),
        },
        "this_year_flood_peak_m": _m(linha["pico_cheia_cm"]),
        "days_since_flood_peak": int(linha["dias_desde_pico"]),
        "typical_level_for_this_day_of_year_m": _m(linha["clima_mediana"]),
        "usual_range_for_this_day_of_year_m": f"{_m(linha['clima_p10'])} to {_m(linha['clima_p90'])} (10th to 90th percentile)",
        "difference_from_typical": f"{abs(anomalia) / 100:.2f} m {'below' if anomalia < 0 else 'above'} the typical level for this day of the year",
    }
    if not pd.isna(linha["mcp_nivel_cm"]):
        s["upstream_solimoes_river_at_manacapuru"] = {
            "current_level_m": _m(linha["mcp_nivel_cm"]),
            "level_change_last_7_days_cm": _cm(linha["mcp_var_7d_cm"]),
            "level_change_last_14_days_cm": _cm(linha["mcp_var_14d_cm"]),
        }
    if com_datas:
        s["date"] = linha["data"].strftime("%Y-%m-%d")
        s["year"] = int(linha["ano"])
    return s


def instrucoes(linha: pd.Series) -> dict:
    dias = linha["dias_ate_limiar_no_ritmo"]
    no_ritmo = (
        "the level is not falling"
        if pd.isna(linha["taxa_7d_cm_dia"]) or linha["taxa_7d_cm_dia"] >= 0
        else f"about {dias:.1f} days"
    )
    return {
        "threshold_m": _m(linha["limiar_cm"]),
        "horizon_days": int(linha["horizonte_dias"]),
        "distance_above_threshold_cm": _cm(linha["distancia_cm"]),
        "days_to_reach_threshold_if_last_7_day_fall_rate_continued": no_ritmo,
        "question": PERGUNTA,
    }


def pergunta(linha: pd.Series, variante: str) -> dict:
    if variante == "noul":
        return {"type": "noul", "instructions": instrucoes(linha),
                "criteria": {"true": DESCRICAO_CRUZA, "false": DESCRICAO_FICA}}
    cruza, fica, cruza_primeiro = OPCOES[variante]
    opcoes = [(cruza, DESCRICAO_CRUZA), (fica, DESCRICAO_FICA)]
    if not cruza_primeiro:
        opcoes.reverse()
    return {"type": "choice", "instructions": instrucoes(linha), "criteria": dict(opcoes)}


def pedidos(amostras: pd.DataFrame, variante: str) -> list[dict]:
    """Um pedido por dia de previsão, com uma pergunta por tarefa aplicável."""
    lista = []
    for data, dia in amostras.groupby("data"):
        primeira = dia.iloc[0]
        perguntas = {
            f"L{int(l.limiar_cm)}_H{int(l.horizonte_dias)}": pergunta(l, variante) for _, l in dia.iterrows()
        }
        lista.append({
            "data": data.strftime("%Y-%m-%d"),
            "pedido": {"model": MODELO, "state": estado(primeira, com_datas=variante == "com_datas"),
                       "questions": perguntas},
        })
    return lista


def _chave(pedido: dict) -> str:
    return hashlib.sha256(json.dumps(pedido, sort_keys=True).encode()).hexdigest()


def _ler_cache(arquivo: Path) -> dict[str, dict]:
    if not arquivo.exists():
        return {}
    registros = (json.loads(l) for l in arquivo.read_text(encoding="utf-8").splitlines() if l.strip())
    return {r["chave"]: r for r in registros}


async def _perguntar(lista: list[dict], arquivo: Path) -> dict[str, dict]:
    load_dotenv(RAIZ / ".env")
    cache = _ler_cache(arquivo)
    faltam = [p for p in lista if _chave(p["pedido"]) not in cache]
    if faltam:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        semaforo = asyncio.Semaphore(CHAMADAS_SIMULTANEAS)
        trava = asyncio.Lock()
        async with AsyncTypeSafeClient(api_key=os.environ["JEV_API_KEY"], model=MODELO) as cliente:
            async def uma(item: dict) -> None:
                async with semaforo:
                    resposta = await cliente.system_one(
                        state=item["pedido"]["state"], questions=item["pedido"]["questions"]
                    )
                registro = {"chave": _chave(item["pedido"]), "data": item["data"], "pedido": item["pedido"],
                            "resposta": resposta.model_dump(mode="json")}
                async with trava:
                    with arquivo.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
                    cache[registro["chave"]] = registro

            await asyncio.gather(*(uma(p) for p in faltam))
        print(f"  {len(faltam)} chamadas novas ao Jev ({len(lista) - len(faltam)} vindas do cache)")
    return cache


def _probabilidade(resposta: dict, chave_pergunta: str, variante: str) -> float:
    resp = resposta["answers"][chave_pergunta]
    if variante == "noul":
        return float(resp["noul"])
    return float(resp["probabilities"][OPCOES[variante][0]])


def prever(amostras: pd.DataFrame, variante: str, periodo: str) -> pd.DataFrame:
    lista = pedidos(amostras, variante)
    cache = asyncio.run(_perguntar(lista, PASTA / variante / f"{periodo}.jsonl"))
    por_data = {p["data"]: cache[_chave(p["pedido"])] for p in lista}

    saida = amostras[["data", "ano", "periodo", "limiar_cm", "horizonte_dias", "rotulo"]].copy()
    probs, modelos = [], set()
    for _, l in saida.iterrows():
        registro = por_data[l["data"].strftime("%Y-%m-%d")]
        modelos.add(registro["resposta"]["model"])
        probs.append(_probabilidade(registro["resposta"], f"L{int(l.limiar_cm)}_H{int(l.horizonte_dias)}", variante))
    saida[f"jev__{variante}"] = np.clip(probs, 0.001, 0.999)
    print(f"  modelo(s) que responderam: {sorted(modelos)}")
    return saida


def rodar(periodo: str, variantes: tuple[str, ...] | None = None) -> pd.DataFrame:
    amostras = pd.read_parquet(am.ARQUIVO)
    alvo = amostras[amostras["periodo"] == periodo]
    if variantes is None:
        variantes = ("principal",) if periodo == "validacao" else VARIANTES
    resultado = None
    for variante in variantes:
        print(f"Jev — {variante} — {periodo}")
        previsoes = prever(alvo, variante, periodo)
        resultado = previsoes if resultado is None else resultado.merge(
            previsoes, on=["data", "ano", "periodo", "limiar_cm", "horizonte_dias", "rotulo"]
        )
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    resultado.to_parquet(RESULTADOS / f"previsoes_jev_{periodo}.parquet")
    return resultado
