"""Normalização de texto para busca lexical (BM25) e comparações."""
from __future__ import annotations

import re
import unicodedata

# Stopwords do português (sem acentos). Mantém números e termos de domínio ("art", "hora", "credito").
STOPWORDS = frozenset(
    """a o as os um uma uns umas de do da dos das em no na nos nas por para com sem sob sobre ao aos
    e ou mas se que qual quais quem quando onde como quanto quantos quantas
    eu me meu minha meus minhas voce vc seu sua seus suas ele ela eles elas nos lhe lhes
    ser sou e foi sao era eh ter tem tenho tinha ha hao estar esta estou
    pode podem posso podemos deve devem deveria preciso precisa
    ja so tambem mais menos muito muita muitos muitas pouco ainda entre ate apos desde
    isso isto aquilo esse essa esses essas este esta estes estas aquele aquela
    ha vai vou vamos fazer faz fazem feito""".split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalizar(texto: str) -> str:
    """Minúsculas e sem acentos."""
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def radical(token: str) -> str:
    """Radical grosseiro: tira o plural em 's' e trunca em 6 letras ('trancamento' e 'trancar' -> 'tranca')."""
    if token.isdigit():
        return token
    if len(token) > 3 and token.endswith("s"):
        token = token[:-1]
    return token[:6]


def tokenizar(texto: str) -> list[str]:
    return [radical(t) for t in _TOKEN_RE.findall(normalizar(texto)) if t not in STOPWORDS and len(t) > 1]


# Perguntas que mencionam pós-graduação (roteamento de escopo). Aplicado ao texto normalizado.
_POS_RE = re.compile(
    r"\b(mestr\w*|doutor\w*|pos[\s-]?gradua\w*|stricto(?:\s+sensu)?|ppg|dissertac\w*|"
    r"orientand\w*|qualificac\w*|tese|teses)\b"
)


def menciona_pos_graduacao(pergunta: str) -> bool:
    return _POS_RE.search(normalizar(pergunta)) is not None
