"""Experimento: python -m eval.run

50 perguntas × (sem RAG, com RAG) no mesmo LLM (Gemini, temperatura 0), juiz Groq. O progresso é gravado em
eval/resultados/progresso.json depois de CADA chamada: se cair (rede, limite diário do plano gratuito), rode de
novo e ele continua de onde parou. Ao final gera o CSV, o resumo.json e os gráficos.

Opções:
  --so-recuperacao   mede só o recall@3 da página do gabarito (sem LLM, sem chave)
  --limite N         usa só as N primeiras perguntas (teste rápido)
  --reiniciar        apaga o progresso anterior
  --sem-graficos     não gera as figuras
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

from backend.config import ROOT, Settings, get_settings
from backend.generator import ErroProvedor, Provedor, obter_provedor
from backend.prompts import PROMPT_VERSAO, montar_contexto
from backend.rag import coletar, eh_recusa, responder
from backend.retriever import Retriever
from eval.juiz import VERSAO_JUIZ, julgar
from eval.metricas import fontes_aceitas, por_categoria, recall_at_3, resumir_modo

RESULTADOS = ROOT / "eval" / "resultados"
PERGUNTAS = ROOT / "eval" / "perguntas.json"
MODOS = ("sem_rag", "rag")
PARADA = {"limite_de_uso", "chave_ausente", "modelo_ausente", "provedor_nao_suportado"}


class Progresso:
    def __init__(self, caminho: Path, meta: dict, reiniciar: bool = False) -> None:
        self.caminho = caminho
        dados = {} if reiniciar or not caminho.exists() else json.loads(caminho.read_text(encoding="utf-8"))
        anterior = dados.get("meta", {})
        chaves = ("provedor", "modelo", "juiz", "modelo_juiz", "prompt", "prompt_juiz", "hash_perguntas")
        if dados and any(anterior.get(k) != meta.get(k) for k in chaves if k in anterior):
            diff = {k: (anterior.get(k), meta.get(k)) for k in chaves if anterior.get(k) != meta.get(k)}
            raise SystemExit(f"Progresso existente foi gerado com outra configuração {diff}. Use --reiniciar.")
        self.meta = {**anterior, **meta}
        self.respostas: dict[str, dict] = dados.get("respostas", {})
        self.recuperacao: dict[str, list] = dados.get("recuperacao", {})

    def gravar(self) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.caminho.with_suffix(".tmp")
        tmp.write_text(json.dumps({"meta": self.meta, "recuperacao": self.recuperacao, "respostas": self.respostas},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.caminho)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _avaliar_citacoes(p: dict, citacoes: list[dict]) -> list[dict]:
    aceitas = fontes_aceitas(p)
    return [{"id": c["id"], "documento": c["documento"], "pagina": c["pagina"], "valida": bool(c["valida"]),
             "pagina_correta": (c["documento"], c["pagina"]) in aceitas} for c in citacoes]


async def executar(
    perguntas: list[dict],
    retriever: Retriever,
    provedor: Provedor | None,
    juiz: Provedor | None,
    s: Settings,
    progresso: Progresso,
    so_recuperacao: bool = False,
    log=print,
) -> str:
    """Roda o que falta e devolve o status: 'completo', 'interrompido' ou 'so_recuperacao'."""
    # 1) recuperação (determinística, sem LLM)
    for p in perguntas:
        if p["id"] not in progresso.recuperacao:
            res = retriever.buscar(p["pergunta"], "hibrido")
            progresso.recuperacao[p["id"]] = [[pg.documento, pg.pagina] for pg in res.paginas]
    progresso.gravar()
    if so_recuperacao:
        return "so_recuperacao"
    assert provedor is not None and juiz is not None

    # 2) respostas (sem RAG e com RAG, mesmo LLM, temperatura 0)
    total = len(perguntas) * len(MODOS)
    feitas = sum(f"{p['id']}|{m}" in progresso.respostas for p in perguntas for m in MODOS)
    for p in perguntas:
        for modo in MODOS:
            chave = f"{p['id']}|{modo}"
            r_prev = progresso.respostas.get(chave)
            if r_prev and not r_prev.get("erro"):
                continue
            r = await coletar(responder(p["pergunta"], modo, retriever, provedor, s))
            if r.erro and r.erro.get("codigo") in PARADA:
                log(f"\nParando: {r.erro['mensagem']} Progresso salvo; rode de novo para continuar.")
                return "interrompido"
            trechos = None
            if modo == "rag":
                res = retriever.buscar(p["pergunta"], "hibrido")
                trechos = montar_contexto(res.paginas)
            progresso.respostas[chave] = {
                "id": p["id"], "modo": modo, "resposta": r.texto, "citacoes": r.citacoes, "fim": r.fim,
                "avisos": r.avisos, "erro": r.erro, "trechos": trechos, "em": datetime.now().isoformat(timespec="seconds"),
            }
            progresso.gravar()
            feitas += 1
            log(f"  [{feitas}/{total}] {chave}: {'ERRO ' + r.erro['codigo'] if r.erro else 'ok'}")

    # 3) julgamento
    por_id = {p["id"]: p for p in perguntas}
    pendentes = [k for k, v in progresso.respostas.items() if k.split("|")[0] in por_id and not v.get("erro")
                 and (v.get("julgamento") or {}).get("veredito") is None]
    for i, chave in enumerate(pendentes, start=1):
        v = progresso.respostas[chave]
        j = await julgar(juiz, por_id[v["id"]], v["resposta"], v.get("trechos"))
        if j.get("codigo") in PARADA:
            log(f"\nParando no juiz: {j['motivo']}. Progresso salvo; rode de novo para continuar.")
            return "interrompido"
        v["julgamento"] = j
        progresso.gravar()
        log(f"  juiz [{i}/{len(pendentes)}] {chave}: {j['veredito']} alucinou={j['alucinou']}")
    return "completo"


def consolidar(perguntas: list[dict], progresso: Progresso) -> list[dict]:
    linhas = []
    for p in perguntas:
        rec = progresso.recuperacao.get(p["id"], [])
        for modo in MODOS:
            v = progresso.respostas.get(f"{p['id']}|{modo}")
            j = (v or {}).get("julgamento") or {}
            citacoes = (v or {}).get("citacoes") or []
            linhas.append({
                "id": p["id"], "categoria": p["categoria"], "modo": modo, "respondivel": p["respondivel"],
                "conflito": p["conflito"], "documento_gabarito": p["documento"], "pagina_gabarito": p["pagina"],
                "pergunta": p["pergunta"], "resposta": (v or {}).get("resposta"),
                "recusa": eh_recusa((v or {}).get("resposta") or "") if v else None,
                "veredito": j.get("veredito"), "alucinou": j.get("alucinou"), "motivo_juiz": j.get("motivo"),
                "fonte_julgamento": j.get("fonte"), "erro": ((v or {}).get("erro") or {}).get("codigo"),
                "citacoes_avaliadas": _avaliar_citacoes(p, citacoes) if modo == "rag" else [],
                "paginas_recuperadas": rec if modo == "rag" else [],
                "recall3": recall_at_3(p, rec) if modo == "rag" else None,
            })
    return linhas


def gravar_saidas(perguntas: list[dict], progresso: Progresso, status: str, pasta: Path = RESULTADOS) -> dict:
    linhas = consolidar(perguntas, progresso)
    julgadas = [l for l in linhas if l["veredito"] is not None]
    rec = [l["recall3"] for l in linhas if l["modo"] == "rag" and l["recall3"] is not None]
    from eval.metricas import bootstrap_ic

    resumo = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "config": progresso.meta,
        "n_perguntas": len(perguntas),
        "revisadas": sum(bool(p["revisado"]) for p in perguntas),
        "aviso": "Gabarito ainda não revisado por humano (revisado=false): números preliminares.",
        "recuperacao": {"recall_at_3": round(sum(rec) / len(rec), 4) if rec else None, "acertos": sum(rec),
                        "n": len(rec), "ic95": bootstrap_ic([1.0 if x else 0.0 for x in rec])},
        "modos": {m: resumir_modo([l for l in julgadas if l["modo"] == m]) for m in MODOS
                  if any(l["modo"] == m for l in julgadas)},
        "por_categoria": por_categoria(julgadas),
        "pendentes": {m: sum(1 for l in linhas if l["modo"] == m and l["veredito"] is None) for m in MODOS},
    }
    pasta.mkdir(parents=True, exist_ok=True)
    csv_path = pasta / f"{date.today().isoformat()}.csv"
    campos = ["id", "categoria", "modo", "respondivel", "conflito", "documento_gabarito", "pagina_gabarito", "pergunta",
              "resposta", "recusa", "veredito", "alucinou", "motivo_juiz", "fonte_julgamento", "erro",
              "n_citacoes", "n_citacoes_validas", "citacao_pagina_correta", "paginas_recuperadas", "recall3"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for l in linhas:
            cit = l["citacoes_avaliadas"]
            w.writerow({**l, "n_citacoes": len(cit), "n_citacoes_validas": sum(c["valida"] for c in cit),
                        "citacao_pagina_correta": any(c["valida"] and c["pagina_correta"] for c in cit) if cit else "",
                        "paginas_recuperadas": "; ".join(f"{d} p{pg}" for d, pg in l["paginas_recuperadas"])})
    resumo["csv"] = csv_path.name
    (pasta / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    return resumo


def main(argv: list[str] | None = None) -> int:
    for f in (sys.stdout, sys.stderr):
        f.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser(description="Experimento sem RAG × com RAG")
    ap.add_argument("--so-recuperacao", action="store_true")
    ap.add_argument("--limite", type=int)
    ap.add_argument("--reiniciar", action="store_true")
    ap.add_argument("--sem-graficos", action="store_true")
    a = ap.parse_args(argv)

    s = get_settings()
    perguntas = json.loads(PERGUNTAS.read_text(encoding="utf-8"))["perguntas"][: a.limite]
    meta = {"provedor": s.llm_provider, "modelo": s.gemini_model if s.llm_provider == "gemini" else s.groq_model,
            "juiz": s.judge_provider, "modelo_juiz": s.groq_model if s.judge_provider == "groq" else s.gemini_model,
            "temperatura": s.temperature, "prompt": PROMPT_VERSAO, "prompt_juiz": VERSAO_JUIZ,
            "hash_perguntas": _hash(PERGUNTAS), "embeddings": s.embedding_model, "max_paginas": s.max_paginas}
    progresso = Progresso(RESULTADOS / "progresso.json", meta, a.reiniciar)

    provedor = juiz = None
    so_rec = a.so_recuperacao
    if not so_rec:
        try:
            provedor, juiz = obter_provedor(s.llm_provider, s), obter_provedor(s.judge_provider, s)
        except ErroProvedor as e:
            print(f"Sem LLM: {e.mensagem}\nRodando só a recuperação (recall@3). Configure o .env e rode de novo.")
            so_rec = True

    print("Carregando índice e modelo de embeddings ...", flush=True)
    retriever = Retriever.carregar(s)
    status = asyncio.run(executar(perguntas, retriever, provedor, juiz, s, progresso, so_rec))
    resumo = gravar_saidas(perguntas, progresso, status)
    r = resumo["recuperacao"]
    print(f"\nStatus: {status} | recall@3 = {r['acertos']}/{r['n']} ({r['recall_at_3']}) | pendentes: {resumo['pendentes']}")
    for m, d in resumo["modos"].items():
        print(f"  {m}: acurácia {d['acuracia']} | alucinação {d['taxa_alucinacao']} IC95 {d['taxa_alucinacao_ic95']}"
              f" | recusa correta {d['recusa_correta']['acertos']}/{d['recusa_correta']['total']}")
    if not a.sem_graficos:
        from eval.graficos import gerar

        for caminho in gerar(resumo):
            print("  figura:", caminho.relative_to(ROOT))
    return 0 if status in ("completo", "so_recuperacao") else 3


if __name__ == "__main__":
    raise SystemExit(main())
