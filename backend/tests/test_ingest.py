"""Testes do pipeline de ingestão: PDF sintético (exclusão/páginas vazias) e o corpus real."""
from __future__ import annotations

import json
import re
from pathlib import Path

import fitz
import pytest

from backend.config import ROOT, Settings
from backend.extract import PUA_RE
from backend.ingest import processar
from backend.schemas import carregar_manifesto


# --- PDF sintético ---------------------------------------------------------------------------
def _pdf_sintetico(pasta: Path) -> Settings:
    doc = fitz.open()
    textos = {
        1: "Art. 1 Esta pagina deve ser indexada normalmente.",
        2: "Art. 2 Esta pagina e a ata escaneada e sera excluida.",
        3: "",  # página sem texto
    }
    for t in textos.values():
        pagina = doc.new_page()
        if t:
            pagina.insert_text((72, 72), t)
    doc.save(pasta / "teste.pdf")
    manifesto = {
        "documentos": [{
            "id": "teste", "arquivo": "teste.pdf", "titulo": "Teste", "tipo": "resolucao",
            "escopo": "graduacao", "vigencia": "2026", "paginas": 3,
            "paginas_excluidas": [2], "motivo_exclusao": "ata sem valor",
        }]
    }
    (pasta / "manifest.json").write_text(json.dumps(manifesto), encoding="utf-8")
    return Settings(pdf_dir=pasta, index_dir=pasta / "index")


def test_pagina_excluida_e_pagina_sem_texto_ficam_fora_e_no_relatorio(tmp_path: Path) -> None:
    settings = _pdf_sintetico(tmp_path)
    chunks, paginas, relatorio = processar(settings, carregar_manifesto(tmp_path))

    assert {c.pagina for c in chunks} == {1}
    assert list(paginas["teste"]) == [1]
    info = relatorio["documentos"][0]
    assert info["paginas_excluidas"] == {"paginas": [2], "motivo": "ata sem valor"}
    assert [p["pagina"] for p in info["paginas_ignoradas"]] == [3]
    assert info["paginas_indexadas"] == 1


def test_arquivo_ausente_levanta_erro(tmp_path: Path) -> None:
    settings = _pdf_sintetico(tmp_path)
    (tmp_path / "teste.pdf").unlink()
    with pytest.raises(FileNotFoundError):
        processar(settings, carregar_manifesto(tmp_path))


# --- Corpus real (data/pdfs) -----------------------------------------------------------------
CORPUS = ROOT / "data" / "pdfs"
pytestmark_corpus = pytest.mark.skipif(not (CORPUS / "manifest.json").exists(), reason="corpus ausente")


@pytest.fixture(scope="module")
def corpus():
    settings = Settings()
    return processar(settings, carregar_manifesto(settings.pdf_dir))


@pytestmark_corpus
def test_corpus_tem_os_10_documentos_e_nenhum_glifo_privado(corpus) -> None:
    chunks, _, relatorio = corpus
    assert relatorio["total"]["documentos"] == 10
    assert relatorio["avisos"] == []
    assert not [c.id for c in chunks if PUA_RE.search(c.texto)]


@pytestmark_corpus
def test_pos_graduacao_remapeada_e_validada(corpus) -> None:
    chunks, _, relatorio = corpus
    info = next(d for d in relatorio["documentos"] if d["id"] == "res-cepe-29-2026-pos-graduacao")
    assert info["remapeamento_glifos"]["validacao"]["contagem_art"] > 0
    assert info["remapeamento_glifos"]["validacao"]["exigidos_presentes"] == ["Art.", "Stricto"]
    art28 = [c for c in chunks if c.documento == "res-cepe-29-2026-pos-graduacao" and c.artigo == "Art. 28"]
    assert art28 and "trancamento" in art28[0].texto
    assert any("Stricto" in c.texto for c in chunks if c.documento == "res-cepe-29-2026-pos-graduacao")


@pytestmark_corpus
def test_ppc_exclui_ata_escaneada_e_registra_no_relatorio(corpus) -> None:
    chunks, paginas, relatorio = corpus
    info = next(d for d in relatorio["documentos"] if d["id"] == "ppc-si-2022")
    assert info["paginas_excluidas"]["paginas"] == list(range(48, 57))
    assert info["paginas_ignoradas"] == []
    indexadas = {c.pagina for c in chunks if c.documento == "ppc-si-2022"}
    assert indexadas.isdisjoint(range(48, 57))
    assert set(paginas["ppc-si-2022"]).isdisjoint(range(48, 57))
    assert info["paginas_indexadas"] == 263


@pytestmark_corpus
@pytest.mark.parametrize(
    ("doc", "total"),
    [
        ("res-cepe-30-2026-regime-didatico", 103),
        ("regulamento-tcc-si", 34),
        ("regulamento-atividades-complementares-si", 10),
        ("res-cepe-6-2022-extensao", 22),
        ("res-cepe-8-2024-mobilidade", 34),
        ("res-cepe-29-2026-pos-graduacao", 104),
    ],
)
def test_numeracao_de_artigos_completa(corpus, doc: str, total: int) -> None:
    chunks, _, _ = corpus
    achados = {int(re.match(r"Art\. (\d+)", c.artigo).group(1)) for c in chunks if c.documento == doc and c.artigo}
    assert achados == set(range(1, total + 1))


@pytestmark_corpus
def test_chunks_chave_para_as_perguntas_de_exemplo(corpus) -> None:
    chunks, _, _ = corpus

    def achar(doc: str, artigo: str) -> str:
        return next(c.texto for c in chunks if c.documento == doc and (c.artigo or "").startswith(artigo))

    assert "210 horas/aula" in achar("regulamento-atividades-complementares-si", "Art. 4")
    assert "dez por cento" in achar("res-cepe-6-2022-extensao", "Art. 8")
    assert "3 (três) períodos" in achar("res-cepe-8-2024-mobilidade", "Art. 5")
    monitoria = [c for c in chunks if c.documento == "regulamento-atividades-complementares-si" and "Monitoria" in c.texto]
    assert any("Máximo 60 h-a" in c.texto and c.pagina == 4 for c in monitoria)
    colacao = " ".join(c.texto for c in chunks if c.documento == "orientacoes-colacao-grau-2026-1")
    assert "31 de julho de 2026" in colacao and "Espaço Multiuso" in colacao


@pytestmark_corpus
def test_tamanho_dos_chunks_respeita_o_limite(corpus) -> None:
    chunks, _, _ = corpus
    assert max(len(c.texto) for c in chunks) <= 1000
    assert all(c.pagina <= c.pagina_fim for c in chunks)
