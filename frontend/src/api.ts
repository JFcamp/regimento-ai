// Cliente da API do Regimento.AI. POST /chat devolve Server-Sent Events, lidos via fetch + ReadableStream
// (EventSource não suporta POST).

export type Modo = "rag" | "sem_rag";

export interface Citacao {
  id: number;
  documento: string;
  titulo: string;
  vigencia: string;
  escopo: string;
  hierarquia: string;
  pagina: number;
  artigo: string | null;
  trecho_literal: string;
  score: number;
  suporte: number;
  valida: boolean;
}

export interface Aviso {
  tipo: "dados_pessoais" | "divergencia" | "pos_graduacao" | string;
  mensagem: string;
}

export interface Fim {
  modo: Modo;
  recusa: boolean;
  n_trechos: number;
  motivo?: string | null;
  cache?: boolean;
  divergencia?: boolean;
}

export interface Resposta {
  texto: string;
  citacoes: Citacao[];
  avisos: Aviso[];
  fim: Fim | null;
  erro: { codigo: string; mensagem: string } | null;
  carregando: boolean;
}

export const respostaVazia = (): Resposta => ({
  texto: "",
  citacoes: [],
  avisos: [],
  fim: null,
  erro: null,
  carregando: true,
});

export async function perguntar(
  pergunta: string,
  modo: Modo,
  onUpdate: (r: Resposta) => void,
  signal?: AbortSignal,
): Promise<Resposta> {
  let r = respostaVazia();
  const emitir = (parcial: Partial<Resposta>) => {
    r = { ...r, ...parcial };
    onUpdate(r);
  };
  try {
    const resp = await fetch(`/api/chat?modo=${modo}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pergunta }),
      signal,
    });
    if (!resp.ok || !resp.body) {
      const detalhe = resp.status === 422 ? "Escreva uma pergunta com pelo menos 3 caracteres." : `HTTP ${resp.status}`;
      emitir({ erro: { codigo: "http", mensagem: detalhe }, carregando: false });
      return r;
    }
    const leitor = resp.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    for (;;) {
      const { value, done } = await leitor.read();
      if (done) break;
      buffer += value;
      let corte: number;
      while ((corte = buffer.indexOf("\n\n")) >= 0) {
        const bloco = buffer.slice(0, corte);
        buffer = buffer.slice(corte + 2);
        const evento = /^event: (.*)$/m.exec(bloco)?.[1];
        const dadosBrutos = /^data: (.*)$/m.exec(bloco)?.[1];
        if (!evento || dadosBrutos === undefined) continue;
        const dados = JSON.parse(dadosBrutos);
        if (evento === "token") emitir({ texto: r.texto + dados.texto });
        else if (evento === "substituir") emitir({ texto: dados.texto });
        else if (evento === "citacoes") emitir({ citacoes: dados });
        else if (evento === "aviso") emitir({ avisos: [...r.avisos, dados] });
        else if (evento === "fim") emitir({ fim: dados });
        else if (evento === "erro") emitir({ erro: dados });
      }
    }
  } catch (e) {
    if ((e as Error).name !== "AbortError") {
      emitir({ erro: { codigo: "rede", mensagem: "Não foi possível falar com o servidor. Ele está rodando?" } });
    }
  }
  emitir({ carregando: false });
  return r;
}

export interface Sugestao {
  pergunta: string;
  em_cache: boolean;
}

export interface Documento {
  id: string;
  titulo: string;
  vigencia: string;
  escopo: string;
  paginas: number;
  tipo: string;
}

export async function getJSON<T>(caminho: string): Promise<T> {
  const r = await fetch(`/api${caminho}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as T;
}
