"""Modelos de dados compartilhados: manifesto de documentos e chunks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Escopo = Literal["graduacao", "curso-si", "pos-graduacao"]


class DocMeta(BaseModel):
    """Um documento do manifesto (data/pdfs/manifest.json)."""

    id: str
    arquivo: str
    titulo: str
    tipo: str
    escopo: Escopo
    vigencia: str
    paginas: int
    fonte_oficial: str | None = None
    arquivo_original: str | None = None
    observacao: str | None = None
    paginas_excluidas: list[int] = Field(default_factory=list)
    motivo_exclusao: str | None = None
    # Textos que precisam existir após a extração (validação do remapeamento de glifos)
    validar_contem: list[str] = Field(default_factory=list)


class Chunk(BaseModel):
    id: str
    documento: str
    titulo: str
    vigencia: str
    escopo: Escopo
    pagina: int
    pagina_fim: int
    artigo: str | None = None
    secao: str | None = None
    origem: Literal["texto", "ocr"] = "texto"
    texto: str


def carregar_manifesto(pdf_dir: Path) -> list[DocMeta]:
    caminho = pdf_dir / "manifest.json"
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    docs = [DocMeta.model_validate(d) for d in dados["documentos"]]
    ids = [d.id for d in docs]
    if len(ids) != len(set(ids)):
        raise ValueError("manifest.json tem ids de documento duplicados")
    return docs
