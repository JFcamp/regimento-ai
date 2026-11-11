"""Verificação das citações [n] da resposta contra o texto das páginas recuperadas.

Para cada [n] usado na resposta, o backend escolhe na página n a janela de texto (1 a 2 frases) mais parecida
com a frase da resposta: é o `trecho_literal`. A citação só é `valida` se
  (a) o literal existe no texto da página (exato após normalização, ou RapidFuzz >= fuzzy_threshold), e
  (b) a frase da resposta é sustentada pelo literal (RapidFuzz token_set_ratio >= suporte_threshold).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from rapidfuzz import fuzz

from backend.retriever import PaginaContexto
from backend.textutil import normalizar

_MARCA_RE = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")
_SENTENCA_RE = re.compile(r"[^.!?\n]+(?:[.!?]+|\n|$)")
MAX_JANELA = 420


@dataclass
class Citacao:
    id: int
    documento: str
    titulo: str
    vigencia: str
    escopo: str
    hierarquia: str
    pagina: int
    artigo: str | None
    trecho_literal: str
    score: float
    suporte: float
    valida: bool

    def dict(self) -> dict:
        return asdict(self)


def _ids_na_frase(frase: str) -> list[int]:
    ids: list[int] = []
    for m in _MARCA_RE.finditer(frase):
        ids.extend(int(x) for x in re.split(r"[,;]", m.group(1)))
    return ids


def _frases_com_citacao(resposta: str) -> list[tuple[str, list[int]]]:
    saida = []
    for m in _SENTENCA_RE.finditer(resposta):
        trecho = m.group(0)
        ids = _ids_na_frase(trecho)
        if ids:
            limpo = _MARCA_RE.sub("", trecho).strip()
            if limpo:
                saida.append((limpo, ids))
    return saida


def _janelas(texto: str) -> list[tuple[int, int]]:
    """Janelas (início, fim) de 1 a 2 sentenças consecutivas; sempre substrings exatas do texto."""
    sentencas = [(m.start(), m.end()) for m in _SENTENCA_RE.finditer(texto) if m.group(0).strip()]
    janelas = []
    for i, (ini, fim) in enumerate(sentencas):
        janelas.append((ini, fim))
        if i + 1 < len(sentencas):
            janelas.append((ini, sentencas[i + 1][1]))
    return [(a, b) for a, b in janelas if b - a <= MAX_JANELA] or [(0, min(len(texto), MAX_JANELA))]


def melhor_trecho(frase: str, texto_pagina: str) -> tuple[str, float]:
    melhor, melhor_s = "", -1.0
    f = normalizar(frase)
    for ini, fim in _janelas(texto_pagina):
        cand = texto_pagina[ini:fim]
        s = fuzz.token_set_ratio(f, normalizar(cand))
        if s > melhor_s:
            melhor, melhor_s = cand.strip(), s
    return melhor, float(max(melhor_s, 0.0))


def literal_existe(literal: str, texto_pagina: str, limiar: int) -> bool:
    a, b = re.sub(r"\s+", " ", normalizar(literal)).strip(), re.sub(r"\s+", " ", normalizar(texto_pagina))
    return bool(a) and (a in b or fuzz.partial_ratio(a, b) >= limiar)


def verificar(
    resposta: str,
    paginas: list[PaginaContexto],
    fuzzy_threshold: int = 90,
    suporte_threshold: int = 45,
    artigo_em=None,
) -> list[Citacao]:
    """Citações usadas na resposta, uma por fonte [n], com o melhor trecho literal encontrado."""
    por_id = {p.id: p for p in paginas}
    melhores: dict[int, tuple[str, float]] = {}
    for frase, ids in _frases_com_citacao(resposta):
        for i in ids:
            if i not in por_id:
                continue
            literal, suporte = melhor_trecho(frase, por_id[i].texto)
            if i not in melhores or suporte > melhores[i][1]:
                melhores[i] = (literal, suporte)

    saida: list[Citacao] = []
    for i in sorted(melhores):
        p = por_id[i]
        literal, suporte = melhores[i]
        valida = literal_existe(literal, p.texto, fuzzy_threshold) and suporte >= suporte_threshold
        artigo = (artigo_em(p.documento, p.pagina, literal) if artigo_em else None) or p.artigo
        saida.append(
            Citacao(i, p.documento, p.titulo, p.vigencia, p.escopo, p.hierarquia, p.pagina, artigo, literal,
                    round(p.score, 5), round(suporte, 1), valida)
        )
    return saida


def citacoes_invalidas_ou_ausentes(resposta: str, paginas: list[PaginaContexto]) -> list[int]:
    """Marcadores [n] que apontam para uma fonte inexistente."""
    validos = {p.id for p in paginas}
    return sorted({i for _, ids in _frases_com_citacao(resposta) for i in ids if i not in validos})
