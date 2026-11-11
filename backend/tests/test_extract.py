from __future__ import annotations

import pytest

from backend.extract import (
    ErroRemapeamento,
    aplicar_mapa,
    construir_vocabulario,
    inferir_mapa_glifos,
    limpar_paginas,
    normalizar_pagina,
    validar_remapeamento,
)
from backend.schemas import DocMeta


def _doc(**kw) -> DocMeta:
    base = dict(id="d", arquivo="d.pdf", titulo="D", tipo="resolucao", escopo="graduacao", vigencia="2026", paginas=1)
    return DocMeta(**{**base, **kw})


# --- Limpeza de ruído ---------------------------------------------------------------------
def test_remove_ruido_sei_em_linhas_separadas() -> None:
    pagina = (
        "23/03/26, 16:06\nSEI/UFV - 1894729 - Resolução\n"
        "Art. 1º Fica aprovado o regimento.\n"
        "https://sei.ufv.br/sei/controlador.php?acao=x&id=1… 1/23\n"
    )
    limpas, stats = limpar_paginas([pagina])
    assert limpas[0] == "Art. 1º Fica aprovado o regimento."
    assert stats.linhas_sei == 3


def test_remove_cabecalho_repetido_em_pdf_longo_sem_apagar_conteudo() -> None:
    # Regra: linha de borda que, ignorando dígitos, se repete em >= 60% das páginas é cabeçalho/rodapé.
    # O conteúdo das páginas precisa diferir além dos dígitos.
    assuntos = ["trancamento", "matrícula", "frequência", "aprovação", "desligamento", "calendário"]
    paginas = [f"UFV - Campus Rio Paranaíba\nArt. {i} Regras sobre {a}.\nPágina {i}" for i, a in enumerate(assuntos, start=1)]
    limpas, stats = limpar_paginas(paginas)
    for i, (texto, a) in enumerate(zip(limpas, assuntos), start=1):
        assert f"Art. {i} Regras sobre {a}." in texto
        assert "Campus Rio Paranaíba" not in texto
        assert "Página" not in texto
    assert stats.linhas_repetidas == 12


def test_nao_remove_repeticao_em_documento_curto() -> None:
    limpas, _ = limpar_paginas(["Cabeçalho\nTexto A", "Cabeçalho\nTexto B"])
    assert "Cabeçalho" in limpas[0]


# --- Normalização --------------------------------------------------------------------------
def test_une_linhas_quebradas_e_preserva_inicio_de_artigo_e_paragrafo() -> None:
    linhas = ["Art. 5º O estudante poderá", "solicitar o trancamento", "§ 1º O pedido deve ser", "aprovado.", "I - primeiro", "II - segundo"]
    assert normalizar_pagina(linhas).split("\n") == [
        "Art. 5º O estudante poderá solicitar o trancamento",
        "§ 1º O pedido deve ser aprovado.",
        "I - primeiro",
        "II - segundo",
    ]


def test_art_e_numero_em_linhas_separadas() -> None:
    texto = normalizar_pagina(["CAPÍTULO I", "Art", "1°", "-", "O presente", "regulamento"])
    assert texto.split("\n")[1].startswith("Art 1° - O presente regulamento")


def test_dois_artigos_na_mesma_linha_sao_separados() -> None:
    texto = normalizar_pagina(["Rio Paranaíba. Art 2° - As Atividades Complementares devem"])
    assert texto.split("\n") == ["Rio Paranaíba.", "Art 2° - As Atividades Complementares devem"]


def test_hifen_no_fim_da_linha_une_sem_espaco() -> None:
    assert normalizar_pagina(["Pós-", "Graduação"]) == "Pós-Graduação"


# --- Glifos privados -----------------------------------------------------------------------
VOCAB = construir_vocabulario(["estudantes instituições título cientifica ordem alunos", "art regimento"])


def test_infere_mapa_por_vocabulario() -> None:
    texto = "es\ue044udan\ue044es " * 3 + "ins\ue044i\ue044uições " * 3 + "Ar\ue044. 1"
    mapa = inferir_mapa_glifos(texto, VOCAB)
    assert mapa == {"\ue044": "t"}
    assert "Art. 1" in aplicar_mapa(texto, mapa)


def test_glifo_apos_digito_e_ordinal_nao_ligadura() -> None:
    texto = "Art. 3\uf06f- O TCC\n" * 6
    assert inferir_mapa_glifos(texto, VOCAB) == {"\uf06f": "º"}


def test_resolve_glifo_dependente_de_outro() -> None:
    # \ue046 só aparece junto de \ue044; precisa resolver \ue044 antes
    texto = "es\ue044udan\ue044es " * 3 + "\ue046\ue044ulo " * 3
    mapa = inferir_mapa_glifos(texto, construir_vocabulario(["estudantes título"]))
    assert mapa == {"\ue044": "t", "\ue046": "tí"}


def test_glifo_sem_evidencia_levanta_erro() -> None:
    with pytest.raises(ErroRemapeamento):
        inferir_mapa_glifos("xy\ue099zk " * 5, VOCAB)


def test_validacao_exige_textos_obrigatorios() -> None:
    doc = _doc(validar_contem=["Art.", "Stricto"])
    with pytest.raises(ErroRemapeamento, match="Stricto"):
        validar_remapeamento("Art. 1 Regimento de Pós-Graduação", doc, VOCAB)
    ok = validar_remapeamento("Art. 1 Regimento de Pós-Graduação Stricto Sensu", doc, VOCAB)
    assert ok["contagem_art"] == 1


def test_validacao_falha_se_sobrar_glifo_privado() -> None:
    with pytest.raises(ErroRemapeamento, match="U\\+E099"):
        validar_remapeamento("Art. 1 texto \ue099", _doc(), VOCAB)
