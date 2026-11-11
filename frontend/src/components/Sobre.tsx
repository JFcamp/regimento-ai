import { useEffect, useState, type ReactNode } from "react";

import { getJSON, type Documento } from "../api";

function Bloco({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-stone-200 bg-white p-6">
      <h2 className="text-lg font-semibold text-stone-900">{titulo}</h2>
      <div className="mt-3 space-y-3 text-sm leading-relaxed text-stone-600">{children}</div>
    </section>
  );
}

const ESCOPO: Record<string, string> = { graduacao: "graduação (UFV)", "curso-si": "curso de SI", "pos-graduacao": "pós-graduação" };

export function Sobre() {
  const [docs, setDocs] = useState<Documento[] | null>(null);
  useEffect(() => {
    getJSON<Documento[]>("/documentos").then(setDocs).catch(() => setDocs([]));
  }, []);

  return (
    <div className="mx-auto w-full max-w-4xl space-y-5 px-4 py-8 sm:px-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight text-stone-900">Sobre o Regimento.AI</h1>
        <p className="mt-2 text-stone-600">
          Assistente acadêmico para estudantes de <strong>Sistemas de Informação da UFV, campus Rio Paranaíba</strong>.
        </p>
      </header>

      <div role="note" className="rounded-2xl border border-vinho-200 bg-vinho-50 p-5 text-sm leading-relaxed text-vinho-900">
        <strong>Importante:</strong> as respostas não substituem a coordenação do curso nem o Registro Escolar. Em caso de
        dúvida ou divergência, vale sempre o documento oficial. Confira a página citada antes de tomar decisões.
      </div>

      <Bloco titulo="Como funciona">
        <p>
          O assistente usa <strong>RAG</strong> (geração aumentada por recuperação). Os PDFs oficiais foram divididos em trechos
          por artigo e indexados. Para cada pergunta, uma busca híbrida (palavras-chave BM25 + significado com o modelo
          multilingual-e5) encontra os trechos mais relevantes, e as páginas inteiras vão para o modelo de linguagem.
        </p>
        <p>
          O modelo só pode responder com base nesses trechos e precisa citar cada afirmação com [n]. O sistema confere se o trecho
          citado existe no PDF; se nenhuma citação se confirma, a resposta é trocada por “Não encontrei isso nos documentos
          oficiais”. Quando o PPC e uma norma específica divergem, a norma específica vem primeiro e a divergência é avisada.
        </p>
        <p>
          Para medir o ganho, o mesmo modelo responde a 50 perguntas com e sem RAG, e outro modelo, de outro fornecedor, avalia as
          respostas contra um gabarito com página de origem.
        </p>
      </Bloco>

      <Bloco titulo="Documentos indexados">
        {docs === null ? (
          <p>Carregando...</p>
        ) : docs.length === 0 ? (
          <p>Não foi possível carregar a lista (o backend está rodando?).</p>
        ) : (
          <ul className="divide-y divide-stone-100">
            {docs.map((d) => (
              <li key={d.id} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2.5">
                <span className="font-medium text-stone-800">{d.titulo}</span>
                <span className="text-xs text-stone-500">
                  vigência {d.vigencia} · {d.paginas} págs. · {ESCOPO[d.escopo] ?? d.escopo}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Bloco>

      <Bloco titulo="Limitações">
        <ul className="list-disc space-y-1.5 pl-5">
          <li>Cobre só os 10 documentos listados acima. Normas mais novas ou de outros cursos não estão incluídas.</li>
          <li>Os documentos têm vigências diferentes (2021 a 2026) e às vezes se contradizem, como na carga de atividades complementares (210 h-a × 60 h-a).</li>
          <li>As 9 páginas escaneadas do PPC (ata do CEPE) ficaram fora do índice, e o PDF de extensão tem erros de OCR.</li>
          <li>O banco de avaliação tem 50 perguntas e ainda não foi revisado por um humano: os números são preliminares.</li>
          <li>Modelos de linguagem podem errar mesmo com as fontes. Confira sempre a página citada.</li>
        </ul>
      </Bloco>

      <Bloco titulo="Privacidade">
        <p>
          <strong>Não digite dados pessoais.</strong> CPF e número de matrícula são ocultados automaticamente antes de a pergunta
          ser enviada ao modelo, mas outros dados não são.
        </p>
        <p>
          As perguntas são processadas pelo Google Gemini no plano gratuito, e o Google pode usar os dados enviados nesse plano para
          melhorar seus produtos. O Regimento.AI não guarda histórico de conversas.
        </p>
      </Bloco>

      <p className="text-center text-xs text-stone-400">
        Projeto acadêmico · código em github.com/JFcamp/regimento-ai
      </p>
    </div>
  );
}
