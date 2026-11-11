"""Configurações lidas do .env (nunca do código). Caminhos relativos são resolvidos a partir da raiz do projeto."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,  # "MIN_SCORE=" vazio no .env.example vira o valor padrão
    )

    # Caminhos
    pdf_dir: Path = ROOT / "data" / "pdfs"
    index_dir: Path = ROOT / "data" / "index"

    # Embeddings e recuperação
    embedding_model: str = "intfloat/multilingual-e5-base"
    top_k: int = 6

    # Chunking (valores do notebook de origem: 800 / 150)
    chunk_size: int = 800
    chunk_overlap: int = 150
    # Artigo que cabe neste tamanho não é dividido
    article_max_chars: int = 1000
    min_chunk_chars: int = 20

    @field_validator("pdf_dir", "index_dir")
    @classmethod
    def _resolver_relativo(cls, v: Path) -> Path:
        return v if v.is_absolute() else (ROOT / v).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
