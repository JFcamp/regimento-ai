"""Máscara de dados pessoais na pergunta, aplicada ANTES de qualquer envio ao LLM."""
from __future__ import annotations

import re

_CPF_RE = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
# "matrícula 8745", "matricula nº 123456", "mat.: ES12345"
_MATRICULA_RE = re.compile(
    r"(?P<pre>\b(?:matr[ií]cula|matricula|mat)\b\.?\s*(?:n[º°o.]{0,2}\s*)?[:\-]?\s*)(?P<num>[A-Za-z]{0,3}\d{4,10})\b",
    re.IGNORECASE,
)


def mascarar(texto: str) -> tuple[str, list[str]]:
    """Retorna (texto mascarado, tipos encontrados). Não guarda nem registra o valor original."""
    tipos: list[str] = []
    if _CPF_RE.search(texto):
        tipos.append("cpf")
        texto = _CPF_RE.sub("[CPF]", texto)
    if _MATRICULA_RE.search(texto):
        tipos.append("matricula")
        texto = _MATRICULA_RE.sub(lambda m: m.group("pre") + "[MATRÍCULA]", texto)
    return texto, tipos
