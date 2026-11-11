"""Recuperação híbrida: BM25 + e5 (RRF), roteamento por escopo, hierarquia de fontes e páginas inteiras.

Modos (para medir o ganho de cada etapa com o mesmo código):
  denso    só e5, sem filtros (comportamento da Etapa 2)
  bm25     só BM25
  rrf      BM25 + e5 fundidos por Reciprocal Rank Fusion
  hibrido  rrf + roteamento de escopo + hierarquia de fontes (padrão)
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Literal

import faiss
import numpy as np
from rank_bm25 import BM25Okapi

from backend.config import Settings
from backend.indexer import carregar_indice, consulta_para_embedding
from backend.schemas import Chunk, DocMeta, carregar_manifesto
from backend.textutil import menciona_pos_graduacao, tokenizar

Modo = Literal["denso", "bm25", "rrf", "hibrido"]
EmbedQuery = Callable[[str], np.ndarray]

# Valor calibrado de MIN_SCORE: ver docs/spec/design.md, seção 11 (preenchido pelo script de calibração)
MIN_SCORE_PADRAO = 0.0


@dataclass
class Candidato:
    chunk: Chunk
    score: float  # score final de ordenação (RRF, já com a hierarquia aplicada)
    score_denso: float
    rank_denso: int | None
    rank_bm25: int | None


@dataclass
class PaginaContexto:
    id: int  # número da citação [n]
    documento: str
    titulo: str
    vigencia: str
    escopo: str
    hierarquia: Literal["norma", "ppc"]
    pagina: int
    artigo: str | None
    texto: str
    score: float


@dataclass
class Resultado:
    pergunta: str
    modo: str
    candidatos: list[Candidato]
    paginas: list[PaginaContexto]
    incluiu_pos: bool  # a pergunta mencionou pós-graduação
    melhor_denso: float
    cobertura: float  # fração dos termos da pergunta presentes nas páginas de contexto
    divergencias: list[dict] = field(default_factory=list)

    @property
    def tem_pos_no_contexto(self) -> bool:
        return any(p.escopo == "pos-graduacao" for p in self.paginas)


def _rotulo_base(artigo: str | None) -> str | None:
    return artigo.split(",")[0] if artigo else None


class Retriever:
    def __init__(
        self,
        index: faiss.Index,
        chunks: list[Chunk],
        paginas: dict[str, dict[str, str]],
        docs: dict[str, DocMeta],
        embed_query: EmbedQuery,
        settings: Settings,
    ) -> None:
        self.index = index
        self.chunks = chunks
        self.paginas = paginas
        self.docs = docs
        self.embed_query = embed_query
        self.s = settings
        self._tokens_chunk = [tokenizar(f"{c.titulo} {c.artigo or ''} {c.texto}") for c in chunks]
        self.bm25 = BM25Okapi(self._tokens_chunk)
        self._eh_pos = np.array([c.escopo == "pos-graduacao" for c in chunks])
        self._eh_ppc = np.array([docs[c.documento].tipo == "ppc" for c in chunks])

    # ---------- construção ----------
    @classmethod
    def carregar(cls, settings: Settings, embed_query: EmbedQuery | None = None) -> "Retriever":
        index, chunks, paginas = carregar_indice(settings.index_dir)
        docs = {d.id: d for d in carregar_manifesto(settings.pdf_dir)}
        return cls(index, chunks, paginas, docs, embed_query or criar_embed_query(settings), settings)

    # ---------- ranking ----------
    def _scores_densos(self, pergunta: str) -> np.ndarray:
        q = np.asarray(self.embed_query(pergunta), dtype="float32").reshape(1, -1)
        scores, ids = self.index.search(q, self.index.ntotal)
        saida = np.zeros(self.index.ntotal, dtype="float32")
        saida[ids[0]] = scores[0]
        return saida

    def buscar(self, pergunta: str, modo: Modo = "hibrido") -> Resultado:
        n = len(self.chunks)
        incluiu_pos = menciona_pos_graduacao(pergunta)
        permitido = np.ones(n, dtype=bool)
        if modo == "hibrido" and not incluiu_pos:
            permitido &= ~self._eh_pos  # padrão: graduação

        denso = self._scores_densos(pergunta)
        tokens_q = tokenizar(pergunta)
        lexico = np.asarray(self.bm25.get_scores(tokens_q), dtype="float64") if tokens_q else np.zeros(n)

        def ranking(valores: np.ndarray, minimo: float | None = None) -> list[int]:
            ordem = np.argsort(-valores, kind="stable")
            return [int(i) for i in ordem if permitido[i] and (minimo is None or valores[i] > minimo)][: self.s.candidatos]

        r_denso = ranking(denso)
        r_bm25 = ranking(lexico, minimo=0.0)
        pos_denso = {i: r + 1 for r, i in enumerate(r_denso)}
        pos_bm25 = {i: r + 1 for r, i in enumerate(r_bm25)}

        if modo == "denso":
            fusao = {i: float(denso[i]) for i in r_denso}
        elif modo == "bm25":
            fusao = {i: float(lexico[i]) for i in r_bm25}
        else:
            fusao = defaultdict(float)
            for pos in (pos_denso, pos_bm25):
                for i, r in pos.items():
                    fusao[i] += 1.0 / (self.s.rrf_k + r)
            if modo == "hibrido":
                for i in fusao:
                    if self._eh_ppc[i]:
                        fusao[i] *= self.s.peso_ppc  # norma específica antes do PPC

        ordem = sorted(fusao, key=lambda i: (-fusao[i], i))[: self.s.top_k]
        candidatos = [
            Candidato(self.chunks[i], float(fusao[i]), float(denso[i]), pos_denso.get(i), pos_bm25.get(i)) for i in ordem
        ]
        paginas = self._expandir_paginas(candidatos, ordenar_hierarquia=(modo == "hibrido"))
        melhor_denso = float(denso[permitido].max()) if permitido.any() else 0.0
        cobertura = self._cobertura(tokens_q, paginas)
        return Resultado(
            pergunta, modo, candidatos, paginas, incluiu_pos, melhor_denso, cobertura,
            detectar_divergencias(paginas) if modo == "hibrido" else [],
        )

    # ---------- expansão para página inteira ----------
    def _expandir_paginas(self, candidatos: list[Candidato], ordenar_hierarquia: bool) -> list[PaginaContexto]:
        escolhidas: list[tuple[str, int, Candidato]] = []
        vistas: set[tuple[str, int]] = set()
        for c in candidatos:
            chave = (c.chunk.documento, c.chunk.pagina)
            if chave in vistas:
                continue
            vistas.add(chave)
            escolhidas.append((c.chunk.documento, c.chunk.pagina, c))
            if len(escolhidas) >= self.s.max_paginas:
                break

        def eh_ppc(item: tuple[str, int, Candidato]) -> bool:
            return self.docs[item[0]].tipo == "ppc"

        if ordenar_hierarquia:
            escolhidas.sort(key=eh_ppc)  # estável: norma específica primeiro, ranking preservado dentro de cada grupo

        saida: list[PaginaContexto] = []
        for n, (doc_id, pagina, cand) in enumerate(escolhidas, start=1):
            texto = self.paginas.get(doc_id, {}).get(str(pagina)) or cand.chunk.texto
            d = self.docs[doc_id]
            saida.append(
                PaginaContexto(
                    id=n, documento=doc_id, titulo=d.titulo, vigencia=d.vigencia, escopo=d.escopo,
                    hierarquia="ppc" if d.tipo == "ppc" else "norma", pagina=pagina,
                    artigo=_rotulo_base(cand.chunk.artigo), texto=texto, score=cand.score,
                )
            )
        return saida

    def artigo_em(self, documento: str, pagina: int, literal: str) -> str | None:
        """Artigo do chunk dessa página que contém o trecho literal (ou o mais parecido)."""
        from rapidfuzz import fuzz

        melhor, melhor_s = None, 0.0
        for c in self.chunks:
            if c.documento != documento or not (c.pagina <= pagina <= c.pagina_fim):
                continue
            s = 100.0 if literal and literal in c.texto else fuzz.partial_ratio(literal, c.texto) * 0.99
            if s > melhor_s:
                melhor, melhor_s = c, s
        return _rotulo_base(melhor.artigo) if melhor and melhor_s >= 60 else None

    @staticmethod
    def _cobertura(tokens_q: list[str], paginas: list[PaginaContexto]) -> float:
        if not tokens_q:
            return 0.0
        presentes: set[str] = set()
        for p in paginas:
            presentes.update(tokenizar(p.texto))
        unicos = set(tokens_q)
        return len(unicos & presentes) / len(unicos)


# ---------- divergência entre PPC e norma específica ----------
_UNIDADES = [
    (re.compile(r"h(?:oras?)?\s*[-/]\s*aula|hora[-\s]aula", re.I), "h-a"),
    (re.compile(r"horas?\b|\bh\b", re.I), "h"),
    (re.compile(r"cr[eé]ditos?", re.I), "créditos"),
    (re.compile(r"per[ií]odos?", re.I), "períodos"),
    (re.compile(r"dias?\b", re.I), "dias"),
    (re.compile(r"meses|m[eê]s\b", re.I), "meses"),
    (re.compile(r"anos?\b", re.I), "anos"),
    (re.compile(r"%|por\s+cento", re.I), "%"),
]
_QTD_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(h(?:oras?)?\s*[-/]\s*aula|horas?|h\b|cr[eé]ditos?|per[ií]odos?|dias?|mes(?:es)?|anos?|%|por\s+cento)", re.I)


def quantidades(texto: str) -> dict[str, set[str]]:
    achados: dict[str, set[str]] = defaultdict(set)
    for valor, unidade in _QTD_RE.findall(texto):
        for padrao, nome in _UNIDADES:
            if padrao.fullmatch(unidade.strip()) or padrao.match(unidade.strip()):
                achados[nome].add(valor.replace(",", "."))
                break
    return achados


def detectar_divergencias(paginas: list[PaginaContexto]) -> list[dict]:
    """Quantidades (com a mesma unidade) que diferem entre norma específica e PPC no contexto."""
    normas = [p for p in paginas if p.hierarquia == "norma"]
    ppcs = [p for p in paginas if p.hierarquia == "ppc"]
    saida: list[dict] = []
    for ppc in ppcs:
        q_ppc = quantidades(ppc.texto)
        for norma in normas:
            q_norma = quantidades(norma.texto)
            for unidade in sorted(set(q_ppc) & set(q_norma)):
                if q_ppc[unidade].isdisjoint(q_norma[unidade]):
                    saida.append(
                        {
                            "unidade": unidade,
                            "norma": {"fonte": norma.id, "valores": sorted(q_norma[unidade])},
                            "ppc": {"fonte": ppc.id, "valores": sorted(q_ppc[unidade])},
                        }
                    )
    return saida


def criar_embed_query(settings: Settings) -> EmbedQuery:
    from sentence_transformers import SentenceTransformer  # import tardio

    modelo = SentenceTransformer(settings.embedding_model, device="cpu")

    def embed(pergunta: str) -> np.ndarray:
        return np.asarray(
            modelo.encode([consulta_para_embedding(pergunta)], normalize_embeddings=True), dtype="float32"
        )[0]

    return embed
