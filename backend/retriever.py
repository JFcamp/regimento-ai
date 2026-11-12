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
from backend.textutil import menciona_pos_graduacao, normalizar, tokenizar

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
    # por que a página entrou: "ranking" (busca normal), "calendario" (roteamento de datas)
    # ou "ppc_conflito" (página do PPC sobre o mesmo tema de um regulamento recuperado)
    motivo: str = "ranking"


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


# Versão do retriever registrada nos resultados da avaliação
VERSAO_RETRIEVER = "v2"  # v2: páginas obrigatórias (calendário por semestre e PPC em temas com conflito)

# ---------- roteamento de calendário ----------
_MESES = {"JANEIRO": 1, "FEVEREIRO": 2, "MARÇO": 3, "MARCO": 3, "ABRIL": 4, "MAIO": 5, "JUNHO": 6, "JULHO": 7,
          "AGOSTO": 8, "SETEMBRO": 9, "OUTUBRO": 10, "NOVEMBRO": 11, "DEZEMBRO": 12}
_MES_RE = re.compile(r"\b(JANEIRO|FEVEREIRO|MAR[ÇC]O|ABRIL|MAIO|JUNHO|JULHO|AGOSTO|SETEMBRO|OUTUBRO|NOVEMBRO|DEZEMBRO)/(\d{4})")
_SEM_ANO_RE = re.compile(r"\b(20\d\d)\s*[/.\-]\s*([12])\b")
_SEM_ORDINAL_RE = re.compile(r"\b(primeiro|1\s*[ºo°]?)\s+semestre\b|\b(segundo|2\s*[ºo°]?)\s+semestre\b")
# perguntas sobre datas, prazos e períodos (texto já normalizado: minúsculo, sem acento)
_PEDE_CALENDARIO_RE = re.compile(
    r"\b(quando|ate quando|prazo\w*|datas?|dia|dias|inicio|comec\w*|termin\w*|ultimo dia|calendario|"
    r"semestre|periodo letivo)\b"
)

Semestre = tuple[int, int]  # (ano, 1 | 2)


def _semestre_do_mes(m: int, a: int) -> Semestre:
    # março a julho = semestre 1; agosto a dezembro = semestre 2; janeiro e fevereiro fecham o semestre 2 anterior
    return (a, 1) if 3 <= m <= 7 else (a, 2) if m >= 8 else (a - 1, 2)


def semestres_da_pagina(texto: str, mes_anterior: tuple[int, int] | None = None) -> set[Semestre]:
    """Semestres letivos cobertos por uma página do calendário, pelos cabeçalhos "MÊS/ANO". Se o topo da página
    continua o mês da página anterior (sem repetir o cabeçalho), `mes_anterior` (mês, ano) também conta."""
    saida: set[Semestre] = set()
    achados = [(_MESES[mes], int(ano), m.start()) for m in _MES_RE.finditer(texto) for mes, ano in [m.groups()]]
    if mes_anterior and (not achados or achados[0][2] > 40):
        saida.add(_semestre_do_mes(*mes_anterior))
    for m, a, _ in achados:
        saida.add(_semestre_do_mes(m, a))
    return saida


def semestres_do_calendario(paginas: dict[str, str]) -> dict[int, set[Semestre]]:
    saida: dict[int, set[Semestre]] = {}
    ultimo: tuple[int, int] | None = None
    for p in sorted(paginas, key=int):
        texto = paginas[p]
        saida[int(p)] = semestres_da_pagina(texto, ultimo)
        meses = [(_MESES[mes], int(ano)) for mes, ano in _MES_RE.findall(texto)]
        if meses:
            ultimo = meses[-1]
    return saida


# Vocabulário do calendário: a pergunta diz "começa", o calendário escreve "Início" (só para a sub-busca no calendário)
_SINONIMOS_CALENDARIO = [
    (re.compile(r"\bcome[cç]\w*|\bcome[cç]o\b", re.I), "início"),
    (re.compile(r"\btermin\w*|\bacab\w*|\bfim\b", re.I), "término"),
    (re.compile(r"\bat[eé] quando\b|\bprazo\w*|\bat[eé] que dia\b", re.I), "último dia"),
]


def expandir_termos_calendario(pergunta: str) -> str:
    """Troca no lugar (para preservar a ordem das palavras): "quando começa o período" -> "quando início o período"."""
    for padrao, termo in _SINONIMOS_CALENDARIO:
        pergunta = padrao.sub(termo, pergunta)
    return pergunta


def _bigramas(tokens: list[str]) -> set[tuple[str, str]]:
    return set(zip(tokens, tokens[1:]))


def semestre_da_pergunta(pergunta: str) -> tuple[int | None, int] | None:
    """(ano ou None, 1 | 2) se a pergunta cita um semestre: "2026/1", "2026-2", "primeiro semestre"..."""
    texto = normalizar(pergunta)
    m = _SEM_ANO_RE.search(texto)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _SEM_ORDINAL_RE.search(texto)
    if m:
        ano = re.search(r"\b(20\d\d)\b", texto)
        return (int(ano.group(1)) if ano else None), (1 if m.group(1) else 2)
    return None


def pede_calendario(pergunta: str) -> bool:
    return semestre_da_pergunta(pergunta) is not None or _PEDE_CALENDARIO_RE.search(normalizar(pergunta)) is not None


# ---------- conflito com o PPC ----------
# Documentos cujo tema o PPC também trata (com valores ou códigos diferentes): quando um deles entra no contexto,
# a página do PPC sobre o mesmo tema entra junto, para o modelo poder apontar a divergência.
TEMAS_CONFLITO = {
    "regulamento-atividades-complementares-si": "atividades complementares carga horária horas/aula disciplina SIN",
    "res-cepe-6-2022-extensao": "atividades curriculares de extensão carga horária horas/aula disciplina SIN",
}


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
        # calendário: documento do tipo "calendario" e o semestre de cada página
        self._calendario = next((d.id for d in docs.values() if d.tipo == "calendario"), None)
        self._semestres_pagina = semestres_do_calendario(paginas.get(self._calendario or "", {}))
        self._ppc = next((d.id for d in docs.values() if d.tipo == "ppc"), None)

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
        extras = self._paginas_obrigatorias(pergunta, candidatos, incluiu_pos, denso) if modo == "hibrido" else []
        paginas = self._expandir_paginas(candidatos, ordenar_hierarquia=(modo == "hibrido"), extras=extras)
        melhor_denso = float(denso[permitido].max()) if permitido.any() else 0.0
        cobertura = self._cobertura(tokens_q, paginas)
        return Resultado(
            pergunta, modo, candidatos, paginas, incluiu_pos, melhor_denso, cobertura,
            detectar_divergencias(paginas) if modo == "hibrido" else [],
        )

    # ---------- páginas obrigatórias ----------
    def _melhor_chunk(self, indices: list[int], denso: np.ndarray, lexico: np.ndarray) -> int | None:
        """Melhor chunk de um subconjunto, por RRF entre e5 e BM25 calculados só dentro dele."""
        if not indices:
            return None
        r_d = sorted(indices, key=lambda i: (-denso[i], i))
        r_l = sorted(indices, key=lambda i: (-lexico[i], i))
        fusao: dict[int, float] = defaultdict(float)
        for ordem in (r_d, r_l):
            for r, i in enumerate(ordem, start=1):
                fusao[i] += 1.0 / (self.s.rrf_k + r)
        return min(fusao, key=lambda i: (-fusao[i], i))

    def _paginas_obrigatorias(
        self, pergunta: str, candidatos: list[Candidato], incluiu_pos: bool, denso: np.ndarray
    ) -> list[tuple[str, int, Chunk, float, str]]:
        """Páginas que entram no contexto além das escolhidas pelo ranking (doc, página, chunk, score, motivo)."""
        extras: list[tuple[str, int, Chunk, float, str]] = []
        normais = {(c.chunk.documento, c.chunk.pagina) for c in candidatos[: self.s.max_paginas * 2]}
        docs_normais = {c.chunk.documento for c in candidatos}

        # 1) calendário do semestre citado (ou o melhor do calendário, se a pergunta só fala de prazo/data)
        if self._calendario and not incluiu_pos and pede_calendario(pergunta):
            sem = semestre_da_pergunta(pergunta)
            paginas_ok = {
                p for p, sems in self._semestres_pagina.items()
                if sem is None or any(n == sem[1] and (sem[0] is None or a == sem[0]) for a, n in sems)
            }
            idx = [i for i, c in enumerate(self.chunks) if c.documento == self._calendario and c.pagina in paginas_ok]
            tokens_q = tokenizar(expandir_termos_calendario(pergunta))
            lexico = np.asarray(self.bm25.get_scores(tokens_q), dtype="float64")
            # o calendário repete as mesmas palavras em todo trecho; vale mais quem tem a sequência da pergunta
            # ("início período", "último dia", "dia trancamento"): só esses entram no desempate por RRF
            bq = _bigramas(tokens_q)
            pares = {i: len(bq & _bigramas(self._tokens_chunk[i])) for i in idx}
            maior = max(pares.values(), default=0)
            if maior > 0:
                idx = [i for i in idx if pares[i] == maior]
            melhor = self._melhor_chunk(idx, denso, lexico)
            if melhor is not None:
                c = self.chunks[melhor]
                extras.append((c.documento, c.pagina, c, float(denso[melhor]), "calendario"))

        # 2) regulamento com tema que o PPC também trata: traz a página do corpo do PPC sobre o mesmo tema
        if self._ppc:
            for doc_id, tema in TEMAS_CONFLITO.items():
                if doc_id not in docs_normais:
                    continue
                lexico = np.asarray(self.bm25.get_scores(tokenizar(f"{pergunta} {tema}")), dtype="float64")
                # só o corpo do PPC (fora dos anexos), onde estão os valores do curso
                idx = [i for i, c in enumerate(self.chunks) if c.documento == self._ppc and c.secao is None]
                melhor = self._melhor_chunk(idx, denso, lexico)
                if melhor is not None:
                    c = self.chunks[melhor]
                    # o trecho pode atravessar páginas (ex.: PPC p. 17 -> 18): entram todas as que ele cobre
                    for pg in range(c.pagina, c.pagina_fim + 1):
                        if (c.documento, pg) not in normais:
                            extras.append((c.documento, pg, c, float(denso[melhor]), "ppc_conflito"))
        return extras

    # ---------- expansão para página inteira ----------
    def _expandir_paginas(
        self,
        candidatos: list[Candidato],
        ordenar_hierarquia: bool,
        extras: list[tuple[str, int, Chunk, float, str]] | None = None,
    ) -> list[PaginaContexto]:
        escolhidas: list[tuple[str, int, Chunk, float, str]] = []
        vistas: set[tuple[str, int]] = set()
        for c in candidatos:
            chave = (c.chunk.documento, c.chunk.pagina)
            if chave in vistas:
                continue
            vistas.add(chave)
            escolhidas.append((c.chunk.documento, c.chunk.pagina, c.chunk, c.score, "ranking"))
            if len(escolhidas) >= self.s.max_paginas:
                break
        for e in extras or []:  # obrigatórias entram além das MAX_PAGINAS do ranking
            if (e[0], e[1]) not in vistas:
                vistas.add((e[0], e[1]))
                escolhidas.append(e)

        if ordenar_hierarquia:
            # estável: norma específica primeiro, ranking preservado dentro de cada grupo
            escolhidas.sort(key=lambda item: self.docs[item[0]].tipo == "ppc")

        saida: list[PaginaContexto] = []
        for n, (doc_id, pagina, chunk, score, motivo) in enumerate(escolhidas, start=1):
            texto = self.paginas.get(doc_id, {}).get(str(pagina)) or chunk.texto
            d = self.docs[doc_id]
            saida.append(
                PaginaContexto(
                    id=n, documento=doc_id, titulo=d.titulo, vigencia=d.vigencia, escopo=d.escopo,
                    hierarquia="ppc" if d.tipo == "ppc" else "norma", pagina=pagina,
                    artigo=_rotulo_base(chunk.artigo), texto=texto, score=score, motivo=motivo,
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
