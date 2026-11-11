"""Extração de texto dos PDFs: leitura por página, remapeamento de glifos privados, limpeza de ruído.

Sem OCR (decisão do projeto): páginas sem texto são excluídas/registradas no relatório, e um
remapeamento de glifos que não passa na validação interrompe a ingestão com erro explícito.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import fitz  # PyMuPDF

from backend.schemas import DocMeta

# --- Glifos da área de uso privado (PUA) -------------------------------------------------
PUA_RE = re.compile(r"[\ue000-\uf8ff]")
# Palavras, incluindo letras acentuadas e glifos privados (que o \w do Python não cobre)
PALAVRA_RE = re.compile(r"[A-Za-zÀ-ÿ\ue000-\uf8ff]+")
# Sequências que PDFs costumam trocar por um único glifo (ligaduras, letras isoladas e ligaduras acentuadas)
CANDIDATAS = (
    "t", "f", "fi", "fl", "ff", "ffi", "ffl", "ti", "tt", "tr", "tri", "ct", "st", "ft",
    "tí", "tá", "tó", "fí", "fé",
)
# Termos latinos/ingleses do domínio que não aparecem nos outros PDFs (usados só para validar candidatas)
VOCAB_EXTRA = frozenset(
    {"doctor", "magister", "stricto", "sensu", "scientiae", "vitae", "curriculum", "caput", "memoriam",
     "degree", "joint", "dual", "offshore", "campus", "campi", "lato",
     # Palavras raras no corpus, conferidas na página renderizada do doc 10 (arts. 23 e 45)
     "fluxo", "conflito", "conflitos"}
)
MIN_LETRAS_EVIDENCIA = 3  # token com menos letras (fora o glifo) não vale como evidência
RAZAO_ORDINAL = 0.9  # fração das ocorrências do glifo logo após um dígito para tratá-lo como "º"
MIN_ORDINAIS = 5


class ErroRemapeamento(RuntimeError):
    """O remapeamento de glifos privados não passou na validação."""


def ler_paginas(pdf: Path) -> list[str]:
    """Texto bruto de cada página (índice 0 = página 1)."""
    with fitz.open(pdf) as doc:
        return [pagina.get_text() for pagina in doc]


def tem_glifos_privados(texto: str) -> bool:
    return PUA_RE.search(texto) is not None


def construir_vocabulario(textos: Iterable[str]) -> set[str]:
    """Palavras minúsculas (>= 2 letras) de textos sem glifos privados."""
    vocab: set[str] = set(VOCAB_EXTRA)
    for texto in textos:
        for p in PALAVRA_RE.findall(texto):
            if not PUA_RE.search(p) and len(p) >= 2:
                vocab.add(p.lower())
    return vocab


def aplicar_mapa(texto: str, mapa: dict[str, str]) -> str:
    return texto.translate(str.maketrans(mapa)) if mapa else texto


def inferir_mapa_glifos(texto: str, vocab: set[str]) -> dict[str, str]:
    """Descobre o que cada glifo privado representa, testando candidatas contra o vocabulário.

    Para cada glifo, só consideram-se palavras onde ele é o único glifo ainda desconhecido; assim
    "cien\\ue046\\ue02fca" é resolvido depois que \\ue046 e \\ue02f aparecem sozinhos em outras palavras.
    Levanta ErroRemapeamento se algum glifo ficar ambíguo ou sem solução.
    """
    mapa: dict[str, str] = {}

    # Passo 1: glifo que quase sempre vem logo após um dígito é o indicador ordinal ("Art. 3º")
    todos = Counter(PUA_RE.findall(texto))
    for g, total_g in todos.items():
        apos_digito = len(re.findall(rf"\d{re.escape(g)}", texto))
        if total_g >= MIN_ORDINAIS and apos_digito / total_g >= RAZAO_ORDINAL:
            mapa[g] = "º"
    texto = aplicar_mapa(texto, mapa)

    # Passo 2: palavras com glifos desconhecidos, validadas contra o vocabulário
    tokens = Counter(p for p in PALAVRA_RE.findall(texto) if PUA_RE.search(p))
    freq_glifos: Counter[str] = Counter()
    for tok, n in tokens.items():
        for ch in tok:
            if PUA_RE.match(ch):
                freq_glifos[ch] += n

    pendentes = [g for g, _ in freq_glifos.most_common()]
    progresso = True
    while pendentes and progresso:
        progresso = False
        for g in list(pendentes):
            alvo = [
                (tok, n)
                for tok, n in tokens.items()
                if g in tok
                and set(PUA_RE.findall(aplicar_mapa(tok, mapa))) == {g}
                and len(PUA_RE.sub("", aplicar_mapa(tok, mapa))) >= MIN_LETRAS_EVIDENCIA
            ]
            if not alvo:
                continue
            total = sum(n for _, n in alvo)
            pontos = {
                cand: sum(n for tok, n in alvo if aplicar_mapa(tok, mapa).replace(g, cand).lower() in vocab)
                for cand in CANDIDATAS
            }
            melhor = max(pontos.values())
            if melhor == 0:
                continue
            empatadas = [c for c, p in pontos.items() if p == melhor]
            if len(empatadas) > 1:
                continue
            if melhor / total < 0.6 or (melhor < 2 and total > 2):
                continue
            mapa[g] = empatadas[0]
            pendentes.remove(g)
            progresso = True

    if pendentes:
        detalhes = ", ".join(f"U+{ord(g):04X} (x{freq_glifos[g]})" for g in pendentes)
        raise ErroRemapeamento(f"Glifos privados sem mapeamento confiável: {detalhes}")
    return mapa


def validar_remapeamento(texto: str, doc: DocMeta, vocab: set[str]) -> dict[str, object]:
    """Confere o texto remapeado. Levanta ErroRemapeamento se qualquer critério falhar."""
    restantes = sorted({f"U+{ord(c):04X}" for c in PUA_RE.findall(texto)})
    if restantes:
        raise ErroRemapeamento(f"{doc.arquivo}: ainda há glifos privados após o remapeamento: {restantes}")
    exigidos = list(doc.validar_contem)
    ausentes = [s for s in exigidos if s not in texto]
    if ausentes:
        raise ErroRemapeamento(f"{doc.arquivo}: o texto remapeado não contém {ausentes}")
    palavras = [p.lower() for p in PALAVRA_RE.findall(texto) if len(p) >= 4]
    taxa = sum(1 for p in palavras if p in vocab) / max(len(palavras), 1)
    return {
        "contagem_art": texto.count("Art."),
        "exigidos_presentes": exigidos,
        "taxa_vocabulario": round(taxa, 3),
    }


# --- Limpeza de ruído ----------------------------------------------------------------------
# Cabeçalho do SEI: "23/03/26, 16:06 SEI/UFV - 1894729 - Resolução"
# (na extração real, data/hora, "SEI/UFV - n - Resolução" e a URL costumam vir em linhas separadas)
SEI_CABECALHO_RE = re.compile(
    r"^\s*(\d{2}/\d{2}/\d{2,4},?\s+\d{2}:\d{2}(\s+SEI/UFV\b.*)?|SEI/UFV\s*-\s*\d+\s*-.*)\s*$"
)
# Rodapé do SEI: URL do processo no sei.ufv.br (o "n/N" da página é removido pela detecção de repetição)
SEI_URL_RE = re.compile(r"^\s*https?://sei\.\S+")
# Início de estrutura normativa: não deve ser unido à linha anterior
ESTRUTURA_RE = re.compile(
    r"^(Art\.?\s*\d+|§\s*\d+|Parágrafo\s+[Úú]nico|CAPÍTULO|TÍTULO|Seção|SEÇÃO|ANEXO"
    r"|[IVXL]{1,6}\s*[-–—]\s|[a-z]\)\s|Tabela\s+\d+)"
)
# "... Paranaíba. Art 2° - As ..." (dois artigos na mesma linha)
ARTIGO_INLINE_RE = re.compile(r"(?<=[\.;:])\s+(?=Art\.?\s*\d+\s*[º°o]?\s*[-–.]\s)")
BORDA_LINHAS = 4  # quantas linhas do topo e do rodapé entram na detecção de cabeçalhos repetidos
LIMIAR_REPETICAO = 0.6
MIN_PAGINAS_REPETICAO = 4


@dataclass
class EstatisticasLimpeza:
    linhas_sei: int = 0
    linhas_repetidas: int = 0
    exemplos_repetidas: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.linhas_sei + self.linhas_repetidas


def _chave_borda(linha: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\d", "#", linha.strip().lower()))


def normalizar_pagina(linhas: list[str]) -> str:
    """Une linhas quebradas pela diagramação, preservando o início de artigos, incisos e parágrafos."""
    # "Art" sozinho numa linha seguido do número na próxima ("Art\n1°\n-\nO presente...")
    unidas: list[str] = []
    for bruta in linhas:
        if unidas and re.fullmatch(r"\s*Art\.?\s*", unidas[-1]) and re.match(r"\s*\d", bruta):
            unidas[-1] = unidas[-1].strip() + " " + bruta.strip()
        else:
            unidas.append(bruta)

    saida: list[str] = []
    for bruta in unidas:
        for parte in ARTIGO_INLINE_RE.sub("\n", bruta).split("\n"):
            linha = re.sub(r"[ \t\u00a0]+", " ", parte).strip()
            if not linha:
                continue
            if saida and not ESTRUTURA_RE.match(linha):
                # palavra hifenizada na quebra de linha ("Pós-" + "Graduação"); um "-" solto é separador
                colar = re.search(r"[A-Za-zÀ-ÿ]-$", saida[-1]) is not None
                saida[-1] = saida[-1] + linha if colar else saida[-1] + " " + linha
            else:
                saida.append(linha)
    return "\n".join(saida)


def limpar_paginas(paginas: list[str]) -> tuple[list[str], EstatisticasLimpeza]:
    """Remove ruído do SEI e cabeçalhos/rodapés repetidos e normaliza quebras de linha."""
    stats = EstatisticasLimpeza()

    sem_sei: list[list[str]] = []
    for texto in paginas:
        mantidas: list[str] = []
        for linha in texto.splitlines():
            if SEI_CABECALHO_RE.match(linha) or SEI_URL_RE.match(linha):
                stats.linhas_sei += 1
            else:
                mantidas.append(linha)
        sem_sei.append(mantidas)

    repetidas: set[str] = set()
    if len(paginas) >= MIN_PAGINAS_REPETICAO:
        contagem: Counter[str] = Counter()
        for linhas in sem_sei:
            nao_vazias = [l for l in linhas if l.strip()]
            bordas = nao_vazias[:BORDA_LINHAS] + nao_vazias[-BORDA_LINHAS:]
            contagem.update({_chave_borda(l) for l in bordas})
        minimo = LIMIAR_REPETICAO * len(paginas)
        repetidas = {k for k, n in contagem.items() if n >= minimo and k}

    limpas: list[str] = []
    for linhas in sem_sei:
        nao_vazias_idx = [i for i, l in enumerate(linhas) if l.strip()]
        indices_borda = set(nao_vazias_idx[:BORDA_LINHAS] + nao_vazias_idx[-BORDA_LINHAS:])
        mantidas = []
        for i, linha in enumerate(linhas):
            if i in indices_borda and _chave_borda(linha) in repetidas:
                stats.linhas_repetidas += 1
                if len(stats.exemplos_repetidas) < 5 and linha.strip() not in stats.exemplos_repetidas:
                    stats.exemplos_repetidas.append(linha.strip()[:100])
            else:
                mantidas.append(linha)
        limpas.append(normalizar_pagina(mantidas))
    return limpas, stats


ANEXO_RE = re.compile(r"\bANEXO\s+([IVXL]+)\b")


def detectar_secao(texto_pagina: str) -> str | None:
    """Rótulo de anexo no topo da página (ex.: 'Anexo IV'), usado no PPC."""
    m = ANEXO_RE.search(texto_pagina[:300])
    return f"Anexo {m.group(1)}" if m else None
