import { useEffect, useState } from "react";

import { Chat } from "./components/Chat";
import { Resultados } from "./components/Resultados";
import { Sobre } from "./components/Sobre";

type Aba = "chat" | "resultados" | "sobre";
const ABAS: { id: Aba; rotulo: string }[] = [
  { id: "chat", rotulo: "Chat" },
  { id: "resultados", rotulo: "Resultados" },
  { id: "sobre", rotulo: "Sobre" },
];

function abaDaUrl(): Aba {
  const h = window.location.hash.replace("#", "");
  return h === "resultados" || h === "sobre" ? h : "chat";
}

export default function App() {
  const [aba, setAba] = useState<Aba>(abaDaUrl);

  useEffect(() => {
    const ouvir = () => setAba(abaDaUrl());
    window.addEventListener("hashchange", ouvir);
    return () => window.removeEventListener("hashchange", ouvir);
  }, []);

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#conteudo" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        Pular para o conteúdo
      </a>
      <header className="sticky top-0 z-20 border-b border-stone-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-2 px-3 py-3 sm:gap-4 sm:px-6">
          <a href="#chat" className="flex items-center gap-2.5" aria-label="Regimento.AI, início">
            <span aria-hidden className="flex h-8 w-8 items-center justify-center rounded-lg bg-vinho-700 text-sm font-bold text-white">R</span>
            <span className="leading-tight">
              <span className="block font-semibold text-stone-900">Regimento.AI</span>
              <span className="hidden text-[11px] text-stone-500 sm:block">UFV · campus Rio Paranaíba</span>
            </span>
          </a>
          <nav aria-label="Seções">
            <ul className="flex gap-1">
              {ABAS.map((a) => (
                <li key={a.id}>
                  <a
                    href={`#${a.id}`}
                    aria-current={aba === a.id ? "page" : undefined}
                    className={`rounded-lg px-2.5 py-2 text-sm font-medium transition sm:px-3 ${
                      aba === a.id ? "bg-vinho-50 text-vinho-800" : "text-stone-600 hover:bg-stone-100 hover:text-stone-900"
                    }`}
                  >
                    {a.rotulo}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      </header>
      <main id="conteudo" className="flex flex-1 flex-col">
        {aba === "chat" && <Chat />}
        {aba === "resultados" && <Resultados />}
        {aba === "sobre" && <Sobre />}
      </main>
    </div>
  );
}
