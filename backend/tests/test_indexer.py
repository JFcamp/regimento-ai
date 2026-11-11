from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from backend.indexer import (
    ARQUIVOS_INDICE,
    carregar_indice,
    construir_indice,
    gravar_indice,
    embedder_com_cache,
    limpar_indice,
    texto_para_embedding,
    verificar_escrita,
)
from backend.schemas import Chunk


def embed_falso(textos: list[str]) -> np.ndarray:
    """Vetores determinísticos e normalizados, sem baixar modelo."""
    saida = []
    for t in textos:
        v = np.frombuffer(hashlib.sha256(t.encode()).digest(), dtype=np.uint8)[:16].astype("float32") - 127.5
        saida.append(v / np.linalg.norm(v))
    return np.asarray(saida, dtype="float32")


def _chunk(i: int, artigo: str | None = "Art. 1") -> Chunk:
    return Chunk(
        id=f"d-p001-c{i:03d}", documento="d", titulo="Doc", vigencia="2026", escopo="graduacao",
        pagina=1, pagina_fim=1, artigo=artigo, texto=f"texto do trecho número {i}",
    )


def test_texto_indexado_tem_prefixo_e5_e_contexto() -> None:
    t = texto_para_embedding(_chunk(1))
    assert t.startswith("passage: Doc (vigência 2026) - Art. 1\n")
    assert t.endswith("texto do trecho número 1")
    assert "- " not in texto_para_embedding(_chunk(1, artigo=None)).split("\n")[0].split("2026)")[1]


def test_indice_recupera_o_proprio_chunk_e_faz_roundtrip(tmp_path: Path) -> None:
    chunks = [_chunk(i) for i in range(5)]
    index = construir_indice(chunks, embed_falso)
    assert index.ntotal == 5

    gravar_indice(tmp_path, index, chunks, {"d": {1: "texto da página"}}, {"total": {"chunks": 5}}, "modelo-falso")
    for nome in ARQUIVOS_INDICE:
        assert (tmp_path / nome).exists(), nome

    index2, chunks2, paginas = carregar_indice(tmp_path)
    assert [c.id for c in chunks2] == [c.id for c in chunks]
    assert paginas["d"]["1"] == "texto da página"
    consulta = embed_falso([texto_para_embedding(chunks[3])])
    scores, ids = index2.search(consulta, 1)
    assert ids[0][0] == 3 and scores[0][0] > 0.999

    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["n_chunks"] == 5 and meta["dimensao"] == 16 and meta["modelo_embeddings"] == "modelo-falso"


def test_grava_e_le_indice_em_diretorio_com_acentos(tmp_path: Path) -> None:
    # Regressão: faiss.write_index falha em caminhos como "Área de Trabalho" no Windows
    pasta = tmp_path / "Área de Trabalho" / "índice"
    chunks = [_chunk(i) for i in range(3)]
    index = construir_indice(chunks, embed_falso)
    verificar_escrita(pasta)
    gravar_indice(pasta, index, chunks, {"d": {1: "x"}}, {}, "modelo-falso")
    index2, chunks2, _ = carregar_indice(pasta)
    assert index2.ntotal == 3 and len(chunks2) == 3
    assert not (pasta / ".sonda_escrita.faiss").exists()


def test_cache_de_embeddings_retoma_apos_queda(tmp_path: Path) -> None:
    cache = tmp_path / "Área" / "emb_cache.npz"
    textos = [f"trecho {i}" for i in range(10)]
    chamadas: list[int] = []

    def encode(lote: list[str]) -> np.ndarray:
        chamadas.append(len(lote))
        if sum(chamadas) > 6:
            raise RuntimeError("queda simulada")
        return embed_falso(lote)

    with pytest.raises(RuntimeError):
        embedder_com_cache(encode, "m", cache, bloco=3)(textos)
    assert cache.exists()  # os 6 primeiros ficaram gravados

    chamadas.clear()

    def encode_ok(lote: list[str]) -> np.ndarray:
        chamadas.append(len(lote))
        return embed_falso(lote)

    resultado = embedder_com_cache(encode_ok, "m", cache, bloco=3)(textos)
    assert sum(chamadas) == 4  # só os 4 que faltavam
    assert np.allclose(resultado, embed_falso(textos))
    # outro modelo não reaproveita o cache
    chamadas.clear()
    embedder_com_cache(encode_ok, "outro-modelo", cache, bloco=3)(textos)
    assert sum(chamadas) == 10


def test_gravacao_funciona_com_pymupdf_importado_depois_do_faiss(tmp_path: Path) -> None:
    # Regressão: com `fitz` importado depois do `faiss`, faiss.serialize_index falha (conflito de tipos SWIG)
    import subprocess
    import sys

    codigo = (
        "import faiss, numpy as np\nimport fitz\nfrom pathlib import Path\n"
        "from backend.indexer import _gravar_faiss, _ler_faiss\n"
        "i = faiss.IndexFlatIP(4); i.add(np.ones((2, 4), dtype='float32'))\n"
        f"p = Path(r'{tmp_path}') / 'x.faiss'; _gravar_faiss(i, p); print(_ler_faiss(p).ntotal)\n"
    )
    r = subprocess.run([sys.executable, "-W", "ignore", "-c", codigo], capture_output=True, timeout=120)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-400:]
    assert r.stdout.decode().strip() == "2"


def test_limpar_indice_preserva_gitkeep_e_arquivos_alheios(tmp_path: Path) -> None:
    (tmp_path / ".gitkeep").write_text("")
    (tmp_path / "outro.txt").write_text("x")
    for nome in ARQUIVOS_INDICE:
        (tmp_path / nome).write_text("velho")
    limpar_indice(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == [".gitkeep", "outro.txt"]
