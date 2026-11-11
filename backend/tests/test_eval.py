"""Testes do experimento com LLM, juiz e retriever falsos (sem rede)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from backend.config import Settings
from backend.prompts import RECUSA
from backend.retriever import PaginaContexto, Resultado
from eval.graficos import gerar
from eval.juiz import julgamento_por_regra, parse_julgamento
from eval.metricas import bootstrap_ic, recall_at_3, resumir_modo
from eval.run import Progresso, consolidar, executar, gravar_saidas

PAGINA = "Art 4º - O cumprimento da carga horária de 210 horas/aula como atividades acadêmicas complementares."
PERGUNTAS = [
    {"id": "Q1", "categoria": "horas-complementares-extensao", "documento": "ac", "pagina": 2, "respondivel": True,
     "conflito": False, "revisado": False, "pergunta": "Carga de atividades complementares?",
     "resposta_gabarito": "210 horas/aula"},
    {"id": "Q2", "categoria": "outros", "documento": None, "pagina": None, "respondivel": False, "conflito": False,
     "revisado": False, "pergunta": "Cardápio do RU?", "resposta_gabarito": RECUSA},
]


class LLM:
    modelo = "falso"

    def __init__(self) -> None:
        self.chamadas = 0

    async def stream(self, system, user, temperature=None, max_tokens=None):
        self.chamadas += 1
        if "Cardápio" in user:
            yield (RECUSA + ".") if "TRECHOS" in user else "O cardápio tem arroz e feijão."
        else:
            yield "São 210 horas/aula de atividades complementares [1]." if "TRECHOS" in user else "São 120 horas."


class Juiz:
    modelo = "juiz"

    def __init__(self) -> None:
        self.chamadas = 0

    async def completar(self, system, user, temperature=None, max_tokens=None):
        self.chamadas += 1
        ok = "210 horas/aula de" in user.split("RESPOSTA DO ASSISTENTE:")[1]
        return json.dumps({"veredito": "correta" if ok else "incorreta", "alucinou": not ok, "motivo": "teste"})


class Ret:
    def buscar(self, pergunta, modo="hibrido"):
        pg = PaginaContexto(1, "ac", "AC", "2021", "curso-si", "norma", 2, "Art. 4", PAGINA, 0.03)
        return Resultado(pergunta, modo, [], [pg], False, 0.8, 1.0, [])

    def artigo_em(self, *a):
        return "Art. 4"


def _rodar(tmp: Path, llm=None, juiz=None):
    s = Settings(index_dir=tmp, cache_sugeridas=tmp / "c.json")
    prog = Progresso(tmp / "progresso.json", {"provedor": "falso", "hash_perguntas": "x"})
    status = asyncio.run(executar(PERGUNTAS, Ret(), llm or LLM(), juiz or Juiz(), s, prog, log=lambda *_: None))
    return status, prog


def test_experimento_completo_metricas_e_figuras(tmp_path: Path) -> None:
    status, prog = _rodar(tmp_path)
    assert status == "completo"
    resumo = gravar_saidas(PERGUNTAS, prog, status, tmp_path / "res")
    rag, sem = resumo["modos"]["rag"], resumo["modos"]["sem_rag"]
    assert rag["acuracia"] == 1.0 and rag["taxa_alucinacao"] == 0.0 and rag["recusa_correta"] == {"acertos": 1, "total": 1}
    assert sem["acuracia"] == 0.0 and sem["taxa_alucinacao"] == 1.0 and sem["recusa_correta"]["acertos"] == 0
    assert rag["citacoes"]["precisao_pagina"] == 1.0 and rag["citacoes"]["literal_valido"] == 1.0
    assert resumo["recuperacao"]["recall_at_3"] == 1.0 and resumo["revisadas"] == 0
    assert (tmp_path / "res" / "resumo.json").exists() and (tmp_path / "res" / resumo["csv"]).exists()
    figs = gerar(resumo, tmp_path / "fig")
    assert {f.name for f in figs} == {
        "alucinacao_sem_vs_com_rag.png", "alucinacao_sem_vs_com_rag.svg", "acuracia_por_categoria.png",
        "acuracia_por_categoria.svg", "citacao_e_recall.png", "citacao_e_recall.svg"}


def test_retoma_sem_refazer_chamadas(tmp_path: Path) -> None:
    llm, juiz = LLM(), Juiz()
    _rodar(tmp_path, llm, juiz)
    assert llm.chamadas == 4  # 2 perguntas × 2 modos
    assert juiz.chamadas == 2  # Q2 (sem resposta nos documentos) é julgada por regra nos dois modos
    llm2, juiz2 = LLM(), Juiz()
    status, _ = _rodar(tmp_path, llm2, juiz2)
    assert status == "completo" and llm2.chamadas == 0 and juiz2.chamadas == 0


def test_para_e_salva_progresso_no_limite_de_uso(tmp_path: Path) -> None:
    class LLM429(LLM):
        async def stream(self, *a, **k):
            from backend.generator import ErroProvedor

            self.chamadas += 1
            if self.chamadas > 1:
                raise ErroProvedor("limite_de_uso", "cota diária esgotada", 429)
            yield "São 120 horas."
            return

    status, prog = _rodar(tmp_path, LLM429())
    assert status == "interrompido" and len(prog.respostas) == 1
    assert json.loads((tmp_path / "progresso.json").read_text(encoding="utf-8"))["respostas"]


def test_so_recuperacao_dispensa_llm(tmp_path: Path) -> None:
    s = Settings(index_dir=tmp_path)
    prog = Progresso(tmp_path / "p.json", {"hash_perguntas": "x"})
    assert asyncio.run(executar(PERGUNTAS, Ret(), None, None, s, prog, so_recuperacao=True)) == "so_recuperacao"
    resumo = gravar_saidas(PERGUNTAS, prog, "so_recuperacao", tmp_path / "r")
    assert resumo["modos"] == {} and resumo["recuperacao"]["acertos"] == 1
    assert [f.name for f in gerar(resumo, tmp_path / "f")] == ["citacao_e_recall.png", "citacao_e_recall.svg"]


def test_julgamento_por_regra_e_parse() -> None:
    sem = PERGUNTAS[1]
    assert julgamento_por_regra(sem, RECUSA + ".")["veredito"] == "correta"
    assert julgamento_por_regra(sem, "Arroz e feijão.")["alucinou"] is True
    assert julgamento_por_regra(PERGUNTAS[0], RECUSA)["veredito"] == "incorreta"
    assert julgamento_por_regra(PERGUNTAS[0], "São 210 horas") is None
    assert parse_julgamento('ok: {"veredito": "parcial", "alucinou": false, "motivo": "x"} fim')["veredito"] == "parcial"
    assert parse_julgamento('{"veredito": "talvez", "alucinou": false}') is None


def test_recall_e_bootstrap() -> None:
    p = {**PERGUNTAS[0], "fontes_aceitas": [{"documento": "ppc", "pagina": 18}]}
    assert recall_at_3(p, [["x", 1], ["ppc", 18]]) is True
    assert recall_at_3(p, [["x", 1], ["y", 2], ["z", 3], ["ac", 2]]) is False  # só as 3 primeiras contam
    assert recall_at_3(PERGUNTAS[1], []) is None
    assert bootstrap_ic([1.0] * 10) == [1.0, 1.0]
    lo, hi = bootstrap_ic([0.0, 1.0] * 20)
    assert lo < 0.5 < hi and bootstrap_ic([0.0, 1.0] * 20) == [lo, hi]  # semente fixa
    assert resumir_modo([])["acuracia"] is None
