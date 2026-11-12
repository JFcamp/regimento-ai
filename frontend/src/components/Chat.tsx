import { useEffect, useRef, useState, type FormEvent } from "react";

import { getJSON, perguntar, respostaVazia, type Resposta, type Sugestao } from "../api";
import { PainelFontes } from "./PainelFontes";
import { RespostaCard } from "./RespostaCard";

interface Troca {
  id: number;
  pergunta: string;
  rag: Resposta;
  semRag: Resposta | null;
}

const SUGESTOES_PADRAO = [
  "Quantas vezes posso trancar a matrícula na graduação?",
  "Qual a carga horária de atividades complementares exigida no curso?",
  "Quando e onde será a colação de grau de 2026/1?",
  "Qual a frequência mínima para ser aprovado em uma disciplina?",
];

export function Chat() {
  const [trocas, setTrocas] = useState<Troca[]>([]);
  const [texto, setTexto] = useState("");
  const [comparar, setComparar] = useState(false);
  const [sugestoes, setSugestoes] = useState<string[]>(SUGESTOES_PADRAO);
  const [selecao, setSelecao] = useState<{ troca: number; fonte: number | null } | null>(null);
  const [painelMovel, setPainelMovel] = useState(false);
  const fimRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    getJSON<Sugestao[]>("/sugestoes")
      .then((s) => setSugestoes(s.map((x) => x.pergunta)))
      .catch(() => undefined);
  }, []);

  // ?q=... na URL envia a pergunta ao abrir (links compartilháveis e demonstração)
  const enviouDaUrl = useRef(false);
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("q");
    if (q && !enviouDaUrl.current) {
      enviouDaUrl.current = true;
      void enviar(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    fimRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [trocas.length]);

  const ocupado = trocas.some((t) => t.rag.carregando || t.semRag?.carregando);
  const trocaFontes = selecao ? trocas.find((t) => t.id === selecao.troca) : trocas.at(-1);

  async function enviar(pergunta: string) {
    const p = pergunta.trim();
    if (p.length < 3 || ocupado) return;
    setTexto("");
    const id = Date.now();
    abortRef.current = new AbortController();
    const sinal = abortRef.current.signal;
    setTrocas((ts) => [...ts, { id, pergunta: p, rag: respostaVazia(), semRag: comparar ? respostaVazia() : null }]);
    setSelecao({ troca: id, fonte: null });
    const atualizar = (campo: "rag" | "semRag") => (r: Resposta) =>
      setTrocas((ts) => ts.map((t) => (t.id === id ? { ...t, [campo]: r } : t)));
    const [rag] = await Promise.all([
      perguntar(p, "rag", atualizar("rag"), sinal),
      comparar ? perguntar(p, "sem_rag", atualizar("semRag"), sinal) : Promise.resolve(null),
    ]);
    // destaca a primeira fonte válida no painel
    const primeira = rag.citacoes.find((c) => c.valida);
    if (primeira) setSelecao({ troca: id, fonte: primeira.id });
  }

  function citar(troca: number, fonte: number) {
    setSelecao({ troca, fonte });
    setPainelMovel(true);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void enviar(texto);
  }

  return (
    <div className="mx-auto grid w-full max-w-7xl flex-1 grid-cols-[minmax(0,1fr)] gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(0,1fr)_380px]">
      <section aria-label="Conversa" className="flex min-h-[60vh] min-w-0 flex-col">
        <div className="flex-1 space-y-8" aria-live="polite">
          {trocas.length === 0 && (
            <div className="rounded-3xl border border-stone-200 bg-white p-6 shadow-sm sm:p-8">
              <p className="text-xs font-semibold uppercase tracking-widest text-vinho-700">Sistemas de Informação · UFV Rio Paranaíba</p>
              <h1 className="mt-2 text-2xl font-bold tracking-tight text-stone-900 sm:text-3xl">
                Tire dúvidas sobre as normas do curso, com a fonte na mão.
              </h1>
              <p className="mt-3 max-w-2xl leading-relaxed text-stone-600">
                As respostas vêm só do Regime Didático, do calendário, do PPC e dos regulamentos oficiais. Cada afirmação
                aponta a página e o artigo de onde saiu. Se não estiver nos documentos, o assistente avisa.
              </p>
              <h2 className="mt-6 text-sm font-semibold text-stone-700">Experimente perguntar</h2>
              <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                {sugestoes.map((s) => (
                  <li key={s}>
                    <button
                      type="button"
                      onClick={() => void enviar(s)}
                      className="h-full w-full rounded-xl border border-stone-200 bg-stone-50 px-4 py-3 text-left text-sm text-stone-700 transition hover:border-vinho-200 hover:bg-vinho-50 hover:text-vinho-900"
                    >
                      {s}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {trocas.map((t) => (
            <div key={t.id} className="space-y-3">
              <div className="flex justify-end">
                <p className="max-w-[85%] rounded-2xl rounded-br-md bg-vinho-700 px-4 py-2.5 text-white shadow-sm">{t.pergunta}</p>
              </div>
              <div className={t.semRag ? "grid gap-3 md:grid-cols-2" : ""}>
                <RespostaCard
                  r={t.rag}
                  titulo={t.semRag ? "Regimento.AI (com RAG)" : undefined}
                  onCitar={(f) => citar(t.id, f)}
                  ativa={selecao?.troca === t.id ? selecao.fonte : null}
                />
                {t.semRag && <RespostaCard r={t.semRag} titulo="Mesmo LLM, sem RAG" variante="sem_rag" />}
              </div>
            </div>
          ))}
          <div ref={fimRef} />
        </div>

        <form onSubmit={onSubmit} className="sticky bottom-0 mt-6 bg-gradient-to-t from-stone-50 via-stone-50 pt-4 pb-2">
          <div className="rounded-2xl border border-stone-300 bg-white p-2 shadow-sm focus-within:border-vinho-300 focus-within:ring-2 focus-within:ring-vinho-100">
            <label htmlFor="pergunta" className="sr-only">Sua pergunta</label>
            <textarea
              id="pergunta"
              rows={2}
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void enviar(texto);
                }
              }}
              maxLength={1000}
              placeholder="Ex.: Até quando posso trancar a matrícula em 2026/1?"
              className="w-full resize-none bg-transparent px-2 py-1.5 text-stone-800 placeholder:text-stone-400 focus:outline-none"
            />
            <div className="flex flex-wrap items-center justify-between gap-2 px-1">
              <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-stone-600">
                <input
                  type="checkbox"
                  checked={comparar}
                  onChange={(e) => setComparar(e.target.checked)}
                  className="peer sr-only"
                />
                <span
                  aria-hidden
                  className="relative h-5 w-9 rounded-full bg-stone-300 transition after:absolute after:top-0.5 after:left-0.5 after:h-4 after:w-4 after:rounded-full after:bg-white after:shadow after:transition peer-checked:bg-vinho-600 peer-checked:after:translate-x-4 peer-focus-visible:ring-2 peer-focus-visible:ring-vinho-300"
                />
                Comparar com LLM sem RAG
              </label>
              <button
                type="submit"
                disabled={ocupado || texto.trim().length < 3}
                className="rounded-xl bg-vinho-700 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-vinho-800 disabled:cursor-not-allowed disabled:bg-stone-300"
              >
                {ocupado ? "Respondendo..." : "Perguntar"}
              </button>
            </div>
          </div>
          <p className="mt-2 text-center text-[11px] text-stone-400">
            Não digite dados pessoais. CPF e matrícula são ocultados antes do envio. A resposta não substitui a coordenação do curso.
          </p>
        </form>
      </section>

      {/* Painel de fontes: coluna fixa no desktop, gaveta no celular */}
      <div className="hidden lg:block">
        <div className="sticky top-20 h-[calc(100vh-6.5rem)] overflow-hidden rounded-2xl border border-stone-200 bg-stone-100/60">
          <PainelFontes
            citacoes={trocaFontes?.rag.citacoes ?? []}
            ativa={selecao?.troca === trocaFontes?.id ? (selecao?.fonte ?? null) : null}
            onSelecionar={(f) => trocaFontes && setSelecao({ troca: trocaFontes.id, fonte: f })}
          />
        </div>
      </div>
      {painelMovel && (
        <div className="fixed inset-0 z-30 flex items-end bg-stone-900/40 lg:hidden" onClick={() => setPainelMovel(false)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Fontes"
            className="max-h-[80vh] w-full overflow-hidden rounded-t-2xl bg-stone-50"
            onClick={(e) => e.stopPropagation()}
          >
            <PainelFontes
              citacoes={trocaFontes?.rag.citacoes ?? []}
              ativa={selecao?.fonte ?? null}
              onSelecionar={(f) => trocaFontes && setSelecao({ troca: trocaFontes.id, fonte: f })}
              onFechar={() => setPainelMovel(false)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
