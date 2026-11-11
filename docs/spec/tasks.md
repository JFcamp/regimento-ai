# Regimento.AI — Tarefas

Status: **APROVADA**. Nada abaixo foi executado, exceto o que está marcado como feito.

Regras de execução:
- Cada etapa termina em **um commit próprio** (Etapa 1: `chore: estrutura inicial do Regimento.AI`) e só vai ao remoto com pedido explícito.
- Nenhuma etapa começa antes da aprovação da spec e da etapa anterior.
- Antes de fechar cada etapa: rodar build e testes e conferir os critérios de aceite relacionados.

## Pré-etapa (feita)

- [x] Copiar os 10 PDFs de `documentos-rag/` para `data/pdfs/` (cópia, não movimentação). `documentos-rag/` fica de backup.
- [x] Medir páginas e texto extraível de cada PDF (resultados em `requirements.md`, seção 1).
- [x] Identificar problemas: 9 págs escaneadas no PPC (48 a 56), doc 10 com glifos privados, ruído SEI, Tesseract ausente.
- [x] Escrever `requirements.md`, `design.md`, `tasks.md`.
- [ ] **Aprovação do usuário** e resposta às perguntas em aberto (`requirements.md`, seção 6).

## Etapa 1 — Estrutura do repositório (R1.4 a R1.8)

- [x] 1.1 Resolver a conta GitHub: confirmar que `gh` tem permissão em `JFcamp` (ou fazer `gh auth login` na conta certa).
- [x] 1.2 Criar a estrutura de pastas e arquivos (`.gitkeep` onde vazio, `.env.example`, `.gitignore`, `README.md` mínimo).
- [x] 1.3 `.gitignore`: `data/index/`, `documentos-rag/`, `.env`, `.venv/`, `__pycache__/`, `node_modules/`, `dist/`, caches de modelos.
- [x] 1.4 Colocar `data/pdfs/` e `manifest.json` conforme a decisão sobre versionar PDFs.
- [x] 1.5 Copiar a spec para `docs/spec/`.
- [x] 1.6 `git init`, remoto `JFcamp/regimento-ai` (público), commit único `chore: estrutura inicial do Regimento.AI`, push.
- [x] 1.7 Verificar: `gh repo view JFcamp/regimento-ai`, árvore no remoto igual à de R1.4, `data/index/` e `documentos-rag/` ausentes do remoto.

## Etapa 2 — Ingestão (R2.1 a R2.8)

- [x] 2.1 `backend/requirements.txt` com versões fixas (pymupdf, faiss-cpu, sentence-transformers, rapidfuzz, pydantic-settings, fastapi, uvicorn, pytest, pytesseract).
- [x] 2.2 `config.py` e `.env.example` completos.
- [x] 2.3 `manifest.json` com os 10 documentos, vigência e escopo.
- [x] 2.4 `extract.py`: texto por página, limpeza SEI, remapeamento PUA com validação, OCR com fallback para "ignorada".
- [x] 2.5 ~~Instalar Tesseract~~ Dispensado por decisão do projeto: págs 48 a 56 do PPC excluídas pelo manifesto e registradas no relatório.
- [x] 2.6 `chunking.py`: detecção de artigo/§, chunks 800/150 sem cortar artigo curto, tabelas.
- [x] 2.7 `indexer.py` + `ingest.py`: embeddings e5 (prefixos), FAISS, `chunks.json`, `ingest_report.json`.
- [x] 2.8 Testes pytest de ingestão (design seção 8).
- [x] 2.9 Verificar: `python -m backend.ingest` do zero, zero caracteres de área privada no índice, relatório com os 10 docs.
- [x] 2.10 Commit da etapa.

## Etapa 3 — Backend (R3.1 a R3.7)

- [x] 3.1 `schemas.py` e `prompts.py` (RAG e sem RAG).
- [x] 3.2 `retriever.py` com top-k, dedup e limiar.
- [x] 3.3 `generator.py` com providers `local`, `openai`, `anthropic` e streaming.
- [x] 3.4 `citations.py` (extração do literal, `valida`, fallback para recusa).
- [x] 3.5 `main.py`: `/chat`, `/chat?modo=sem_rag`, `/documentos`, `/health`, tratamento de erros.
- [ ] 3.6 (cortado hoje; ver design 11) Calibrar `MIN_SCORE` e `FUZZY_THRESHOLD` em perguntas de desenvolvimento (separadas das 50 do teste).
- [x] 3.7 Testes pytest de retriever e citações.
- [x] 3.8 Verificar: toda resposta do RAG tem ≥1 citação válida ou recusa explícita (critério de aceite 1).
- [x] 3.9 Commit da etapa.

## Etapa 4 — Banco de perguntas (R4.1 a R4.5)

- [x] 4.1 Redigir as 50 perguntas segundo a distribuição (45 respondíveis + 5 sem resposta), com página de origem, `revisado: false`.
- [x] 4.2 Marcar `conflito: true` nas perguntas sobre 210 h-a × PPC e nas de códigos de TCC.
- [x] 4.3 Validador (`eval/validate_perguntas.py`): 50 itens, categorias válidas, página existe no PDF, trecho do gabarito aparece na página citada.
- [ ] 4.4 (pendente: revisão humana) Entregar ao usuário para revisão (marcar `revisado: true` só depois).
- [x] 4.5 Commit da etapa.

## Etapa 5 — Avaliação (R5.1 a R5.6)

- [x] 5.1 `judge_prompt_v1.md` e `metrics.py` (veredito, alucinação, recusa, precisão de citação, bootstrap 10.000).
- [x] 5.2 `eval/run.py`: dois modos, mesmo LLM, `temperature=0`, CSV e `resumo.json`.
- [x] 5.3 `plots.py`: 3 figuras PNG 300 dpi + SVG, rótulos em português, em `docs/figuras/`.
- [ ] 5.4 (pendente: chaves de API) Rodar a avaliação (precisa do provedor definido) e conferir 10 veredictos do juiz à mão.
- [x] 5.5 Verificar: um único comando gera CSV, `resumo.json` e as 3 figuras (critério de aceite 2).
- [ ] 5.6 Commit da etapa.

## Etapa 6 — Frontend (R6.1 a R6.5)

- [x] 6.1 Scaffold Vite + React + TypeScript (estrito) + Tailwind, tokens vinho, Inter, modo escuro.
- [x] 6.2 Hook `useChatStream` (SSE via `fetch`) e tela de Chat com painel "Fontes", selo de confiança e sugestões.
- [x] 6.3 Modo "Comparar com LLM sem RAG" lado a lado.
- [x] 6.4 Tela Resultados (figuras + números do resumo.json; tela interativa cortada) e tela Sobre.
- [x] 6.5 Responsivo, acessibilidade, estados de carregamento e erro.
- [x] 6.6 `npm run build` e `tsc --noEmit` sem erros; teste manual no navegador.
- [x] 6.7 Commit da etapa.

## Etapa 7 — Docker e README (R7.1, R7.2)

- [ ] 7.1 Dockerfiles do backend e do frontend; `docker-compose.yml`.
- [ ] 7.2 `README.md` em português (problema, Mermaid, rodar, reindexar, avaliar, resultados com gráfico central, limitações, aviso legal).
- [ ] 7.3 Verificar: `docker compose up` sobe os dois serviços e o chat responde.
- [ ] 7.4 Commit da etapa.
