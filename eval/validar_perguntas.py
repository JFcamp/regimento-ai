"""Valida eval/perguntas.json: python -m eval.validar_perguntas

Confere estrutura, distribuição e, para cada pergunta respondível, se a `evidencia` aparece no texto extraído
da página indicada (o mesmo texto que vai para o índice). Sai com código 1 se houver erro.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from backend.config import get_settings
from backend.schemas import carregar_manifesto

ROOT = Path(__file__).resolve().parent.parent
ARQUIVO = ROOT / "eval" / "perguntas.json"
CATEGORIAS = {"trancamento", "pre-requisitos", "horas-complementares-extensao", "prazos-calendario", "outros"}
CAMPOS = {"id", "pergunta", "resposta_gabarito", "documento", "pagina", "categoria", "revisado", "respondivel", "conflito"}


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()


def carregar() -> list[dict]:
    return json.loads(ARQUIVO.read_text(encoding="utf-8"))["perguntas"]


def validar(perguntas: list[dict]) -> tuple[list[str], dict]:
    s = get_settings()
    docs = {d.id: d for d in carregar_manifesto(s.pdf_dir)}
    paginas = json.loads((s.index_dir / "paginas.json").read_text(encoding="utf-8"))
    erros: list[str] = []

    ids = [p.get("id") for p in perguntas]
    if len(perguntas) != 50:
        erros.append(f"esperadas 50 perguntas, há {len(perguntas)}")
    if len(set(ids)) != len(ids):
        erros.append("ids duplicados")

    for p in perguntas:
        pid = p.get("id", "?")
        faltam = CAMPOS - set(p)
        if faltam:
            erros.append(f"{pid}: campos ausentes {sorted(faltam)}")
            continue
        if p["categoria"] not in CATEGORIAS:
            erros.append(f"{pid}: categoria inválida {p['categoria']}")
        if p["revisado"] is not False:
            erros.append(f"{pid}: rascunho deve ter revisado=false")
        if not p["respondivel"]:
            if p["documento"] is not None or p["pagina"] is not None:
                erros.append(f"{pid}: pergunta sem resposta deve ter documento e página nulos")
            continue
        doc = docs.get(p["documento"])
        if doc is None:
            erros.append(f"{pid}: documento desconhecido {p['documento']}")
            continue
        if not (1 <= p["pagina"] <= doc.paginas) or p["pagina"] in doc.paginas_excluidas:
            erros.append(f"{pid}: página {p['pagina']} inválida para {doc.id}")
            continue
        texto = _norm(paginas.get(doc.id, {}).get(str(p["pagina"]), ""))
        ev = _norm(p.get("evidencia", ""))
        if not ev:
            erros.append(f"{pid}: sem evidência")
        elif ev not in texto:
            onde = [pg for pg, t in paginas.get(doc.id, {}).items() if ev in _norm(t)]
            erros.append(f"{pid}: evidência não está na p.{p['pagina']} de {doc.id}" + (f" (está em {onde})" if onde else ""))
        for f in p.get("fontes_aceitas", []):
            d2 = docs.get(f["documento"])
            if d2 is None or not (1 <= f["pagina"] <= d2.paginas):
                erros.append(f"{pid}: fonte aceita inválida {f}")
        if p["conflito"] and len({f["documento"] for f in p.get("fontes_aceitas", [])}) < 2:
            erros.append(f"{pid}: conflito exige fontes_aceitas de pelo menos 2 documentos")

    resumo = {
        "total": len(perguntas),
        "por_documento": dict(Counter(p["documento"] or "(sem resposta)" for p in perguntas)),
        "por_categoria": dict(Counter(p["categoria"] for p in perguntas)),
        "sem_resposta": sum(not p["respondivel"] for p in perguntas),
        "conflito": sum(bool(p["conflito"]) for p in perguntas),
        "revisadas": sum(bool(p["revisado"]) for p in perguntas),
    }
    if resumo["sem_resposta"] != 5:
        erros.append(f"esperadas 5 perguntas sem resposta, há {resumo['sem_resposta']}")
    return erros, resumo


def main() -> int:
    for f in (sys.stdout, sys.stderr):
        f.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    erros, resumo = validar(carregar())
    print(json.dumps(resumo, ensure_ascii=False, indent=1))
    for e in erros:
        print("ERRO:", e)
    print("OK" if not erros else f"{len(erros)} erro(s)")
    return 1 if erros else 0


if __name__ == "__main__":
    raise SystemExit(main())
