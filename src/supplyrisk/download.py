"""Baixa as séries brutas (ANA e Porto de Manaus) e grava em data/raw.

Uso: uv run python -m supplyrisk.download
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pandas as pd

from supplyrisk import ana, porto

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"

ANO_INICIAL_CONVENCIONAL = 1900
ANO_INICIAL_TELEMETRIA = 2008
# O serviço da ANA é frágil (timeouts no banco); poucas consultas simultâneas bastam.
CONSULTAS_SIMULTANEAS = 4


# Consultas que falharam mesmo após as novas tentativas. Não entram no cache,
# então rodar o download de novo tenta só elas (o resto vem do cache).
falhas: list[str] = []


def _tentar(funcao, *args) -> pd.DataFrame:
    try:
        return funcao(*args)
    except RuntimeError as erro:
        falhas.append(str(erro))
        return pd.DataFrame()


def baixar_convencional(codigo: int, pool: ThreadPoolExecutor) -> pd.DataFrame:
    anos = range(ANO_INICIAL_CONVENCIONAL, date.today().year + 1)
    partes = list(pool.map(lambda ano: _tentar(ana.convencional_ano, codigo, ano), anos))
    print(f"  convencional: {sum(not p.empty for p in partes)} anos com dados")
    return pd.concat(partes, ignore_index=True)


def baixar_telemetria(codigo: int, pool: ThreadPoolExecutor) -> pd.DataFrame:
    hoje = date.today()
    meses = [
        (ano, mes)
        for ano in range(ANO_INICIAL_TELEMETRIA, hoje.year + 1)
        for mes in range(1, 13)
        if (ano, mes) <= (hoje.year, hoje.month)
    ]
    partes = list(pool.map(lambda am: _tentar(ana.telemetria_mes, codigo, *am), meses))
    print(f"  telemetria: {sum(not p.empty for p in partes)} meses com dados")
    return pd.concat(partes, ignore_index=True).drop_duplicates("datahora").sort_values("datahora")


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(CONSULTAS_SIMULTANEAS) as pool:
        for codigo, nome in ana.ESTACOES.items():
            print(f"{codigo} — {nome}")
            baixar_convencional(codigo, pool).to_parquet(RAW_DIR / f"ana_convencional_{codigo}.parquet")
            baixar_telemetria(codigo, pool).to_parquet(RAW_DIR / f"ana_telemetria_{codigo}.parquet")

    print("Porto de Manaus")
    porto.main()

    if falhas:
        print(f"\n{len(falhas)} consultas falharam; rode de novo para tentar só elas:")
        print("\n".join(f"  {f}" for f in falhas))


if __name__ == "__main__":
    main()
