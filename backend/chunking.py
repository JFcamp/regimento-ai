"""Divisão do texto em unidades (artigos/seções) e chunks.

A janela de caracteres com sobreposição vem do notebook rag-plantas-medicinais
(`dividir_em_chunks`). Aqui ela é aplicada só quando o artigo não cabe num chunk.
"""
from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

from backend.extract import detectar_secao
from backend.schemas import Chunk, DocMeta

ARTIGO_RE = re.compile(r"^Art\.?\s*(\d+)\s*[º°o]?")
TITULO_RE = re.compile(r"^(CAPÍTULO|TÍTULO|Seção|SEÇÃO)\b")
PARAGRAFO_RE = re.compile(r"^(§\s*(\d+)\s*[º°o]?|Parágrafo\s+[Úú]nico)")


@dataclass(frozen=True)
class Unidade:
    """Trecho contínuo de um documento: um artigo, ou um bloco sem artigo."""

    documento: DocMeta
    artigo: str | None
    secao: str | None
    texto: str
    # (offset do início da linha no texto, página) em ordem crescente
    marcas_pagina: tuple[tuple[int, int], ...]

    def pagina_em(self, offset: int) -> int:
        inicios = [m[0] for m in self.marcas_pagina]
        i = bisect_right(inicios, max(offset, 0)) - 1
        return self.marcas_pagina[max(i, 0)][1]


@dataclass
class _Rascunho:
    artigo: str | None
    secao: str | None
    linhas: list[tuple[int, str]]  # (página, linha)


def _fechar(doc: DocMeta, r: _Rascunho) -> Unidade | None:
    if not r.linhas:
        return None
    partes: list[str] = []
    marcas: list[tuple[int, int]] = []
    offset = 0
    for pagina, linha in r.linhas:
        marcas.append((offset, pagina))
        partes.append(linha)
        offset += len(linha) + 1
    return Unidade(doc, r.artigo, r.secao, "\n".join(partes), tuple(marcas))


def _corrigir_numero(n: int, anterior: int | None) -> int:
    """Camada de texto de PDFs digitalizados lê "Art. 3º" como "Art. 32". Se o número foge da sequência
    mas o dígito inicial é exatamente o artigo esperado, usa o dígito inicial."""
    if anterior is not None and n != anterior + 1 and n >= 10 and n % 10 == 2 and n // 10 == anterior + 1:
        return n // 10
    return n


def montar_unidades(doc: DocMeta, paginas: dict[int, str]) -> list[Unidade]:
    """Quebra as páginas (já limpas) em unidades. Um novo artigo ou anexo abre uma nova unidade."""
    unidades: list[Unidade] = []
    atual = _Rascunho(None, None, [])
    secao: str | None = None

    def abrir(artigo: str | None, nova_secao: str | None) -> None:
        nonlocal atual
        u = _fechar(doc, atual)
        if u:
            unidades.append(u)
        atual = _Rascunho(artigo, nova_secao, [])

    anterior: int | None = None  # último número de artigo, para corrigir o "º" lido como "2" pelo OCR
    titulos: list[tuple[int, str]] = []  # títulos de capítulo/seção, anexados ao artigo que vem depois

    for numero in sorted(paginas):
        texto = paginas[numero]
        achada = detectar_secao(texto)
        if achada and achada != secao:
            secao = achada
            abrir(None, secao)  # mudar de anexo reinicia o artigo corrente
            anterior = None
        for linha in texto.splitlines():
            if TITULO_RE.match(linha):
                titulos.append((numero, linha))
                continue
            m = ARTIGO_RE.match(linha)
            if m:
                n = _corrigir_numero(int(m.group(1)), anterior)
                abrir(f"Art. {n}", secao)
                anterior = n
            atual.linhas.extend(titulos)
            titulos = []
            atual.linhas.append((numero, linha))
    atual.linhas.extend(titulos)
    u = _fechar(doc, atual)
    if u:
        unidades.append(u)
    return unidades


def dividir_em_janelas(texto: str, tamanho: int, sobreposicao: int) -> list[tuple[int, int]]:
    """Janelas (início, fim) de ~`tamanho` caracteres, sem cortar palavras. Porta do notebook."""
    spans: list[tuple[int, int]] = []
    inicio = 0
    while inicio < len(texto):
        fim = min(inicio + tamanho, len(texto))
        if fim < len(texto):
            corte = max(texto.rfind(" ", inicio, fim), texto.rfind("\n", inicio, fim))
            if corte > inicio + tamanho // 2:
                fim = corte
        spans.append((inicio, fim))
        if fim >= len(texto):
            break
        inicio = fim - sobreposicao
    return spans


def _rotulo_paragrafo(linha: str, artigo: str | None) -> str | None:
    m = PARAGRAFO_RE.match(linha)
    if not m:
        return None
    if m.group(2):
        n = int(m.group(2))
        rotulo = f"§ {n}º" if n <= 9 else f"§ {n}"
    else:
        rotulo = "Parágrafo único"
    return f"{artigo}, {rotulo}" if artigo else rotulo


def _segmentos(u: Unidade) -> list[tuple[int, int, str | None]]:
    """Divide a unidade em caput + parágrafos: (início, fim, rótulo)."""
    segmentos: list[tuple[int, int, str | None]] = []
    offset = 0
    inicio = 0
    rotulo: str | None = u.artigo
    for linha in u.texto.split("\n"):
        novo = _rotulo_paragrafo(linha, u.artigo)
        if novo and offset > inicio:
            segmentos.append((inicio, offset - 1, rotulo))
            inicio, rotulo = offset, novo
        elif novo:
            rotulo = novo
        offset += len(linha) + 1
    segmentos.append((inicio, len(u.texto), rotulo))
    return segmentos


def _spans_da_unidade(
    u: Unidade, tamanho: int, sobreposicao: int, artigo_max: int
) -> list[tuple[int, int, str | None]]:
    texto = u.texto
    if u.artigo is not None and len(texto) <= artigo_max:
        return [(0, len(texto), u.artigo)]
    if u.artigo is None:
        return [(a, b, None) for a, b in dividir_em_janelas(texto, tamanho, sobreposicao)]

    # Artigo longo: empacota caput e parágrafos até `tamanho`; parágrafo maior que isso vira janelas
    resultado: list[tuple[int, int, str | None]] = []
    atual: tuple[int, int, str | None] | None = None
    for ini, fim, rotulo in _segmentos(u):
        if fim - ini > tamanho:
            if atual:
                resultado.append(atual)
                atual = None
            for a, b in dividir_em_janelas(texto[ini:fim], tamanho, sobreposicao):
                resultado.append((ini + a, ini + b, rotulo))
        elif atual and fim - atual[0] <= tamanho:
            atual = (atual[0], fim, atual[2])
        else:
            if atual:
                resultado.append(atual)
            atual = (ini, fim, rotulo)
    if atual:
        resultado.append(atual)
    return resultado


def gerar_chunks(
    u: Unidade, tamanho: int, sobreposicao: int, artigo_max: int, min_chars: int, contador: int
) -> tuple[list[Chunk], int, int]:
    """Chunks de uma unidade. Retorna (chunks, próximo contador, descartados por serem curtos demais)."""
    chunks: list[Chunk] = []
    descartados = 0
    for ini, fim, rotulo in _spans_da_unidade(u, tamanho, sobreposicao, artigo_max):
        bruto = u.texto[ini:fim]
        texto = bruto.strip()
        if len(texto) < min_chars:
            descartados += 1
            continue
        ini_real = ini + (len(bruto) - len(bruto.lstrip()))
        fim_real = ini_real + len(texto)
        pagina = u.pagina_em(ini_real)
        chunks.append(
            Chunk(
                id=f"{u.documento.id}-p{pagina:03d}-c{contador:03d}",
                documento=u.documento.id,
                titulo=u.documento.titulo,
                vigencia=u.documento.vigencia,
                escopo=u.documento.escopo,
                pagina=pagina,
                pagina_fim=u.pagina_em(max(fim_real - 1, ini_real)),
                artigo=rotulo if rotulo is not None else u.artigo,
                secao=u.secao,
                texto=texto,
            )
        )
        contador += 1
    return chunks, contador, descartados
