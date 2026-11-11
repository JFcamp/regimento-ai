"""Configurações lidas do .env (nunca do código). Caminhos relativos são resolvidos a partir da raiz do projeto."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,  # "MIN_SCORE=" vazio no .env.example vira o valor padrão
    )

    # --- Caminhos ---
    pdf_dir: Path = ROOT / "data" / "pdfs"
    index_dir: Path = ROOT / "data" / "index"
    cache_sugeridas: Path = ROOT / "data" / "cache" / "sugeridas.json"

    # --- Embeddings e chunking (Etapa 2) ---
    embedding_model: str = "intfloat/multilingual-e5-base"
    chunk_size: int = 800
    chunk_overlap: int = 150
    article_max_chars: int = 1000  # artigo que cabe neste tamanho não é dividido
    min_chunk_chars: int = 20

    # --- Recuperação (Etapa 3) ---
    top_k: int = 6  # chunks que entram na fusão final
    candidatos: int = 40  # profundidade de cada ranking (denso e BM25) antes do RRF
    rrf_k: int = 60  # constante do Reciprocal Rank Fusion
    max_paginas: int = 3  # páginas inteiras enviadas ao LLM (como no notebook de origem)
    peso_ppc: float = 0.85  # PPC perde para norma específica sobre o mesmo tema
    min_score: float | None = None  # None = valor calibrado em backend/retriever.py (ver spec, seção 11)
    fuzzy_threshold: int = 90  # literal precisa existir na página (exato ou fuzzy >= isto)
    suporte_threshold: int = 45  # frase da resposta precisa ser sustentada pelo literal

    # --- Provedores de LLM ---
    llm_provider: str = "gemini"  # modelo avaliado e do chat: gemini | groq | openai | anthropic | local
    judge_provider: str = "groq"  # juiz da avaliação (Etapa 5)
    temperature: float = 0.0
    max_output_tokens: int = 700

    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-flash-latest"  # confirme com: python -m backend.listar_modelos
    gemini_rpm: int = 10  # pedidos por minuto (plano gratuito); 0 desliga o espaçamento

    groq_api_key: SecretStr | None = None
    groq_model: str = "llama-3.3-70b-versatile"  # confirme com: python -m backend.listar_modelos
    groq_rpm: int = 25

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"

    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = ""

    local_model: str = "Qwen/Qwen2.5-3B-Instruct"  # opcional; pensado para Colab com GPU T4

    # --- Retry em erro 429/5xx ---
    max_retries: int = 5
    backoff_base: float = 2.0  # segundos; dobra a cada tentativa, com jitter, respeitando Retry-After

    @field_validator("pdf_dir", "index_dir", "cache_sugeridas")
    @classmethod
    def _resolver_relativo(cls, v: Path) -> Path:
        return v if v.is_absolute() else (ROOT / v).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
