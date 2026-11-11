"""Ingestão: `python -m backend.ingest` reconstrói o índice do zero a partir de data/pdfs/.

Opções:
  --dry-run   extrai, limpa e gera chunks e relatório, sem embeddings nem escrita em data/index/
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

from backend.chunking import gerar_chunks, montar_unidades
from backend.config import Settings, get_settings
from backend.extract import (
    ErroRemapeamento,
    aplicar_mapa,
    construir_vocabulario,
    inferir_mapa_glifos,
    ler_paginas,
    limpar_paginas,
    tem_glifos_privados,
    validar_remapeamento,
)
from backend.indexer import (
    CACHE_EMBEDDINGS,
    construir_indice,
    criar_embedder,
    gravar_indice,
    limpar_indice,
    verificar_escrita,
)
from backend.schemas import Chunk, DocMeta, carregar_manifesto

log = logging.getLogger("ingest")
MIN_CHARS_PAGINA = 30  # abaixo disso a página é tratada como sem texto


def processar(
    settings: Settings, docs: list[DocMeta]
) -> tuple[list[Chunk], dict[str, dict[int, str]], dict]:
    """Extrai, limpa e divide em chunks. Não escreve nada em disco."""
    brutos: dict[str, list[str]] = {}
    avisos: list[str] = []
    for doc in docs:
        caminho = settings.pdf_dir / doc.arquivo
        if not caminho.exists():
            raise FileNotFoundError(f"PDF do manifesto não encontrado: {caminho}")
        brutos[doc.id] = ler_paginas(caminho)
        if len(brutos[doc.id]) != doc.paginas:
            avisos.append(f"{doc.arquivo}: manifesto diz {doc.paginas} páginas, o PDF tem {len(brutos[doc.id])}")

    com_pua = {d.id for d in docs if any(tem_glifos_privados(p) for p in brutos[d.id])}
    vocab = construir_vocabulario(p for d in docs if d.id not in com_pua for p in brutos[d.id])
    log.info("vocabulário de referência: %d palavras (de %d documentos sem glifos privados)", len(vocab), len(docs) - len(com_pua))

    relatorio_docs: list[dict] = []
    todos_chunks: list[Chunk] = []
    paginas_json: dict[str, dict[int, str]] = {}

    for doc in docs:
        paginas_brutas = brutos[doc.id]
        info: dict = {
            "id": doc.id,
            "arquivo": doc.arquivo,
            "escopo": doc.escopo,
            "vigencia": doc.vigencia,
            "paginas": len(paginas_brutas),
        }

        if doc.id in com_pua:
            texto_total = "\n".join(paginas_brutas)
            mapa = inferir_mapa_glifos(texto_total, vocab)
            paginas_brutas = [aplicar_mapa(p, mapa) for p in paginas_brutas]
            validacao = validar_remapeamento("\n".join(paginas_brutas), doc, vocab)
            info["remapeamento_glifos"] = {
                "mapa": {f"U+{ord(g):04X}": v for g, v in sorted(mapa.items())},
                "validacao": validacao,
            }
            log.info("%s: glifos remapeados %s", doc.arquivo, info["remapeamento_glifos"]["mapa"])
        elif doc.validar_contem:
            validar_remapeamento("\n".join(paginas_brutas), doc, vocab)

        limpas, stats = limpar_paginas(paginas_brutas)
        info["linhas_ruido_removidas"] = {
            "sei": stats.linhas_sei,
            "cabecalho_rodape_repetido": stats.linhas_repetidas,
            "exemplos": stats.exemplos_repetidas,
        }

        excluidas = set(doc.paginas_excluidas)
        paginas_indexadas: dict[int, str] = {}
        ignoradas: list[dict] = []
        for numero, texto in enumerate(limpas, start=1):
            if numero in excluidas:
                continue
            if len(texto.strip()) < MIN_CHARS_PAGINA:
                ignoradas.append({"pagina": numero, "motivo": "sem texto extraível (possível página escaneada)"})
                continue
            paginas_indexadas[numero] = texto
        info["paginas_excluidas"] = {"paginas": sorted(excluidas), "motivo": doc.motivo_exclusao} if excluidas else None
        info["paginas_ignoradas"] = ignoradas
        info["paginas_indexadas"] = len(paginas_indexadas)

        unidades = montar_unidades(doc, paginas_indexadas)
        chunks_doc: list[Chunk] = []
        contador = 0
        descartados = 0
        for u in unidades:
            novos, contador, desc = gerar_chunks(
                u, settings.chunk_size, settings.chunk_overlap, settings.article_max_chars, settings.min_chunk_chars, contador
            )
            chunks_doc.extend(novos)
            descartados += desc

        artigos = {c.artigo.split(",")[0] for c in chunks_doc if c.artigo}
        info["chunks"] = len(chunks_doc)
        info["chunks_descartados_por_tamanho"] = descartados
        info["artigos_detectados"] = len(artigos)
        info["secoes"] = dict(Counter(c.secao for c in chunks_doc if c.secao))
        relatorio_docs.append(info)
        todos_chunks.extend(chunks_doc)
        paginas_json[doc.id] = paginas_indexadas
        log.info(
            "%s: %d págs indexadas, %d chunks, %d artigos, %d ignoradas",
            doc.arquivo, len(paginas_indexadas), len(chunks_doc), len(artigos), len(ignoradas),
        )

    relatorio = {
        "modelo_embeddings": settings.embedding_model,
        "parametros": {
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "article_max_chars": settings.article_max_chars,
        },
        "total": {
            "documentos": len(docs),
            "chunks": len(todos_chunks),
            "paginas_indexadas": sum(d["paginas_indexadas"] for d in relatorio_docs),
        },
        "avisos": avisos,
        "documentos": relatorio_docs,
    }
    return todos_chunks, paginas_json, relatorio


def executar(settings: Settings, dry_run: bool = False) -> dict:
    docs = carregar_manifesto(settings.pdf_dir)
    chunks, paginas, relatorio = processar(settings, docs)
    if dry_run:
        return relatorio

    # Só apaga o índice antigo depois que a extração e a validação passaram
    limpar_indice(settings.index_dir)
    verificar_escrita(settings.index_dir)  # falha cedo, antes dos ~20 min de embeddings em CPU
    embed = criar_embedder(settings.embedding_model, cache_path=settings.index_dir / CACHE_EMBEDDINGS)
    index = construir_indice(chunks, embed)
    gravar_indice(settings.index_dir, index, chunks, paginas, relatorio, settings.embedding_model)
    return relatorio


def main(argv: list[str] | None = None) -> int:
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Reconstrói o índice do Regimento.AI do zero.")
    parser.add_argument("--dry-run", action="store_true", help="não gera embeddings nem grava o índice")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        relatorio = executar(get_settings(), dry_run=args.dry_run)
    except ErroRemapeamento as e:
        log.error("Validação do remapeamento falhou: %s", e)
        log.error("Índice anterior mantido. Sem OCR por decisão do projeto: avise o responsável.")
        return 2
    except FileNotFoundError as e:
        log.error("%s", e)
        return 1

    total = relatorio["total"]
    log.info("Concluído: %d documentos, %d chunks, %d páginas indexadas.", total["documentos"], total["chunks"], total["paginas_indexadas"])
    for aviso in relatorio["avisos"]:
        log.warning(aviso)
    if args.dry_run:
        print(json.dumps(relatorio["total"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
