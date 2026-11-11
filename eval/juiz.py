"""Juiz LLM (Groq por padrão) com prompt versionado em eval/judge_prompt_v1.md."""
from __future__ import annotations

import json
import re
from pathlib import Path

from backend.generator import ErroProvedor, Provedor
from backend.rag import eh_recusa

VERSAO_JUIZ = "v1"
PROMPT_JUIZ = (Path(__file__).resolve().parent / f"judge_prompt_{VERSAO_JUIZ}.md").read_text(encoding="utf-8")
VEREDITOS = {"correta", "parcial", "incorreta"}
_JSON_RE = re.compile(r"\{.*\}", re.S)


def parse_julgamento(texto: str) -> dict | None:
    m = _JSON_RE.search(texto or "")
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if d.get("veredito") not in VEREDITOS or not isinstance(d.get("alucinou"), bool):
        return None
    return {"veredito": d["veredito"], "alucinou": d["alucinou"], "motivo": str(d.get("motivo", ""))[:300]}


def julgamento_por_regra(pergunta: dict, resposta: str) -> dict | None:
    """Casos que não precisam de LLM. Retorna None quando o juiz deve ser chamado."""
    recusou = eh_recusa(resposta)
    if not pergunta["respondivel"]:
        return {"veredito": "correta" if recusou else "incorreta", "alucinou": not recusou,
                "motivo": "recusa correta" if recusou else "respondeu pergunta sem base nos documentos", "fonte": "regra"}
    if recusou:
        return {"veredito": "incorreta", "alucinou": False, "motivo": "recusou pergunta respondível", "fonte": "regra"}
    return None


def montar_user(pergunta: dict, resposta: str, trechos: str | None) -> str:
    partes = [f"PERGUNTA: {pergunta['pergunta']}", f"GABARITO: {pergunta['resposta_gabarito']}"]
    if trechos:
        partes.append(f"TRECHOS FORNECIDOS AO ASSISTENTE:\n{trechos}")
    partes.append(f"RESPOSTA DO ASSISTENTE: {resposta}")
    return "\n\n".join(partes)


async def julgar(juiz: Provedor, pergunta: dict, resposta: str, trechos: str | None = None) -> dict:
    regra = julgamento_por_regra(pergunta, resposta)
    if regra:
        return regra
    user = montar_user(pergunta, resposta, trechos)
    ultimo = ""
    for _ in range(2):  # uma nova tentativa se o JSON vier malformado
        try:
            ultimo = await juiz.completar(PROMPT_JUIZ, user, temperature=0.0, max_tokens=200)
        except ErroProvedor as e:
            return {"veredito": None, "alucinou": None, "motivo": f"erro do juiz: {e.codigo}", "fonte": "erro", "codigo": e.codigo}
        d = parse_julgamento(ultimo)
        if d:
            return {**d, "fonte": "llm"}
    return {"veredito": None, "alucinou": None, "motivo": "juiz devolveu JSON inválido", "fonte": "erro", "bruto": ultimo[:300]}
