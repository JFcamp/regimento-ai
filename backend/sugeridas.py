"""Perguntas sugeridas e cache de respostas (modo demo offline).

O cache é um JSON versionado (data/cache/sugeridas.json). Se a pergunta digitada for uma das sugeridas e houver
entrada no cache, a API responde sem chamar o LLM. Para (re)gerar: python -m backend.build_cache (precisa de chaves).
"""
from __future__ import annotations

import json
from pathlib import Path

from backend.textutil import normalizar

SUGERIDAS = [
    "Quantas vezes posso trancar a matrícula na graduação?",
    "Qual a carga horária de atividades complementares exigida no curso?",
    "Quantas horas de monitoria contam como atividade complementar?",
    "Qual o percentual mínimo de extensão na carga horária do curso?",
    "Por quantos períodos posso fazer mobilidade acadêmica?",
    "Quando e onde será a colação de grau de 2026/1?",
    "Qual a frequência mínima para ser aprovado em uma disciplina?",
    "Quando começam as aulas do primeiro semestre de 2026?",
]


def _chave(pergunta: str) -> str:
    return " ".join(normalizar(pergunta).split()).rstrip("?!. ")


def carregar_cache(caminho: Path) -> dict[str, dict]:
    if not caminho.exists():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8")).get("entradas", {})
    except (json.JSONDecodeError, OSError):
        return {}


def buscar_no_cache(cache: dict[str, dict], pergunta: str) -> dict | None:
    return cache.get(_chave(pergunta))


def gravar_cache(caminho: Path, entradas: dict[str, dict], meta: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps({"versao": 1, "meta": meta, "entradas": entradas}, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def chave_da_pergunta(pergunta: str) -> str:
    return _chave(pergunta)
