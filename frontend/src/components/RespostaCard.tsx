import { Fragment, type ReactNode } from "react";

import type { Citacao, Resposta } from "../api";

const RECUSA = "Não encontrei isso nos documentos oficiais";

/** Texto da resposta com os marcadores [n] trocados por botões que abrem a fonte. */
function TextoComCitacoes({ texto, citacoes, onCitar, ativa }: {
  texto: string;
  citacoes: Citacao[];
  onCitar?: (id: number) => void;
  ativa?: number | null;
}) {
  const porId = new Map(citacoes.map((c) => [c.id, c]));
  const partes: ReactNode[] = [];
  const re = /\[(\d+(?:\s*[,;]\s*\d+)*)\]/g;
  let ultimo = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(texto))) {
    partes.push(texto.slice(ultimo, m.index));
    const ids = m[1]!.split(/[,;]/).map((x) => Number(x.trim()));
    partes.push(
      <span key={m.index} className="whitespace-nowrap">
        {ids.map((id) => {
          const c = porId.get(id);
          if (!c || !onCitar) {
            return <sup key={id} className="text-xs text-stone-400">[{id}]</sup>;
          }
          return (
            <button
              key={id}
              type="button"
              onClick={() => onCitar(id)}
              aria-label={`Ver fonte ${id}: ${c.titulo}, página ${c.pagina}`}
              className={`mx-0.5 inline-flex h-5 min-w-5 -translate-y-0.5 items-center justify-center rounded-md px-1 text-[11px] font-semibold transition ${
                ativa === id
                  ? "bg-vinho-700 text-white"
                  : c.valida
                    ? "bg-vinho-100 text-vinho-800 hover:bg-vinho-200"
                    : "bg-amber-100 text-amber-800 hover:bg-amber-200"
              }`}
            >
              {id}
            </button>
          );
        })}
      </span>,
    );
    ultimo = m.index + m[0].length;
  }
  partes.push(texto.slice(ultimo));
  return (
    <>
      {partes.map((p, i) => (
        <Fragment key={i}>{p}</Fragment>
      ))}
    </>
  );
}

export function Selo({ r }: { r: Resposta }) {
  if (r.carregando || !r.fim || r.fim.modo !== "rag") return null;
  if (r.fim.recusa) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-stone-100 px-2.5 py-1 text-xs font-medium text-stone-600">
        <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-stone-400" />
        Não encontrado nos documentos
      </span>
    );
  }
  const n = r.fim.n_trechos;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-800 ring-1 ring-emerald-200">
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
      Fundamentado em {n} {n === 1 ? "trecho" : "trechos"}
    </span>
  );
}

export function RespostaCard({ r, titulo, onCitar, ativa, variante = "rag" }: {
  r: Resposta;
  titulo?: string;
  onCitar?: (id: number) => void;
  ativa?: number | null;
  variante?: "rag" | "sem_rag";
}) {
  const vazio = r.carregando && !r.texto;
  const recusa = !r.carregando && r.texto.trim().startsWith(RECUSA);
  return (
    <article
      className={`rounded-2xl border bg-white p-4 shadow-sm sm:p-5 ${
        variante === "sem_rag" ? "border-dashed border-stone-300" : "border-stone-200"
      }`}
    >
      {titulo && (
        <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h3 className={`text-xs font-semibold uppercase tracking-wide ${variante === "rag" ? "text-vinho-700" : "text-stone-500"}`}>
            {titulo}
          </h3>
          {variante === "sem_rag" && !r.carregando && (
            <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800 ring-1 ring-amber-200">
              sem fontes verificáveis
            </span>
          )}
        </header>
      )}

      {r.avisos
        .filter((a) => a.tipo === "dados_pessoais" || a.tipo === "divergencia")
        .map((a, i) => (
          <p key={i} role="note" className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900 ring-1 ring-amber-200">
            {a.tipo === "divergencia" ? "Atenção: " : ""}
            {a.mensagem}
          </p>
        ))}

      {r.erro ? (
        <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-800 ring-1 ring-red-200">
          {r.erro.mensagem}
        </p>
      ) : vazio ? (
        <div className="space-y-2" aria-label="Buscando nos documentos">
          <div className="h-3 w-11/12 animate-pulse rounded bg-stone-200" />
          <div className="h-3 w-9/12 animate-pulse rounded bg-stone-200" />
          <div className="h-3 w-6/12 animate-pulse rounded bg-stone-200" />
        </div>
      ) : (
        <p
          className={`whitespace-pre-line leading-relaxed ${recusa ? "text-stone-500 italic" : "text-stone-800"} ${
            r.carregando ? "cursor-stream" : ""
          }`}
        >
          <TextoComCitacoes texto={r.texto} citacoes={r.citacoes} onCitar={onCitar} ativa={ativa} />
        </p>
      )}

      {variante === "rag" && !r.carregando && !r.erro && (
        <footer className="mt-4 flex flex-wrap items-center gap-2">
          <Selo r={r} />
          {r.fim?.cache && <span className="text-xs text-stone-400">resposta salva (modo demonstração)</span>}
        </footer>
      )}
    </article>
  );
}
