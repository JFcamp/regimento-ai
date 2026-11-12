"""Testes rápidos do backend (sem rede, sem modelo de embeddings, sem chaves)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.citations import verificar
from backend.config import Settings
from backend.generator import ErroProvedor, Gemini, Groq, obter_provedor
from backend.main import create_app
from backend.pii import mascarar
from backend.prompts import RECUSA
from backend.rag import coletar, responder
from backend.retriever import PaginaContexto, Resultado, detectar_divergencias, quantidades
from backend.sugeridas import chave_da_pergunta, gravar_cache
from backend.textutil import menciona_pos_graduacao, normalizar, radical, tokenizar


# ---------------------------------------------------------------- texto e escopo
def test_normalizacao_e_radical() -> None:
    assert normalizar("Matrícula Pós-Graduação") == "matricula pos-graduacao"
    assert radical("trancamento") == radical("trancar") == radical("trancada") == "tranca"
    assert radical("horas") == radical("hora")
    assert "qual" not in tokenizar("Qual o prazo?") and "prazo" in tokenizar("Qual o prazo?")


@pytest.mark.parametrize("pergunta", [
    "Quantas vezes o mestrando pode trancar?", "Prazo do doutorado", "Regras da pós-graduação", "o que é stricto sensu",
    "Como é a qualificação do doutorado?", "Posso fazer mestrado na UFV?",
])
def test_pergunta_de_pos_e_roteada(pergunta: str) -> None:
    assert menciona_pos_graduacao(pergunta)


@pytest.mark.parametrize("pergunta", [
    "Quantas vezes posso trancar a matrícula na graduação?", "Qual a carga horária de atividades complementares?",
    "Quando é a colação de grau?",
])
def test_pergunta_de_graduacao_nao_e_roteada_para_pos(pergunta: str) -> None:
    assert not menciona_pos_graduacao(pergunta)


# ---------------------------------------------------------------- máscara de dados pessoais
def test_mascara_cpf_e_matricula() -> None:
    t, tipos = mascarar("Meu CPF é 123.456.789-09 e minha matrícula 8745, posso trancar?")
    assert "123" not in t and "8745" not in t and tipos == ["cpf", "matricula"]
    assert "[CPF]" in t and "[MATRÍCULA]" in t
    assert mascarar("cpf 12345678909")[0] == "cpf [CPF]"
    assert mascarar("matrícula nº ES12345")[0].endswith("[MATRÍCULA]")


def test_mascara_nao_apaga_numeros_normais() -> None:
    texto = "Em 2026/1 são 210 horas/aula no Art. 80, 3 períodos e 75% de frequência"
    assert mascarar(texto) == (texto, [])


# ---------------------------------------------------------------- citações
def _pag(i: int, texto: str, **kw) -> PaginaContexto:
    base = dict(id=i, documento="doc", titulo="Doc", vigencia="2021", escopo="curso-si", hierarquia="norma",
                pagina=2, artigo="Art. 4", texto=texto, score=0.03)
    return PaginaContexto(**{**base, **kw})


PAGINA_AC = ("Art 4º - O cumprimento da carga horária de 210 horas/aula como atividades acadêmicas complementares "
             "é requisito indispensável à integralização curricular.\nArt 5º - Monitoria vale 30 h-a por semestre letivo.")


def test_citacao_valida_traz_literal_da_pagina() -> None:
    (c,) = verificar("São exigidas 210 horas/aula de atividades complementares [1].", [_pag(1, PAGINA_AC)])
    assert c.valida and "210 horas/aula" in c.trecho_literal and c.trecho_literal in PAGINA_AC
    assert c.pagina == 2 and c.id == 1


def test_citacao_sem_suporte_e_invalida() -> None:
    (c,) = verificar("O restaurante universitário abre às 11h30 aos domingos [1].", [_pag(1, PAGINA_AC)])
    assert not c.valida


def test_citacao_em_tabela_sem_pontuacao() -> None:
    # Regressão: no catálogo (tabela), a "frase" passa de 420 caracteres e a citação era rejeitada
    linhas = " ".join(f"SIN {100 + i} Disciplina número {i} 4(4-0) 60 SIN {90 + i} I e II" for i in range(40))
    tabela = linhas + " SIN 211 Algoritmos e Estruturas de Dados 6(4-2) 90 SIN 110 I e II " + linhas
    (c,) = verificar("O pré-requisito de Algoritmos e Estruturas de Dados (SIN 211) é SIN 110 [1].", [_pag(1, tabela)])
    assert c.valida and "SIN 211 Algoritmos e Estruturas de Dados" in c.trecho_literal
    assert c.trecho_literal in tabela and len(c.trecho_literal) < 400


def test_marcador_inexistente_e_descartado() -> None:
    assert verificar("São 210 horas/aula [7].", [_pag(1, PAGINA_AC)]) == []


def test_varias_fontes_em_uma_frase() -> None:
    cs = verificar("Há 210 horas/aula de atividades complementares [1][2].", [_pag(1, PAGINA_AC), _pag(2, PAGINA_AC, pagina=3)])
    assert [c.id for c in cs] == [1, 2] and all(c.valida for c in cs)


# ---------------------------------------------------------------- divergência PPC x norma
def test_divergencia_entre_ppc_e_norma() -> None:
    norma = _pag(1, "É requisito cumprir 210 horas/aula de atividades.")
    ppc = _pag(2, "O aluno deve cumprir 60 horas/aula de atividades.", hierarquia="ppc")
    (d,) = detectar_divergencias([norma, ppc])
    assert d["unidade"] == "h-a" and d["norma"]["valores"] == ["210"] and d["ppc"]["valores"] == ["60"]
    assert detectar_divergencias([norma, _pag(2, "São 210 horas/aula.", hierarquia="ppc")]) == []
    assert quantidades("3 (três) períodos e 75% de frequência")["%"] == {"75"}


# ---------------------------------------------------------------- provedores: retry e erros
def _cliente(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _settings(**kw) -> Settings:
    return Settings(gemini_api_key="CHAVE-SECRETA-123", groq_api_key="CHAVE-GROQ", max_retries=3, backoff_base=0.01, **kw)


def _sse_gemini(*textos: str) -> bytes:
    return "".join(
        "data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": t}]}}]}) + "\n\n" for t in textos
    ).encode()


def test_gemini_faz_retry_em_429_e_respeita_retry_after() -> None:
    chamadas, esperas = [], []

    def handler(req: httpx.Request) -> httpx.Response:
        chamadas.append(req)
        if len(chamadas) < 3:
            return httpx.Response(429, headers={"retry-after": "2"}, text="quota")
        return httpx.Response(200, content=_sse_gemini("Olá", " mundo"))

    async def sleep(s: float) -> None:
        esperas.append(s)

    s = _settings()
    prov = Gemini("modelo-x", "CHAVE-SECRETA-123", s, 0, _cliente(handler), sleep)
    assert asyncio.run(prov.completar("sys", "oi")) == "Olá mundo"
    assert len(chamadas) == 3 and esperas == [2.0, 2.0]
    assert "CHAVE-SECRETA-123" not in str(chamadas[0].url) and chamadas[0].headers["x-goog-api-key"] == "CHAVE-SECRETA-123"
    assert json.loads(chamadas[0].content)["generationConfig"]["temperature"] == 0.0


def test_429_persistente_vira_erro_limite_de_uso_sem_vazar_a_chave() -> None:
    async def sleep(_: float) -> None: ...

    prov = Gemini("m", "CHAVE-SECRETA-123", _settings(), 0, _cliente(lambda r: httpx.Response(429, text="x")), sleep)
    with pytest.raises(ErroProvedor) as e:
        asyncio.run(prov.completar("s", "u"))
    assert e.value.codigo == "limite_de_uso" and "CHAVE-SECRETA" not in e.value.mensagem


def test_cota_diaria_para_na_hora_e_informa_o_limite() -> None:
    corpo = {"error": {"code": 429, "message": "quota", "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quotaValue": "500"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "40s"}]}}
    n = []

    def handler(r: httpx.Request) -> httpx.Response:
        n.append(1)
        return httpx.Response(429, json=corpo)

    prov = Gemini("m", "CHAVE-SECRETA-123", _settings(), 0, _cliente(handler))
    with pytest.raises(ErroProvedor) as e:
        asyncio.run(prov.completar("s", "u"))
    assert len(n) == 1 and e.value.codigo == "limite_de_uso"
    assert "PerDay" in e.value.mensagem and "500" in e.value.mensagem and "CHAVE" not in e.value.mensagem


def test_cota_por_minuto_espera_o_retry_delay() -> None:
    corpo = {"error": {"details": [{"violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
                                   {"retryDelay": "7s"}]}}
    chamadas, esperas = [], []

    def handler(r: httpx.Request) -> httpx.Response:
        chamadas.append(1)
        return httpx.Response(429, json=corpo) if len(chamadas) == 1 else httpx.Response(200, content=_sse_gemini("ok"))

    async def sleep(s: float) -> None:
        esperas.append(s)

    prov = Gemini("m", "K", _settings(), 0, _cliente(handler), sleep)
    assert asyncio.run(prov.completar("s", "u")) == "ok" and esperas == [8.0]


def test_gpt_oss_recebe_raciocinio_baixo() -> None:
    corpos = []

    def handler(r: httpx.Request) -> httpx.Response:
        corpos.append(json.loads(r.content))
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    asyncio.run(Groq("openai/gpt-oss-120b", "K", _settings(), 0, _cliente(handler)).completar("s", "u", max_tokens=100))
    assert corpos[0]["reasoning_effort"] == "low" and corpos[0]["max_tokens"] == 1024


def test_erro_4xx_nao_faz_retry() -> None:
    n = []

    def handler(r: httpx.Request) -> httpx.Response:
        n.append(1)
        return httpx.Response(400, text="modelo inexistente")

    prov = Groq("m", "CHAVE-GROQ", _settings(), 0, _cliente(handler))
    with pytest.raises(ErroProvedor) as e:
        asyncio.run(prov.completar("s", "u"))
    assert len(n) == 1 and e.value.codigo == "erro_do_provedor"


def test_groq_le_stream_estilo_openai() -> None:
    corpo = "".join(
        "data: " + json.dumps({"choices": [{"delta": {"content": t}}]}) + "\n\n" for t in ("A", "B")
    ) + "data: [DONE]\n\n"
    prov = Groq("m", "CHAVE-GROQ", _settings(), 0, _cliente(lambda r: httpx.Response(200, content=corpo.encode())))
    assert asyncio.run(prov.completar("s", "u")) == "AB"


def test_chave_ausente_e_provedor_desconhecido() -> None:
    with pytest.raises(ErroProvedor) as e:
        obter_provedor("gemini", Settings(_env_file=None, gemini_api_key=None))
    assert e.value.codigo == "chave_ausente"
    with pytest.raises(ErroProvedor):
        obter_provedor("openai", _settings())


# ---------------------------------------------------------------- fluxo RAG e API
class LLMFalso:
    modelo = "falso"

    def __init__(self, resposta: str) -> None:
        self.resposta, self.recebido = resposta, []

    async def stream(self, system: str, user: str, temperature=None, max_tokens=None):
        self.recebido.append((system, user))
        for i in range(0, len(self.resposta), 7):
            yield self.resposta[i : i + 7]


class RetrieverFalso:
    def __init__(self, paginas: list[PaginaContexto]) -> None:
        self.paginas, self.chunks, self.docs = paginas, [1, 2, 3], {"a": 1}

    def buscar(self, pergunta: str, modo: str = "hibrido") -> Resultado:
        return Resultado(pergunta, modo, [], self.paginas, False, 0.8, 1.0, [])

    def artigo_em(self, documento: str, pagina: int, literal: str) -> str | None:
        return "Art. 4"


def _app(tmp_path: Path, resposta: str, paginas: list[PaginaContexto] | None = None):
    s = Settings(index_dir=tmp_path, cache_sugeridas=tmp_path / "cache.json", pdf_dir=Path("data/pdfs"))
    llm = LLMFalso(resposta)
    ret = RetrieverFalso(paginas if paginas is not None else [_pag(1, PAGINA_AC)])
    return TestClient(create_app(s, ret, llm)), llm, s  # type: ignore[arg-type]


def _eventos(texto: str) -> list[tuple[str, object]]:
    saida = []
    for bloco in texto.strip().split("\n\n"):
        linhas = bloco.split("\n")
        saida.append((linhas[0].removeprefix("event: "), json.loads(linhas[1].removeprefix("data: "))))
    return saida


def test_chat_rag_devolve_resposta_citacao_verificada_e_fim(tmp_path: Path) -> None:
    client, llm, _ = _app(tmp_path, "São exigidas 210 horas/aula de atividades complementares [1].")
    ev = _eventos(client.post("/chat", json={"pergunta": "Qual a carga horária?"}).text)
    nomes = [n for n, _ in ev]
    assert nomes[-1] == "fim" and "citacoes" in nomes and "token" in nomes
    cit = dict(ev)["citacoes"][0]
    assert cit["valida"] and cit["artigo"] == "Art. 4" and cit["pagina"] == 2 and "210 horas/aula" in cit["trecho_literal"]
    fim = dict(ev)["fim"]
    assert fim["recusa"] is False and fim["n_trechos"] == 1
    assert "[1] Doc" in llm.recebido[0][1] and "PERGUNTA:" in llm.recebido[0][1]


def test_resposta_sem_citacao_valida_vira_recusa(tmp_path: Path) -> None:
    client, _, _ = _app(tmp_path, "O prazo é de dez anos, sem exceções.")
    ev = _eventos(client.post("/chat", json={"pergunta": "Qual o prazo?"}).text)
    d = dict(ev)
    assert ("substituir", {"texto": RECUSA + "."}) in ev
    assert d["fim"]["recusa"] is True and d["fim"]["motivo"] == "sem_citacao_valida" and d["citacoes"] == []


def test_recusa_do_modelo_e_preservada(tmp_path: Path) -> None:
    client, _, _ = _app(tmp_path, RECUSA + ".")
    d = dict(_eventos(client.post("/chat", json={"pergunta": "Cardápio do RU?"}).text))
    assert d["fim"]["recusa"] is True and d["citacoes"] == []


def test_sem_contexto_recusa_sem_chamar_o_llm(tmp_path: Path) -> None:
    client, llm, _ = _app(tmp_path, "nunca", paginas=[])
    d = dict(_eventos(client.post("/chat", json={"pergunta": "Pergunta sem base"}).text))
    assert d["fim"]["recusa"] and d["fim"]["motivo"] == "sem_contexto" and llm.recebido == []


def test_cpf_e_matricula_nao_chegam_ao_llm(tmp_path: Path) -> None:
    client, llm, _ = _app(tmp_path, "São 210 horas/aula [1].")
    ev = _eventos(client.post("/chat", json={"pergunta": "CPF 123.456.789-09 matrícula 8745: quantas horas?"}).text)
    assert ev[0][0] == "aviso" and ev[0][1]["mascarados"] == ["cpf", "matricula"]
    tudo = " ".join(system + user for system, user in llm.recebido)
    assert "123.456" not in tudo and "8745" not in tudo and "[CPF]" in tudo


def test_modo_sem_rag_nao_usa_contexto_nem_citacoes(tmp_path: Path) -> None:
    client, llm, _ = _app(tmp_path, "Resposta livre do modelo.")
    d = dict(_eventos(client.post("/chat?modo=sem_rag", json={"pergunta": "Qual o prazo?"}).text))
    assert d["fim"]["modo"] == "sem_rag" and d["citacoes"] == []
    assert "TRECHOS" not in llm.recebido[0][1]


def test_aviso_quando_pos_graduacao_entra_no_contexto(tmp_path: Path) -> None:
    pos = _pag(1, "O trancamento de matrícula poderá ser concedido por 2 (dois) períodos letivos.", escopo="pos-graduacao")
    client, _, _ = _app(tmp_path, "O trancamento pode ser concedido por 2 (dois) períodos letivos [1].", [pos])
    ev = _eventos(client.post("/chat", json={"pergunta": "Quantas vezes o mestrando tranca?"}).text)
    assert any(n == "aviso" and d["tipo"] == "pos_graduacao" for n, d in ev)
    assert "Pós-Graduação" in "".join(d["texto"] for n, d in ev if n == "token")


def test_cache_das_sugeridas_funciona_sem_llm_nem_indice(tmp_path: Path) -> None:
    s = Settings(index_dir=tmp_path, cache_sugeridas=tmp_path / "c.json")
    pergunta = "Quantas vezes posso trancar a matrícula na graduação?"
    gravar_cache(s.cache_sugeridas, {chave_da_pergunta(pergunta): {
        "pergunta": pergunta, "resposta": "Até cinco vezes [1].", "citacoes": [{"id": 1}], "fim": {"recusa": False, "n_trechos": 1}}}, {})
    app = create_app(s, None, None, carregar_retriever_ao_iniciar=False)  # type: ignore[arg-type]
    client = TestClient(app)
    ev = _eventos(client.post("/chat", json={"pergunta": pergunta.upper()}).text)
    assert "".join(d["texto"] for n, d in ev if n == "token") == "Até cinco vezes [1]."
    assert dict(ev)["fim"]["cache"] is True
    assert client.get("/sugestoes").json()[0]["em_cache"] is True


def test_chat_sem_chave_devolve_erro_estruturado(tmp_path: Path) -> None:
    s = Settings(_env_file=None, index_dir=tmp_path, cache_sugeridas=tmp_path / "c.json", gemini_api_key=None)
    client = TestClient(create_app(s, RetrieverFalso([_pag(1, PAGINA_AC)]), None))  # type: ignore[arg-type]
    d = dict(_eventos(client.post("/chat", json={"pergunta": "Qualquer pergunta"}).text))
    assert d["erro"]["codigo"] == "chave_ausente"


def test_documentos_health_e_cors(tmp_path: Path) -> None:
    client, _, _ = _app(tmp_path, "x")
    docs = client.get("/documentos").json()
    assert len(docs) == 10 and {"id", "titulo", "vigencia", "escopo", "paginas"} <= set(docs[0])
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["indice"]["chunks"] == 3 and "gemini" in h["chaves"]
    r = client.options("/chat", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert client.post("/chat", json={"pergunta": "a"}).status_code == 422


def test_coletar_junta_os_eventos() -> None:
    async def gen():
        yield {"event": "token", "data": {"texto": "a"}}
        yield {"event": "token", "data": {"texto": "b"}}
        yield {"event": "fim", "data": {"recusa": False}}

    r = asyncio.run(coletar(gen()))
    assert r.texto == "ab" and r.fim == {"recusa": False}
    assert isinstance(SimpleNamespace(), object)
