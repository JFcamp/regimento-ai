"""Gera data/cache/sugeridas.json com as respostas reais (RAG) das perguntas sugeridas: python -m backend.build_cache"""
from __future__ import annotations

import asyncio
import sys
from datetime import date

from backend.config import get_settings
from backend.generator import ErroProvedor, obter_provedor
from backend.rag import coletar, responder
from backend.retriever import Retriever
from backend.sugeridas import SUGERIDAS, chave_da_pergunta, gravar_cache


async def _main() -> int:
    s = get_settings()
    try:
        prov = obter_provedor(s.llm_provider, s)
    except ErroProvedor as e:
        print(f"ERRO: {e.mensagem}")
        return 1
    ret = Retriever.carregar(s)
    entradas: dict[str, dict] = {}
    for p in SUGERIDAS:
        r = await coletar(responder(p, "rag", ret, prov, s))
        if r.erro:
            print(f"  falhou: {p} -> {r.erro['codigo']}")
            continue
        entradas[chave_da_pergunta(p)] = {"pergunta": p, "resposta": r.texto, "citacoes": r.citacoes, "fim": r.fim}
        print(f"  ok: {p} ({r.fim.get('n_trechos')} citações válidas, recusa={r.fim.get('recusa')})")
    gravar_cache(s.cache_sugeridas, entradas, {"gerado_em": str(date.today()), "provedor": s.llm_provider,
                                              "modelo": getattr(prov, "modelo", "")})
    print(f"{len(entradas)}/{len(SUGERIDAS)} respostas gravadas em {s.cache_sugeridas}")
    return 0 if entradas else 1


if __name__ == "__main__":
    for f in (sys.stdout, sys.stderr):
        f.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    raise SystemExit(asyncio.run(_main()))
