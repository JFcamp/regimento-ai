"""Páginas obrigatórias do retriever: calendário por semestre e PPC em temas com conflito."""
from __future__ import annotations

import numpy as np
import pytest

from backend.config import ROOT, Settings
from backend.retriever import (
    Retriever,
    expandir_termos_calendario,
    pede_calendario,
    semestre_da_pergunta,
    semestres_da_pagina,
    semestres_do_calendario,
)


# ---------------------------------------------------------------- funções puras
@pytest.mark.parametrize(
    ("pergunta", "esperado"),
    [
        ("Até quando posso trancar em 2026/1?", (2026, 1)),
        ("prazo de 2026-2", (2026, 2)),
        ("aulas do primeiro semestre de 2026", (2026, 1)),
        ("o que acontece no 2º semestre?", (None, 2)),
        ("Qual a nota mínima?", None),
    ],
)
def test_semestre_da_pergunta(pergunta, esperado) -> None:
    assert semestre_da_pergunta(pergunta) == esperado


@pytest.mark.parametrize("pergunta", [
    "Até quando posso trancar a matrícula?", "Quando começam as aulas?", "Qual o prazo para entregar?",
    "Qual o último dia de matrícula?", "Início do semestre"])
def test_pede_calendario(pergunta) -> None:
    assert pede_calendario(pergunta)


@pytest.mark.parametrize("pergunta", ["Qual a nota mínima para aprovação?", "Quantas horas de monitoria contam?"])
def test_nao_pede_calendario(pergunta) -> None:
    assert not pede_calendario(pergunta)


def test_semestres_por_cabecalho_e_continuacao_de_pagina() -> None:
    assert semestres_da_pagina("MARÇO/2026 02 segunda-feira Início do período letivo") == {(2026, 1)}
    assert semestres_da_pagina("SETEMBRO/2026 ...") == {(2026, 2)}
    assert semestres_da_pagina("JANEIRO/2026 Colação") == {(2025, 2)}
    paginas = {
        "1": "JUNHO/2026 itens",
        "2": "30 - CAF quinta-feira Colação de Grau 31 - CRP sexta-feira Colação de Grau AGOSTO/2026 Início do período",
    }
    # a p. 2 começa ainda em junho/julho (sem repetir o cabeçalho) e depois entra em agosto
    assert semestres_do_calendario(paginas) == {1: {(2026, 1)}, 2: {(2026, 1), (2026, 2)}}


def test_sinonimos_preservam_a_ordem() -> None:
    assert expandir_termos_calendario("Quando começa o período letivo?") == "Quando início o período letivo?"
    assert expandir_termos_calendario("Até quando posso trancar?").startswith("último dia")


# ---------------------------------------------------------------- índice real (sem carregar o modelo de embeddings)
INDICE = ROOT / "data" / "index" / "index.faiss"


@pytest.fixture(scope="module")
def ret() -> Retriever:
    if not INDICE.exists():
        pytest.skip("índice não gerado")
    s = Settings()
    r = Retriever.carregar(s, embed_query=lambda q: np.zeros(768, dtype="float32"))
    return r


_SCRIPT_REAL = r"""
import json, sys
from backend.config import get_settings
from backend.retriever import Retriever
r = Retriever.carregar(get_settings())
saida = {}
for q in json.loads(sys.argv[1]):
    res = r.buscar(q)
    saida[q] = {"paginas": [[p.documento, p.pagina, p.motivo, p.hierarquia] for p in res.paginas],
                "divergencias": res.divergencias}
print("JSON:" + json.dumps(saida, ensure_ascii=False))
"""

CONFLITO = [
    "Qual a carga horária de atividades complementares exigida no curso de Sistemas de Informação?",
    "Em qual disciplina as atividades complementares são registradas?",
]


@pytest.fixture(scope="module")
def real() -> dict:
    """Com o modelo e5 de verdade (~1 min): a escolha da página do PPC depende do ranking denso. Roda em subprocesso
    porque importar o PyTorch dentro do pytest, depois do FAISS, derruba o processo no Windows (conflito de DLLs)."""
    import json
    import subprocess
    import sys

    if not INDICE.exists():
        pytest.skip("índice não gerado")
    r = subprocess.run([sys.executable, "-X", "utf8", "-W", "ignore", "-c", _SCRIPT_REAL, json.dumps(CONFLITO)],
                       capture_output=True, timeout=600, cwd=ROOT, env={**__import__("os").environ, "PYTHONPATH": str(ROOT)})
    linha = next((l for l in r.stdout.decode("utf-8", "replace").splitlines() if l.startswith("JSON:")), None)
    assert linha, r.stderr.decode("utf-8", "replace")[-800:]
    return json.loads(linha[5:])


def _paginas(r: Retriever, pergunta: str) -> list[tuple[str, int, str]]:
    return [(p.documento, p.pagina, p.motivo) for p in r.buscar(pergunta).paginas]


@pytest.mark.parametrize(
    ("pergunta", "pagina"),
    [
        ("Até quando posso trancar a matrícula em 2026/1?", 4),  # 10/04 e 21/05
        ("Qual o prazo para trancar a matrícula em 2026/2 sem a assinatura dos professores?", 7),  # 18/09
        ("Quando começa o período letivo 2026/1?", 3),  # 02/03
        ("Quando e onde será a colação de grau de 2026/1 no campus Rio Paranaíba?", 6),  # 31/07 CRP
    ],
)
def test_calendario_do_semestre_entra_no_contexto(ret: Retriever, pergunta: str, pagina: int) -> None:
    assert ("res-cepe-24-2025-calendario", pagina) in {(d, p) for d, p, _ in _paginas(ret, pergunta)}


def test_calendario_nao_entra_em_pergunta_sem_data(ret: Retriever) -> None:
    assert all(m != "calendario" for _, _, m in _paginas(ret, "Qual a nota mínima para ser aprovado?"))


def test_calendario_nao_entra_em_pergunta_de_pos(ret: Retriever) -> None:
    assert all(m != "calendario" for _, _, m in _paginas(ret, "Até quando o mestrando pode trancar em 2026/1?"))


@pytest.mark.parametrize("pergunta", CONFLITO)
def test_conflito_traz_ppc_e_aponta_divergencia(real: dict, pergunta: str) -> None:
    res = real[pergunta]
    ppc = {(pg, motivo) for doc, pg, motivo, _ in res["paginas"] if doc == "ppc-si-2022"}
    assert (17, "ppc_conflito") in ppc and (18, "ppc_conflito") in ppc  # trecho que atravessa as duas páginas
    assert any(d["unidade"] == "h-a" and d["norma"]["valores"] == ["210"] and "60" in d["ppc"]["valores"]
               for d in res["divergencias"])
    # a norma específica continua antes do PPC no contexto
    tipos = [h for *_, h in res["paginas"]]
    assert tipos == sorted(tipos, key=lambda h: h == "ppc")


def test_modos_de_medicao_nao_usam_paginas_obrigatorias(ret: Retriever) -> None:
    res = ret.buscar("Até quando posso trancar a matrícula em 2026/1?", "rrf")
    assert all(p.motivo == "ranking" for p in res.paginas) and len(res.paginas) <= 3
