"""Mede hit@1 / hit@3 das consultas de validação por modo de recuperação (sem LLM, sem chave).

Uso: python -m backend.medir_recuperacao
Acerto = chunk do documento esperado e, quando informado, do artigo esperado.
"""
from __future__ import annotations

import sys

from backend.config import get_settings
from backend.retriever import Modo, Resultado, Retriever, _rotulo_base

# (pergunta, documento esperado, artigo esperado ou None, texto que o contexto precisa conter)
CASOS: list[tuple[str, str, str | None, str]] = [
    ("Qual a carga horária mínima de atividades complementares?", "regulamento-atividades-complementares-si", "Art. 4", "210 horas/aula"),
    ("Quantas horas de monitoria contam como atividade complementar?", "regulamento-atividades-complementares-si", "Art. 5", "Máximo 60 h-a"),
    ("Qual o percentual mínimo de extensão na carga horária?", "res-cepe-6-2022-extensao", "Art. 8", "dez por cento"),
    ("Por quantos períodos posso trancar a matrícula na graduação?", "res-cepe-30-2026-regime-didatico", "Art. 80", "até cinco vezes"),
    ("Quantos períodos de mobilidade acadêmica posso fazer?", "res-cepe-8-2024-mobilidade", "Art. 5", "3 (três) períodos"),
    ("Quando é a colação de grau de 2026/1?", "orientacoes-colacao-grau-2026-1", None, "31 de julho de 2026"),
    ("Quantas vezes o mestrando pode trancar a matrícula?", "res-cepe-29-2026-pos-graduacao", "Art. 28", "2 (dois) períodos"),
]
MODOS: list[Modo] = ["denso", "bm25", "rrf", "hibrido"]


def acerta(r: Resultado, doc: str, art: str | None, k: int) -> bool:
    return any(c.chunk.documento == doc and (art is None or _rotulo_base(c.chunk.artigo) == art) for c in r.candidatos[:k])


def contexto_tem(r: Resultado, trecho: str) -> bool:
    return any(trecho in p.texto for p in r.paginas)


def medir(ret: Retriever) -> dict[str, dict[str, object]]:
    saida: dict[str, dict[str, object]] = {}
    for modo in MODOS:
        h1 = h3 = ctx = 0
        linhas = []
        for pergunta, doc, art, chave in CASOS:
            r = ret.buscar(pergunta, modo)
            a1, a3, c = acerta(r, doc, art, 1), acerta(r, doc, art, 3), contexto_tem(r, chave)
            h1, h3, ctx = h1 + a1, h3 + a3, ctx + c
            top = r.candidatos[0].chunk if r.candidatos else None
            linhas.append((a1, a3, c, pergunta, f"{top.documento[:24]} {_rotulo_base(top.artigo)}" if top else "-"))
        saida[modo] = {"hit1": h1, "hit3": h3, "contexto": ctx, "linhas": linhas}
    return saida


def main() -> int:
    for f in (sys.stdout, sys.stderr):
        f.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ret = Retriever.carregar(get_settings())
    res = medir(ret)
    n = len(CASOS)
    print(f"\n{'modo':<9} {'hit@1':>6} {'hit@3':>6} {'contexto(página inteira) contém a resposta':>46}")
    for modo in MODOS:
        d = res[modo]
        print(f"{modo:<9} {d['hit1']:>3}/{n}  {d['hit3']:>3}/{n}  {d['contexto']:>30}/{n}")
    for modo in ("denso", "hibrido"):
        print(f"\n--- detalhe: {modo}  (hit@1 hit@3 ctx)")
        for a1, a3, c, p, top in res[modo]["linhas"]:  # type: ignore[misc]
            print(f"  {'S' if a1 else 'n'} {'S' if a3 else 'n'} {'S' if c else 'n'}  {p[:58]:<58} top1={top}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
