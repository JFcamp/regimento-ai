"""Embeddings (multilingual-e5-base) e índice FAISS. Porta do notebook rag-plantas-medicinais."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Callable

import faiss
import numpy as np

from backend.schemas import Chunk

EmbedFn = Callable[[list[str]], np.ndarray]

ARQUIVOS_INDICE = ("index.faiss", "chunks.json", "paginas.json", "ingest_report.json", "meta.json")


def texto_para_embedding(c: Chunk) -> str:
    """Texto indexado: prefixo e5 'passage:' + título/vigência/artigo (distingue normas parecidas) + trecho."""
    cabecalho = f"{c.titulo} (vigência {c.vigencia})"
    if c.artigo:
        cabecalho += f" - {c.artigo}"
    return f"passage: {cabecalho}\n{c.texto}"


def consulta_para_embedding(pergunta: str) -> str:
    return f"query: {pergunta}"


CACHE_EMBEDDINGS = "emb_cache.npz"  # em data/index/ (ignorado pelo git); não faz parte do índice final


def _carregar_cache(caminho: Path | None) -> dict[str, np.ndarray]:
    if caminho is None or not caminho.exists():
        return {}
    try:
        with np.load(caminho, allow_pickle=False) as z:
            return {str(k): v for k, v in zip(z["chaves"], z["vetores"])}
    except Exception:  # cache corrompido por uma queda no meio da gravação: recomeça sem ele
        return {}


def _gravar_cache(caminho: Path, cache: dict[str, np.ndarray]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(caminho.name + ".tmp")
    with open(temporario, "wb") as f:
        np.savez(f, chaves=np.array(list(cache)), vetores=np.vstack(list(cache.values())))
    temporario.replace(caminho)


def embedder_com_cache(
    encode: Callable[[list[str]], np.ndarray],
    nome_modelo: str,
    cache_path: Path | None,
    bloco: int = 64,
) -> EmbedFn:
    """Calcula embeddings em blocos e grava cada bloco em disco. Se o processo cair (queda, reinício da
    janela), a próxima execução reaproveita o que já foi calculado. A chave inclui modelo e texto."""
    from tqdm import tqdm

    cache = _carregar_cache(cache_path)

    def embed(textos: list[str]) -> np.ndarray:
        chaves = [hashlib.sha256(f"{nome_modelo}\0{t}".encode()).hexdigest() for t in textos]
        faltam = [i for i, k in enumerate(chaves) if k not in cache]
        print(f"Embeddings: {len(textos) - len(faltam)} em cache, {len(faltam)} a calcular", flush=True)
        with tqdm(total=len(faltam), desc="Embeddings", unit="chunk") as barra:
            for ini in range(0, len(faltam), bloco):
                idx = faltam[ini : ini + bloco]
                novos = np.asarray(encode([textos[i] for i in idx]), dtype="float32")
                for i, v in zip(idx, novos):
                    cache[chaves[i]] = v
                if cache_path is not None:
                    _gravar_cache(cache_path, cache)
                barra.update(len(idx))
        return np.vstack([cache[k] for k in chaves]).astype("float32")

    return embed


def criar_embedder(nome_modelo: str, batch_size: int = 32, cache_path: Path | None = None) -> EmbedFn:
    from sentence_transformers import SentenceTransformer  # import tardio: carrega torch só quando preciso

    modelo = SentenceTransformer(nome_modelo, device="cpu")

    def encode(textos: list[str]) -> np.ndarray:
        emb = modelo.encode(textos, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(emb, dtype="float32")

    return embedder_com_cache(encode, nome_modelo, cache_path)


def construir_indice(chunks: list[Chunk], embed: EmbedFn) -> faiss.Index:
    """IndexFlatIP sobre vetores normalizados = similaridade de cosseno."""
    emb = np.asarray(embed([texto_para_embedding(c) for c in chunks]), dtype="float32")
    if emb.ndim != 2 or emb.shape[0] != len(chunks):
        raise ValueError(f"embeddings com formato inesperado: {emb.shape} para {len(chunks)} chunks")
    index = faiss.IndexFlatIP(emb.shape[1])
    index.add(emb)
    return index


def _serializar(index: faiss.Index) -> bytes:
    """Bytes do índice sem `faiss.serialize_index`.

    PyMuPDF e FAISS são gerados com SWIG; se o `fitz` é importado depois do `faiss`, o `std::vector<uint8_t>`
    passa a ser devolvido como `pymupdf.mupdf.vectoruc` e o `serialize_index` falha (AssertionError em
    vector_to_array). Ler o buffer pelo ponteiro evita depender da ordem dos imports.
    """
    partes: list[bytes] = []
    escritor = faiss.PyCallbackIOWriter(lambda b: partes.append(bytes(b)))
    faiss.write_index(index, escritor)
    del escritor  # descarrega o buffer interno do escritor
    return b"".join(partes)


def _gravar_faiss(index: faiss.Index, caminho: Path) -> None:
    """O FAISS (C++) não abre caminhos com acentos no Windows (ex.: 'Área de Trabalho'),
    então serializamos em memória e deixamos o Python gravar o arquivo."""
    caminho.write_bytes(_serializar(index))


def _ler_faiss(caminho: Path) -> faiss.Index:
    leitor = faiss.PyCallbackIOReader(io.BytesIO(caminho.read_bytes()).read)
    return faiss.read_index(leitor)


def verificar_escrita(index_dir: Path) -> None:
    """Falha cedo (antes de gastar minutos em embeddings) se não for possível gravar o índice."""
    index_dir.mkdir(parents=True, exist_ok=True)
    sonda = index_dir / ".sonda_escrita.faiss"
    try:
        _gravar_faiss(faiss.IndexFlatIP(2), sonda)
        _ler_faiss(sonda)
    finally:
        sonda.unlink(missing_ok=True)


def limpar_indice(index_dir: Path) -> None:
    """Apaga só os arquivos conhecidos do índice (reconstrução do zero), preservando o .gitkeep."""
    index_dir.mkdir(parents=True, exist_ok=True)
    for nome in ARQUIVOS_INDICE:
        (index_dir / nome).unlink(missing_ok=True)


def gravar_indice(
    index_dir: Path,
    index: faiss.Index,
    chunks: list[Chunk],
    paginas: dict[str, dict[int, str]],
    relatorio: dict,
    modelo: str,
) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    _gravar_faiss(index, index_dir / "index.faiss")
    conteudo = json.dumps([c.model_dump() for c in chunks], ensure_ascii=False)
    (index_dir / "chunks.json").write_text(conteudo, encoding="utf-8")
    # Texto de página inteira (limpo) para a recuperação por página da Etapa 3
    (index_dir / "paginas.json").write_text(json.dumps(paginas, ensure_ascii=False), encoding="utf-8")
    (index_dir / "ingest_report.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    meta = {
        "modelo_embeddings": modelo,
        "dimensao": index.d,
        "n_chunks": len(chunks),
        "hash_chunks": hashlib.sha256(conteudo.encode("utf-8")).hexdigest(),
    }
    (index_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def carregar_indice(index_dir: Path) -> tuple[faiss.Index, list[Chunk], dict[str, dict[str, str]]]:
    index = _ler_faiss(index_dir / "index.faiss")
    chunks = [Chunk.model_validate(c) for c in json.loads((index_dir / "chunks.json").read_text("utf-8"))]
    paginas = json.loads((index_dir / "paginas.json").read_text("utf-8"))
    return index, chunks, paginas
