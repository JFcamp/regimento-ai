"""Figuras do pôster a partir de eval/resultados/resumo.json: python -m eval.graficos

Gera só as figuras cujos dados existem (as que dependem do LLM ficam de fora até o experimento rodar).
Cada figura sai em PNG 300 dpi e SVG, com rótulos em português, em docs/figuras/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from backend.config import ROOT  # noqa: E402
from eval.metricas import CATEGORIAS, ROTULO_CATEGORIA  # noqa: E402

FIGURAS = ROOT / "docs" / "figuras"
BORDO, BORDO_CLARO, CINZA, TEXTO = "#7A1F2B", "#B85C68", "#9CA3AF", "#1F2937"
ROTULO_MODO = {"sem_rag": "LLM sem RAG", "rag": "Regimento.AI (com RAG)"}
COR_MODO = {"sem_rag": CINZA, "rag": BORDO}


def _estilo() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": "#D1D5DB", "axes.labelcolor": TEXTO, "xtick.color": TEXTO, "ytick.color": TEXTO,
        "axes.titleweight": "bold", "axes.titlesize": 13, "svg.fonttype": "none",
    })


def _salvar(fig, nome: str, pasta: Path) -> list[Path]:
    pasta.mkdir(parents=True, exist_ok=True)
    saida = []
    for ext, kw in (("png", {"dpi": 300}), ("svg", {})):
        caminho = pasta / f"{nome}.{ext}"
        fig.savefig(caminho, bbox_inches="tight", facecolor="white", **kw)
        saida.append(caminho)
    plt.close(fig)
    return saida


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def fig_alucinacao(resumo: dict, pasta: Path) -> list[Path]:
    modos = [m for m in ("sem_rag", "rag") if resumo["modos"].get(m, {}).get("taxa_alucinacao") is not None]
    if len(modos) < 2:
        return []
    fig, ax = plt.subplots(figsize=(6, 4.2))
    for i, m in enumerate(modos):
        d = resumo["modos"][m]
        v, (lo, hi) = d["taxa_alucinacao"], d["taxa_alucinacao_ic95"]
        ax.bar(i, v, color=COR_MODO[m], width=0.55, yerr=[[v - lo], [hi - v]], capsize=8, ecolor=TEXTO)
        wl = d.get("taxa_alucinacao_ic95_wilson")
        topo = max(hi, wl[1] if wl else hi)
        ax.text(i, topo + 0.03, f"{_pct(v)} ({d.get('alucinacoes', '?')}/{d['n_julgadas']})", ha="center",
                va="bottom", fontweight="bold", color=TEXTO)
        if wl:
            ax.text(i, topo + 0.10, f"Wilson: {_pct(wl[0])}–{_pct(wl[1])}", ha="center", va="bottom", fontsize=8,
                    color="#6B7280")
    ax.set_xticks(range(len(modos)), [ROTULO_MODO[m] for m in modos])
    ax.set_ylim(0, 1.05)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_ylabel("Respostas com alucinação")
    ax.set_title("Taxa de alucinação (barras de erro: IC 95% bootstrap)")
    ns = [resumo["modos"][m]["n_julgadas"] for m in modos]
    n = f"n = {ns[0]} por modo" if len(set(ns)) == 1 else f"n = {ns[0]} sem RAG · {ns[1]} com RAG"
    pend = sum((resumo.get("pendentes") or {}).values())
    if pend:
        n += f" ({pend} pendentes)"
    modelo = resumo.get("config", {}).get("modelo", "")
    fig.text(0.01, -0.09, f"{n} · mesmo LLM ({modelo}), temperatura 0 · juiz de outro fornecedor\n"
             "Perto de 0%, o bootstrap subestima a incerteza; o IC de Wilson complementa\n"
             "Gabarito ainda não revisado por humano", fontsize=8, color="#6B7280")
    return _salvar(fig, "alucinacao_sem_vs_com_rag", pasta)


def fig_acuracia_categoria(resumo: dict, pasta: Path) -> list[Path]:
    cats = [c for c in CATEGORIAS if c in resumo.get("por_categoria", {})]
    modos = [m for m in ("sem_rag", "rag") if m in resumo.get("modos", {})]
    if not cats or len(modos) < 2:
        return []
    fig, ax = plt.subplots(figsize=(8.5, 4.4))
    largura = 0.38
    for j, m in enumerate(modos):
        xs = [i + (j - 0.5) * largura for i in range(len(cats))]
        vals = [resumo["por_categoria"][c].get(m, {}).get("acuracia", 0.0) for c in cats]
        barras = ax.bar(xs, vals, width=largura, color=COR_MODO[m], label=ROTULO_MODO[m])
        for b, v in zip(barras, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.02, _pct(v), ha="center", fontsize=8, color=TEXTO)
    def _n(c: str) -> str:
        ns = {m: resumo["por_categoria"][c].get(m, {}).get("n", 0) for m in modos}
        return f"n={ns['rag']}" if len(set(ns.values())) == 1 else f"n={ns['sem_rag']}/{ns['rag']}"

    rot = [f"{ROTULO_CATEGORIA[c]}\n({_n(c)})" for c in cats]
    ax.set_xticks(range(len(cats)), rot, fontsize=9)
    ax.set_ylim(0, 1.1)
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_ylabel("Acurácia (correta = 1, parcial = 0,5)")
    ax.set_title("Acurácia por categoria", pad=34)
    # legenda acima do gráfico, para não cobrir os rótulos de 100%
    ax.legend(frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncols=2)
    return _salvar(fig, "acuracia_por_categoria", pasta)


def fig_citacao_recall(resumo: dict, pasta: Path) -> list[Path]:
    rec = resumo.get("recuperacao", {})
    if rec.get("recall_at_3") is None:
        return []
    barras = [("Recall@3\n(página do gabarito\nentre as 3 do ranking)", rec["recall_at_3"], rec.get("ic95"))]
    if rec.get("recall_contexto") is not None:
        barras.append(("Recall no contexto\n(inclui páginas\nobrigatórias)", rec["recall_contexto"], None))
    cit = resumo.get("modos", {}).get("rag", {}).get("citacoes")
    if cit and cit.get("precisao_pagina") is not None:
        barras.append(("Precisão de citação\n(citação válida na\npágina correta)", cit["precisao_pagina"], None))
    if cit and cit.get("literal_valido") is not None:
        barras.append(("Trecho literal\nverificado", cit["literal_valido"], None))
    fig, ax = plt.subplots(figsize=(6.8 if len(barras) > 1 else 4.6, 4.3))
    cores = [BORDO, "#A63B49", BORDO_CLARO, CINZA]
    for i, (rot, v, ic) in enumerate(barras):
        kw = {"yerr": [[v - ic[0]], [ic[1] - v]], "capsize": 8, "ecolor": TEXTO} if ic else {}
        ax.bar(i, v, color=cores[i], width=0.55, **kw)
        ax.text(i, (ic[1] if ic else v) + 0.03, _pct(v), ha="center", fontweight="bold", color=TEXTO)
    ax.set_xticks(range(len(barras)), [b[0] for b in barras], fontsize=9)
    ax.set_xlim(-0.6, len(barras) - 0.4 if len(barras) > 1 else 0.6)
    ax.set_ylim(0, 1.12)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_title("Recuperação e citações (com RAG)")
    nota = f"n = {rec['n']} perguntas respondíveis · busca híbrida BM25 + e5, páginas inteiras"
    if cit and cit.get("total"):
        nota += f" · {cit['total']} citações"
    if len(barras) == 1:
        nota += " · precisão de citação: pendente"
    fig.text(0.01, -0.08, nota, fontsize=8, color="#6B7280")
    return _salvar(fig, "citacao_e_recall", pasta)


def gerar(resumo: dict, pasta: Path = FIGURAS) -> list[Path]:
    _estilo()
    return fig_alucinacao(resumo, pasta) + fig_acuracia_categoria(resumo, pasta) + fig_citacao_recall(resumo, pasta)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    resumo = json.loads((ROOT / "eval" / "resultados" / "resumo.json").read_text(encoding="utf-8"))
    for c in gerar(resumo):
        print(c.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
