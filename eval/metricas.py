"""Métricas do experimento (sem RAG × com RAG) e intervalos de confiança por bootstrap."""
from __future__ import annotations

from collections import defaultdict

import numpy as np

CATEGORIAS = ["trancamento", "pre-requisitos", "horas-complementares-extensao", "prazos-calendario", "outros"]
ROTULO_CATEGORIA = {
    "trancamento": "Trancamento",
    "pre-requisitos": "Pré-requisitos",
    "horas-complementares-extensao": "Horas compl.\n/ extensão",
    "prazos-calendario": "Prazos /\ncalendário",
    "outros": "Outros",
}
PONTOS = {"correta": 1.0, "parcial": 0.5, "incorreta": 0.0}


def bootstrap_ic(valores: list[float], n: int = 10_000, seed: int = 42) -> list[float] | None:
    """IC 95% percentil da média."""
    if not valores:
        return None
    arr = np.asarray(valores, dtype=float)
    rng = np.random.default_rng(seed)
    medias = arr[rng.integers(0, len(arr), size=(n, len(arr)))].mean(axis=1)
    return [round(float(np.percentile(medias, 2.5)), 4), round(float(np.percentile(medias, 97.5)), 4)]


def wilson_ic(k: int, n: int, z: float = 1.96) -> list[float] | None:
    """IC 95% de Wilson para proporção. Útil quando k = 0 ou k = n, onde o bootstrap percentil degenera em [p, p]."""
    if n == 0:
        return None
    p = k / n
    den = 1 + z**2 / n
    centro = (p + z**2 / (2 * n)) / den
    meia = z * ((p * (1 - p) / n + z**2 / (4 * n**2)) ** 0.5) / den
    return [round(max(0.0, centro - meia), 4), round(min(1.0, centro + meia), 4)]


def fontes_aceitas(p: dict) -> set[tuple[str, int]]:
    if not p["respondivel"]:
        return set()
    return {(p["documento"], p["pagina"])} | {(f["documento"], f["pagina"]) for f in p.get("fontes_aceitas", [])}


def _ranking(paginas: list[list]) -> list[tuple[str, int]]:
    """Páginas escolhidas pelo ranking (sem as obrigatórias). Aceita [doc, pág] ou [doc, pág, motivo]."""
    return [(x[0], int(x[1])) for x in paginas if len(x) < 3 or x[2] == "ranking"]


def recall_at_3(p: dict, paginas: list[list]) -> bool | None:
    """Página do gabarito entre as 3 primeiras do ranking (mede a busca, sem as páginas obrigatórias)."""
    if not p["respondivel"]:
        return None
    return bool(fontes_aceitas(p) & set(_ranking(paginas)[:3]))


def recall_contexto(p: dict, paginas: list[list]) -> bool | None:
    """Página do gabarito em qualquer lugar do contexto enviado ao modelo (inclui as páginas obrigatórias)."""
    if not p["respondivel"]:
        return None
    return bool(fontes_aceitas(p) & {(x[0], int(x[1])) for x in paginas})


def _taxa(vs: list[bool]) -> float | None:
    return round(sum(vs) / len(vs), 4) if vs else None


def resumir_modo(linhas: list[dict]) -> dict:
    """Linhas de um modo com julgamento válido."""
    resp = [l for l in linhas if l["respondivel"]]
    sem = [l for l in linhas if not l["respondivel"]]
    cont = {v: sum(l["veredito"] == v for l in resp) for v in PONTOS}
    pontos = [PONTOS[l["veredito"]] for l in resp]
    aluc = [1.0 if l["alucinou"] else 0.0 for l in linhas]
    saida = {
        "n_julgadas": len(linhas),
        "n_respondiveis": len(resp),
        **cont,
        "recusas_em_respondiveis": sum(bool(l.get("recusa")) for l in resp),
        "acuracia": round(float(np.mean(pontos)), 4) if pontos else None,
        "acuracia_estrita": _taxa([l["veredito"] == "correta" for l in resp]),
        "acuracia_ic95": bootstrap_ic(pontos),
        "taxa_alucinacao": round(float(np.mean(aluc)), 4) if aluc else None,
        "alucinacoes": int(sum(aluc)),
        "taxa_alucinacao_ic95": bootstrap_ic(aluc),
        "taxa_alucinacao_ic95_wilson": wilson_ic(int(sum(aluc)), len(aluc)),
        "recusa_correta": {"acertos": sum(l["veredito"] == "correta" for l in sem), "total": len(sem)},
    }
    citacoes = [c for l in linhas for c in l.get("citacoes_avaliadas", [])]
    if any(l["modo"] == "rag" for l in linhas):
        validas = [c for c in citacoes if c["valida"]]
        saida["citacoes"] = {
            "total": len(citacoes),
            "literal_valido": _taxa([c["valida"] for c in citacoes]),
            "precisao_pagina": _taxa([c["pagina_correta"] for c in validas]),
            "respostas_com_citacao_correta": _taxa(
                [any(c["valida"] and c["pagina_correta"] for c in l.get("citacoes_avaliadas", []))
                 for l in resp if not l.get("recusa")]),
        }
    return saida


def por_categoria(linhas: list[dict]) -> dict:
    acc: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for l in linhas:
        if l["respondivel"]:
            acc[l["categoria"]][l["modo"]].append(PONTOS[l["veredito"]])
    return {
        c: {m: {"acuracia": round(float(np.mean(v)), 4), "n": len(v)} for m, v in acc[c].items()}
        for c in CATEGORIAS if c in acc
    }
