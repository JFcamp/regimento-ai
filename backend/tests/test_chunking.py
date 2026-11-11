from __future__ import annotations

from backend.chunking import _corrigir_numero, dividir_em_janelas, gerar_chunks, montar_unidades
from backend.schemas import DocMeta

DOC = DocMeta(id="doc", arquivo="doc.pdf", titulo="Doc de teste", tipo="resolucao", escopo="graduacao", vigencia="2026", paginas=3)


def _chunks(paginas: dict[int, str], tamanho: int = 800, sobreposicao: int = 150, artigo_max: int = 1000):
    saida = []
    contador = 0
    for u in montar_unidades(DOC, paginas):
        novos, contador, _ = gerar_chunks(u, tamanho, sobreposicao, artigo_max, 20, contador)
        saida.extend(novos)
    return saida


def test_artigo_curto_nao_e_dividido() -> None:
    texto = "Art. 1º Este é um artigo curto que cabe inteiro em um único chunk."
    chunks = _chunks({1: texto})
    assert len(chunks) == 1
    assert chunks[0].texto == texto
    assert chunks[0].artigo == "Art. 1"


def test_cada_artigo_vira_seu_proprio_chunk() -> None:
    chunks = _chunks({1: "Art. 1º Primeiro artigo com texto suficiente.\nArt. 2º Segundo artigo com texto suficiente."})
    assert [c.artigo for c in chunks] == ["Art. 1", "Art. 2"]
    assert "Segundo" not in chunks[0].texto


def test_artigo_longo_divide_por_paragrafo_com_rotulo() -> None:
    corpo = "palavra " * 40  # ~320 caracteres
    texto = f"Art. 5º Caput {corpo}\n§ 1º Um {corpo}\n§ 2º Dois {corpo}\n§ 3º Tres {corpo}"
    chunks = _chunks({1: texto})
    assert len(chunks) >= 2
    assert all(len(c.texto) <= 800 for c in chunks)
    assert chunks[0].artigo == "Art. 5"
    rotulos = [c.artigo for c in chunks]
    assert any(r and "§" in r for r in rotulos)
    # nenhum parágrafo é cortado ao meio quando cabe num chunk
    assert all(c.texto.startswith(("Art.", "§")) for c in chunks)


def test_paragrafo_unico_recebe_rotulo() -> None:
    corpo = "palavra " * 70  # ~560 caracteres; caput + parágrafo passam de article_max (1000)
    chunks = _chunks({1: f"Art. 9º Caput {corpo}\nParágrafo único. {corpo}"})
    assert [c.artigo for c in chunks] == ["Art. 9", "Art. 9, Parágrafo único"]


def test_chunk_guarda_pagina_inicial_e_final() -> None:
    p1 = "Art. 7º " + "a " * 200
    p2 = "continua o mesmo artigo " + "b " * 100
    (c,) = _chunks({3: p1, 4: p2}, artigo_max=2000)
    assert (c.pagina, c.pagina_fim) == (3, 4)
    assert c.id.startswith("doc-p003-")


def test_titulos_de_capitulo_vao_com_o_artigo_seguinte() -> None:
    paginas = {1: "Art. 1º Primeiro artigo do capítulo um.\nCAPÍTULO II DOS PRAZOS\nArt. 2º Segundo artigo, do capítulo dois."}
    c1, c2 = _chunks(paginas)
    assert "CAPÍTULO II" not in c1.texto
    assert c2.texto.startswith("CAPÍTULO II DOS PRAZOS")
    assert c2.artigo == "Art. 2"


def test_corrige_ordinal_lido_como_2_pelo_ocr() -> None:
    assert _corrigir_numero(22, 1) == 2
    assert _corrigir_numero(32, 2) == 3
    assert _corrigir_numero(22, 21) == 22  # artigo 22 verdadeiro
    assert _corrigir_numero(12, 5) == 12  # não confunde com salto legítimo
    paginas = {1: "Art. 1º Primeiro artigo.\nArt. 22 Segundo artigo lido com erro.\nArt. 32 Terceiro artigo lido com erro."}
    assert [c.artigo for c in _chunks(paginas)] == ["Art. 1", "Art. 2", "Art. 3"]


def test_documento_sem_artigos_usa_janelas() -> None:
    texto = " ".join(f"palavra{i}" for i in range(600))
    chunks = _chunks({1: texto})
    assert len(chunks) > 1
    assert all(c.artigo is None for c in chunks)
    assert all(len(c.texto) <= 800 for c in chunks)


def test_janelas_cobrem_o_texto_com_sobreposicao_e_sem_cortar_palavra() -> None:
    texto = " ".join(f"termo{i}" for i in range(300))
    spans = dividir_em_janelas(texto, 800, 150)
    assert spans[0][0] == 0 and spans[-1][1] == len(texto)
    for (_, fim_a), (ini_b, _) in zip(spans, spans[1:]):
        assert ini_b < fim_a  # sobreposição
    for _, fim in spans[:-1]:
        assert texto[fim] == " "  # corta em espaço


def test_descarta_fragmentos_muito_curtos() -> None:
    chunks = _chunks({1: "Art. 1º Texto válido e longo o bastante.\n1/23"})
    assert all(len(c.texto) >= 20 for c in chunks)
