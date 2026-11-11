import { useEffect, useState } from "react";

import { getJSON } from "../api";

interface ResumoModo {
  acuracia: number | null;
  acuracia_estrita: number | null;
  taxa_alucinacao: number | null;
  taxa_alucinacao_ic95: [number, number] | null;
  recusa_correta: { acertos: number; total: number };
  citacoes?: { precisao_pagina: number | null; literal_valido: number | null };
}

interface Resumo {
  disponivel: boolean;
  status?: string;
  gerado_em?: string;
  n_perguntas?: number;
  revisadas?: number;
  config?: { modelo?: string; modelo_juiz?: string };
  recuperacao?: { recall_at_3: number | null; acertos: number; n: number; ic95: [number, number] | null };
  modos?: Partial<Record<"rag" | "sem_rag", ResumoModo>>;
  pendentes?: Record<string, number>;
}

const pct = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(1).replace(".", ",")}%`);
const ic = (v: [number, number] | null | undefined) => (v ? `IC 95%: ${pct(v[0])} a ${pct(v[1])}` : "");

const FIGURAS = [
  { arquivo: "alucinacao_sem_vs_com_rag", titulo: "Alucinação: sem RAG × com RAG" },
  { arquivo: "acuracia_por_categoria", titulo: "Acurácia por categoria" },
  { arquivo: "citacao_e_recall", titulo: "Recuperação e citações" },
];

function Cartao({ rotulo, valor, detalhe, destaque }: { rotulo: string; valor: string; detalhe?: string; destaque?: boolean }) {
  return (
    <div className={`rounded-2xl border p-5 ${destaque ? "border-vinho-200 bg-vinho-50" : "border-stone-200 bg-white"}`}>
      <p className="text-xs font-semibold uppercase tracking-wide text-stone-500">{rotulo}</p>
      <p className={`mt-2 text-3xl font-bold tracking-tight ${destaque ? "text-vinho-800" : "text-stone-900"}`}>{valor}</p>
      {detalhe && <p className="mt-1 text-xs text-stone-500">{detalhe}</p>}
    </div>
  );
}

function Figura({ arquivo, titulo }: { arquivo: string; titulo: string }) {
  const [falhou, setFalhou] = useState(false);
  if (falhou) {
    return (
      <figure className="flex min-h-48 flex-col items-center justify-center rounded-2xl border border-dashed border-stone-300 bg-white p-6 text-center">
        <figcaption className="text-sm font-semibold text-stone-700">{titulo}</figcaption>
        <p className="mt-1 text-xs text-stone-500">Pendente: gerada quando o experimento com o LLM rodar.</p>
      </figure>
    );
  }
  return (
    <figure className="overflow-hidden rounded-2xl border border-stone-200 bg-white p-3">
      <img
        src={`/api/figuras/${arquivo}.png`}
        alt={titulo}
        loading="lazy"
        onError={() => setFalhou(true)}
        className="mx-auto h-auto w-full max-w-xl"
      />
      <figcaption className="mt-2 text-center text-xs text-stone-500">{titulo}</figcaption>
    </figure>
  );
}

export function Resultados() {
  const [resumo, setResumo] = useState<Resumo | null>(null);
  const [erro, setErro] = useState(false);

  useEffect(() => {
    getJSON<Resumo>("/resultados").then(setResumo).catch(() => setErro(true));
  }, []);

  if (erro) {
    return <p role="alert" className="mx-auto max-w-5xl px-6 py-10 text-stone-600">Não foi possível carregar os resultados. O backend está rodando?</p>;
  }
  if (!resumo) {
    return <p className="mx-auto max-w-5xl px-6 py-10 text-stone-500">Carregando resultados...</p>;
  }
  if (!resumo.disponivel) {
    return (
      <p className="mx-auto max-w-5xl px-6 py-10 text-stone-600">
        Ainda não há resultados. Rode <code className="rounded bg-stone-100 px-1.5 py-0.5">python -m eval.run</code>.
      </p>
    );
  }

  const rag = resumo.modos?.rag;
  const sem = resumo.modos?.sem_rag;
  const r = resumo.recuperacao;
  const llmPendente = !rag || !sem;

  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 px-4 py-8 sm:px-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight text-stone-900">Resultados do experimento</h1>
        <p className="mt-2 max-w-3xl text-sm leading-relaxed text-stone-600">
          {resumo.n_perguntas} perguntas do banco de avaliação, respondidas pelo mesmo LLM com e sem RAG (temperatura 0) e julgadas
          por um modelo de outro fornecedor. Gerado em {resumo.gerado_em?.replace("T", " às ")}.
        </p>
        {resumo.revisadas === 0 && (
          <p role="note" className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900 ring-1 ring-amber-200">
            Números preliminares: o gabarito ainda não foi revisado por um humano.
          </p>
        )}
        {llmPendente && (
          <p role="note" className="mt-3 rounded-lg bg-stone-100 px-3 py-2 text-sm text-stone-700 ring-1 ring-stone-200">
            Até agora só a recuperação foi medida. Acurácia, alucinação e precisão de citação aparecem aqui quando o experimento
            rodar com as chaves de API configuradas.
          </p>
        )}
      </header>

      <section aria-label="Números principais" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Cartao rotulo="Recall@3 (com RAG)" valor={pct(r?.recall_at_3)} detalhe={`${r?.acertos}/${r?.n} · ${ic(r?.ic95)}`} destaque />
        <Cartao
          rotulo="Alucinação sem → com RAG"
          valor={llmPendente ? "pendente" : `${pct(sem?.taxa_alucinacao)} → ${pct(rag?.taxa_alucinacao)}`}
          detalhe={rag ? ic(rag.taxa_alucinacao_ic95) : undefined}
        />
        <Cartao
          rotulo="Acurácia sem → com RAG"
          valor={llmPendente ? "pendente" : `${pct(sem?.acuracia)} → ${pct(rag?.acuracia)}`}
          detalhe={llmPendente ? undefined : "correta = 1, parcial = 0,5"}
        />
        <Cartao
          rotulo="Precisão de citação"
          valor={pct(rag?.citacoes?.precisao_pagina)}
          detalhe={rag ? `recusa correta: ${rag.recusa_correta.acertos}/${rag.recusa_correta.total}` : "pendente"}
        />
      </section>

      <section aria-label="Gráficos" className="grid gap-4 lg:grid-cols-2">
        {FIGURAS.map((f) => (
          <Figura key={f.arquivo} {...f} />
        ))}
      </section>
    </div>
  );
}
