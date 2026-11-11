"""Fluxo de resposta: recuperação -> prompt -> LLM em streaming -> verificação de citações.

`responder` é um gerador de eventos {"event": ..., "data": ...}, usado pela API (SSE) e pela avaliação.
Eventos: aviso, token, substituir, citacoes, fim, erro.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator

from backend.citations import Citacao, citacoes_invalidas_ou_ausentes, verificar
from backend.config import Settings
from backend.generator import ErroProvedor, Provedor
from backend.pii import mascarar
from backend.prompts import RECUSA, SYSTEM_RAG, SYSTEM_SEM_RAG, montar_user_rag
from backend.retriever import Retriever
from backend.textutil import normalizar

AVISO_POS = (
    "\n\nObservação: um dos trechos consultados é do Regimento da Pós-Graduação e não se aplica a estudantes de graduação."
)
Evento = dict


def eh_recusa(texto: str) -> bool:
    return normalizar(RECUSA) in normalizar(texto)[:160]


async def responder(
    pergunta: str, modo: str, retriever: Retriever | None, provedor: Provedor, s: Settings
) -> AsyncIterator[Evento]:
    texto_seguro, mascarados = mascarar(pergunta)
    if mascarados:
        yield {"event": "aviso", "data": {"tipo": "dados_pessoais", "mascarados": mascarados,
                                         "mensagem": "Dados pessoais foram ocultados antes do envio ao modelo."}}

    # --- baseline sem RAG ---
    if modo == "sem_rag":
        try:
            async for t in provedor.stream(SYSTEM_SEM_RAG, texto_seguro):
                yield {"event": "token", "data": {"texto": t}}
        except ErroProvedor as e:
            yield {"event": "erro", "data": {"codigo": e.codigo, "mensagem": e.mensagem}}
            return
        yield {"event": "citacoes", "data": []}
        yield {"event": "fim", "data": {"modo": "sem_rag", "recusa": False, "n_trechos": 0, "paginas": []}}
        return

    # --- RAG ---
    assert retriever is not None
    res = retriever.buscar(texto_seguro, "hibrido")
    paginas_ctx = [{"id": p.id, "documento": p.documento, "pagina": p.pagina, "artigo": p.artigo} for p in res.paginas]
    sem_base = not res.paginas or (s.min_score is not None and res.melhor_denso < s.min_score)
    if sem_base:
        yield {"event": "token", "data": {"texto": RECUSA + "."}}
        yield {"event": "citacoes", "data": []}
        yield {"event": "fim", "data": {"modo": "rag", "recusa": True, "n_trechos": 0, "motivo": "sem_contexto",
                                       "paginas": paginas_ctx}}
        return

    if res.divergencias:
        yield {"event": "aviso", "data": {"tipo": "divergencia", "detalhes": res.divergencias,
                                         "mensagem": "Os documentos trazem valores diferentes para este assunto."}}

    acumulado = ""
    try:
        async for t in provedor.stream(SYSTEM_RAG, montar_user_rag(texto_seguro, res.paginas)):
            acumulado += t
            yield {"event": "token", "data": {"texto": t}}
    except ErroProvedor as e:
        yield {"event": "erro", "data": {"codigo": e.codigo, "mensagem": e.mensagem}}
        return

    recusa = eh_recusa(acumulado)
    citacoes: list[Citacao] = [] if recusa else verificar(
        acumulado, res.paginas, s.fuzzy_threshold, s.suporte_threshold, retriever.artigo_em)
    n_validas = sum(c.valida for c in citacoes)
    motivo = None
    if not recusa and n_validas == 0:
        # garantia de aceite: resposta do RAG sempre tem >= 1 citação válida ou recusa explícita
        recusa, motivo, citacoes = True, "sem_citacao_valida", []
        yield {"event": "substituir", "data": {"texto": RECUSA + "."}}
    elif not recusa:
        mortas = citacoes_invalidas_ou_ausentes(acumulado, res.paginas)
        if mortas:
            motivo = f"marcadores_inexistentes:{mortas}"
        if res.tem_pos_no_contexto and "pos-gradua" not in normalizar(acumulado).replace("pós", "pos"):
            yield {"event": "token", "data": {"texto": AVISO_POS}}
            yield {"event": "aviso", "data": {"tipo": "pos_graduacao", "mensagem": AVISO_POS.strip()}}

    yield {"event": "citacoes", "data": [c.dict() for c in citacoes]}
    yield {"event": "fim", "data": {
        "modo": "rag", "recusa": recusa, "motivo": motivo, "n_trechos": n_validas,
        "paginas": paginas_ctx, "divergencia": bool(res.divergencias),
    }}


@dataclass
class RespostaCompleta:
    texto: str = ""
    citacoes: list[dict] = field(default_factory=list)
    avisos: list[dict] = field(default_factory=list)
    fim: dict = field(default_factory=dict)
    erro: dict | None = None


async def coletar(gerador: AsyncIterator[Evento]) -> RespostaCompleta:
    r = RespostaCompleta()
    async for ev in gerador:
        d = ev["data"]
        if ev["event"] == "token":
            r.texto += d["texto"]
        elif ev["event"] == "substituir":
            r.texto = d["texto"]
        elif ev["event"] == "citacoes":
            r.citacoes = d
        elif ev["event"] == "aviso":
            r.avisos.append(d)
        elif ev["event"] == "fim":
            r.fim = d
        elif ev["event"] == "erro":
            r.erro = d
    return r
