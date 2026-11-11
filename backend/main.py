"""API FastAPI do Regimento.AI.  Rodar: uvicorn backend.main:app --port 8000"""
from __future__ import annotations

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.config import ROOT, Settings, get_settings
from backend.generator import ErroProvedor, Provedor, obter_provedor
from backend.rag import responder
from backend.retriever import Retriever
from backend.schemas import carregar_manifesto
from backend.sugeridas import SUGERIDAS, buscar_no_cache, carregar_cache


class ChatIn(BaseModel):
    pergunta: str = Field(min_length=3, max_length=1000)
    usar_cache: bool = True


def _sse(evento: str, dados: object) -> str:
    return f"event: {evento}\ndata: {json.dumps(dados, ensure_ascii=False)}\n\n"


def create_app(
    settings: Settings | None = None,
    retriever: Retriever | None = None,
    provedor: Provedor | None = None,
    carregar_retriever_ao_iniciar: bool = True,
) -> FastAPI:
    s = settings or get_settings()
    estado: dict[str, object] = {"retriever": retriever, "erro_indice": None}

    def _carregar() -> None:
        try:
            estado["retriever"] = Retriever.carregar(s)
        except Exception as e:  # noqa: BLE001 - qualquer falha vira estado visível no /health
            estado["erro_indice"] = f"{type(e).__name__}: {e}"

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Só quando o servidor sobe (nunca no import do módulo): o modelo de embeddings leva ~1 min para carregar,
        # então carrega em thread e o /health mostra "carregando_indice" enquanto isso.
        if estado["retriever"] is None and carregar_retriever_ao_iniciar:
            threading.Thread(target=_carregar, daemon=True).start()
        yield

    app = FastAPI(title="Regimento.AI", version="0.3.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
    )
    def _provedor() -> Provedor:
        return provedor or obter_provedor(s.llm_provider, s)

    @app.get("/health")
    def health() -> dict:
        r: Retriever | None = estado["retriever"]  # type: ignore[assignment]
        return {
            "status": "ok" if r else ("erro" if estado["erro_indice"] else "carregando_indice"),
            "indice": {"chunks": len(r.chunks), "documentos": len(r.docs)} if r else None,
            "erro_indice": estado["erro_indice"],
            "provedor": s.llm_provider,
            "modelo": s.gemini_model if s.llm_provider == "gemini" else s.groq_model,
            "chaves": {
                "gemini": s.gemini_api_key is not None,
                "groq": s.groq_api_key is not None,
            },
            "cache_sugeridas": len(carregar_cache(s.cache_sugeridas)),
        }

    @app.get("/documentos")
    def documentos() -> list[dict]:
        return [d.model_dump() for d in carregar_manifesto(s.pdf_dir)]

    @app.get("/sugestoes")
    def sugestoes() -> list[dict]:
        cache = carregar_cache(s.cache_sugeridas)
        return [{"pergunta": p, "em_cache": buscar_no_cache(cache, p) is not None} for p in SUGERIDAS]

    @app.get("/resultados")
    def resultados() -> JSONResponse:
        caminho = ROOT / "eval" / "resultados" / "resumo.json"
        if not caminho.exists():
            return JSONResponse({"disponivel": False})
        return JSONResponse({"disponivel": True, **json.loads(caminho.read_text(encoding="utf-8"))})

    figuras = ROOT / "docs" / "figuras"
    figuras.mkdir(parents=True, exist_ok=True)
    app.mount("/figuras", StaticFiles(directory=figuras), name="figuras")

    @app.post("/chat")
    async def chat(corpo: ChatIn, modo: Literal["rag", "sem_rag"] = "rag") -> StreamingResponse:
        async def gerar() -> AsyncIterator[str]:
            # 1) cache das perguntas sugeridas (demo offline)
            if modo == "rag" and corpo.usar_cache:
                hit = buscar_no_cache(carregar_cache(s.cache_sugeridas), corpo.pergunta)
                if hit:
                    palavras = hit["resposta"].split(" ")
                    for i, w in enumerate(palavras):
                        yield _sse("token", {"texto": w + (" " if i < len(palavras) - 1 else "")})
                        await asyncio.sleep(0.012)
                    yield _sse("citacoes", hit["citacoes"])
                    yield _sse("fim", {**hit["fim"], "cache": True})
                    return
            # 2) pipeline real
            r: Retriever | None = estado["retriever"]  # type: ignore[assignment]
            if modo == "rag" and r is None:
                msg = estado["erro_indice"] or "O índice ainda está carregando. Tente novamente em instantes."
                yield _sse("erro", {"codigo": "indice_indisponivel", "mensagem": msg})
                return
            try:
                prov = _provedor()
            except ErroProvedor as e:
                yield _sse("erro", {"codigo": e.codigo, "mensagem": e.mensagem})
                return
            async for ev in responder(corpo.pergunta, modo, r, prov, s):
                yield _sse(ev["event"], ev["data"])

        return StreamingResponse(gerar(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


app = create_app()
