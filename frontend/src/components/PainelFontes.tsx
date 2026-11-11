import { useEffect, useRef } from "react";

import type { Citacao } from "../api";

function Fonte({ c, ativa, onSelecionar }: { c: Citacao; ativa: boolean; onSelecionar: () => void }) {
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (ativa) ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [ativa]);
  return (
    <li ref={ref}>
      <button
        type="button"
        onClick={onSelecionar}
        aria-pressed={ativa}
        className={`w-full rounded-xl border p-3 text-left transition ${
          ativa ? "border-vinho-300 bg-vinho-50 shadow-sm" : "border-stone-200 bg-white hover:border-stone-300"
        }`}
      >
        <div className="flex items-start gap-2.5">
          <span
            className={`mt-0.5 inline-flex h-6 min-w-6 items-center justify-center rounded-md text-xs font-bold ${
              ativa ? "bg-vinho-700 text-white" : "bg-vinho-100 text-vinho-800"
            }`}
          >
            {c.id}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold leading-snug text-stone-900">{c.titulo}</p>
            <p className="mt-0.5 text-xs text-stone-500">
              Página {c.pagina}
              {c.artigo ? ` · ${c.artigo}` : ""} · vigência {c.vigencia}
            </p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {c.hierarquia === "ppc" && (
                <span className="rounded bg-stone-100 px-1.5 py-0.5 text-[10px] font-medium uppercase text-stone-600">PPC</span>
              )}
              {c.escopo === "pos-graduacao" && (
                <span className="rounded bg-sky-50 px-1.5 py-0.5 text-[10px] font-medium uppercase text-sky-700">pós-graduação</span>
              )}
              {!c.valida && (
                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium uppercase text-amber-800">
                  trecho não confirmado
                </span>
              )}
            </div>
          </div>
        </div>
        <blockquote className="mt-3 border-l-2 border-vinho-200 pl-3 text-sm leading-relaxed text-stone-700">
          <mark>{c.trecho_literal}</mark>
        </blockquote>
      </button>
    </li>
  );
}

export function PainelFontes({ citacoes, ativa, onSelecionar, onFechar }: {
  citacoes: Citacao[];
  ativa: number | null;
  onSelecionar: (id: number) => void;
  onFechar?: () => void;
}) {
  return (
    <aside aria-label="Fontes da resposta" className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-stone-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-stone-900">
          Fontes <span className="font-normal text-stone-400">({citacoes.length})</span>
        </h2>
        {onFechar && (
          <button type="button" onClick={onFechar} className="rounded-md px-2 py-1 text-sm text-stone-500 hover:bg-stone-100 lg:hidden">
            Fechar
          </button>
        )}
      </div>
      {citacoes.length === 0 ? (
        <p className="p-4 text-sm leading-relaxed text-stone-500">
          As fontes da resposta aparecem aqui: documento, página, artigo e o trecho literal conferido no PDF.
        </p>
      ) : (
        <ul className="flex-1 space-y-3 overflow-y-auto p-4">
          {citacoes.map((c) => (
            <Fonte key={c.id} c={c} ativa={ativa === c.id} onSelecionar={() => onSelecionar(c.id)} />
          ))}
        </ul>
      )}
      <p className="border-t border-stone-200 px-4 py-3 text-[11px] leading-snug text-stone-400">
        O trecho destacado foi conferido no texto do PDF. Em caso de dúvida, consulte o documento oficial.
      </p>
    </aside>
  );
}
