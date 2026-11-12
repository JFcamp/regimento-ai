# Regimento.AI

Assistente acadêmico com **RAG** sobre os documentos oficiais da UFV, para estudantes de **Sistemas de Informação do campus Rio Paranaíba**. Responde só com base nos documentos, cita página e artigo de cada afirmação e diz "Não encontrei isso nos documentos oficiais" quando não há base. Um experimento compara o mesmo LLM com e sem RAG.

> As respostas não substituem a coordenação do curso nem o Registro Escolar. Em caso de dúvida, vale o documento oficial.

## O problema

As regras que um estudante precisa (trancamento, pré-requisitos, atividades complementares, extensão, prazos do calendário, TCC) estão espalhadas em 10 PDFs de anos diferentes, alguns com mais de 200 páginas, e às vezes se contradizem. Um LLM genérico responde com segurança, mas sem fonte e muitas vezes errado. O Regimento.AI só responde com trechos dos documentos e mostra o trecho literal de onde tirou cada informação.

## Arquitetura

![Arquitetura do Regimento.AI](docs/figuras/arquitetura.svg)

```mermaid
flowchart LR
  PDF[10 PDFs oficiais<br/>data/pdfs + manifest.json] --> ING[backend.ingest<br/>PyMuPDF, limpeza, chunks por artigo]
  ING --> IDX[(data/index<br/>FAISS e5 + chunks + páginas)]
  UI[Frontend React<br/>chat, fontes, comparação] -->|POST /chat SSE| API[FastAPI]
  API --> PII[máscara CPF/matrícula]
  PII --> RET[busca híbrida<br/>BM25 + e5 → RRF<br/>escopo, norma antes do PPC]
  RET --> IDX
  RET --> CTX[até 3 páginas inteiras]
  CTX --> LLM{{Gemini<br/>temperatura 0}}
  LLM --> CIT[verificação do trecho literal<br/>RapidFuzz]
  CIT --> API
  EV[eval.run<br/>50 perguntas × sem/com RAG] --> API
  EV --> JUIZ{{Groq: juiz}}
  EV --> RES[eval/resultados + docs/figuras]
  RES --> UI
```

| Pasta | Conteúdo |
|---|---|
| `backend/` | ingestão, busca híbrida, prompts, provedores (Gemini, Groq), verificação de citações, API FastAPI, testes |
| `frontend/` | React + Vite + TypeScript + Tailwind |
| `data/pdfs/` | os 10 PDFs oficiais e o `manifest.json` (título, vigência, escopo, páginas excluídas) |
| `data/index/` | índice gerado (fora do git) |
| `eval/` | banco de 50 perguntas, juiz, experimento, métricas, gráficos e resultados |
| `docs/` | especificação (`docs/spec/`) e figuras |

## Como rodar (Windows)

Requisitos: Python 3.12 e Node.js 20+.

```powershell
copy .env.example .env      # preencha GEMINI_API_KEY e GROQ_API_KEY (planos gratuitos)
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

O `run.ps1` instala o que faltar, gera o índice na primeira vez (cerca de 20 minutos em CPU), sobe o backend em `http://127.0.0.1:8000` e o frontend em `http://127.0.0.1:5173` e abre o navegador. Ctrl+C encerra os dois.

Sem `.env`, a interface abre, mas o chat só responde as perguntas sugeridas que estiverem em `data/cache/sugeridas.json` (modo demonstração). Para gerar esse cache com respostas reais: `python -m backend.build_cache`.

Para ver os modelos que suas chaves enxergam no plano gratuito: `python -m backend.listar_modelos` (os nomes mudam com frequência; ajuste `GEMINI_MODEL` e `GROQ_MODEL` no `.env`). Configuração usada no experimento: `GEMINI_MODEL=gemini-3.5-flash-lite` (os Flash "cheios" têm cota diária baixa no plano gratuito) e `GROQ_MODEL=openai/gpt-oss-120b`.

![Tela do chat com o painel de fontes](docs/figuras/tela_chat.png)

Dica: `http://127.0.0.1:5173/?q=sua+pergunta` abre o chat já com a pergunta enviada.

## Como reindexar

```powershell
python -m backend.download_model    # só na primeira vez
python -m backend.ingest            # reconstrói data/index do zero
python -m backend.ingest --dry-run  # só extrai e gera o relatório
```

O relatório `data/index/ingest_report.json` mostra, por documento, as páginas indexadas, excluídas (9 páginas escaneadas do PPC) e ignoradas, o ruído removido e os glifos remapeados. Para adicionar um documento, coloque o PDF em `data/pdfs/`, registre-o no `manifest.json` e rode a ingestão. Atalho: `.\run.ps1 -Reindexar`.

## Como rodar a avaliação

```powershell
python -m eval.validar_perguntas   # confere o banco de perguntas (evidência literal em cada página)
python -m eval.run                 # experimento completo: 50 × (sem RAG, com RAG) + juiz
python -m eval.run --so-recuperacao  # só o recall@3, sem LLM e sem chave
python -m pytest                   # testes (sem rede)
```

O `eval.run` grava o progresso depois de cada chamada em `eval/resultados/progresso.json`. Se o plano gratuito bater no limite (429), ele para e você roda de novo para continuar. Saídas: `eval/resultados/<data>.csv`, `eval/resultados/resumo.json` e as figuras em `docs/figuras/` (PNG 300 dpi + SVG).

Para medir a busca isoladamente: `python -m backend.medir_recuperacao` (hit@1 e hit@3 de 7 consultas de validação por modo de busca).

## Resultados

> **Números preliminares:** o gabarito das 50 perguntas foi gerado a partir dos PDFs e ainda **não foi revisado por um humano** (`revisado: false`).

Experimento de 11 e 12/11/2026: as mesmas 50 perguntas (45 com resposta nos documentos, 5 sem) respondidas pelo **mesmo LLM** (`gemini-3.5-flash-lite`, plano gratuito, temperatura 0) **sem RAG** e **com RAG**, julgadas por um modelo de outro fornecedor (`openai/gpt-oss-120b` no Groq; a conta não tinha Llama grande de chat disponível).

![Taxa de alucinação sem RAG × com RAG](docs/figuras/alucinacao_sem_vs_com_rag.png)

| Métrica | Sem RAG | Com RAG (Regimento.AI) |
|---|---|---|
| **Alucinação** (n = 50) | **54% (27/50)** · IC 95% bootstrap 40%–68% · Wilson 40,4%–67,0% | **2% (1/50)** · IC 95% bootstrap 0%–6% · Wilson 0,4%–10,5% |
| **Acurácia** (45 respondíveis; correta = 1, parcial = 0,5) | **33,3%** · IC 95% 22,2%–45,6% | **85,6%** · IC 95% 75,6%–94,4% |
| Acurácia estrita (só "correta") | 22,2% (10/45) | 80,0% (36/45) |
| **Recusa correta** (5 perguntas sem resposta) | **0/5** | **5/5** |
| Recusa indevida (respondível, mas recusou) | 0/45 | 3/45 |
| **Recall@3** (página do gabarito entre as 3 recuperadas) | — | **91,1% (41/45)** · IC 95% 82,2%–97,8% |
| **Precisão de citação** (citação válida na página do gabarito) | — | **87,2% (41/47)** |
| Trecho literal confirmado no PDF | — | 100% (47/47) |
| Respostas com ao menos uma citação na página certa | — | 97,6% (41/42) |

![Acurácia por categoria](docs/figuras/acuracia_por_categoria.png)

![Recuperação e citações](docs/figuras/citacao_e_recall.png)

Como ler:

- **Sem RAG**, o modelo responde tudo com segurança, inclusive as 5 perguntas sem resposta nos documentos (0/5 recusas corretas), e inventa números em mais da metade das respostas. Exemplo: dá "quatro semestres" de trancamento, quando o Regime Didático diz até cinco vezes. A pior categoria é prazos/calendário (6%).
- **Com RAG**, as 3 recusas indevidas (Q07, Q26, Q27) acontecem quando a página certa não foi recuperada. O calendário repete as mesmas frases a cada semestre, e o PPC repete a mesma informação em várias páginas.
- A **única alucinação com RAG (Q37)** parece falso positivo do juiz. A resposta traz os prazos por modalidade de mobilidade (2 ou 4 períodos intercampi, 2 nacional, 3 internacional), todos nas páginas citadas, mas o gabarito só fala do limite geral de 3. O caso está marcado para a revisão humana.
- A **precisão de citação é conservadora**. Algumas citações "fora da página do gabarito" estão certas, porque o PPC repete a tabela do catálogo e as cargas horárias em outras páginas.
- Nas 2 perguntas de **conflito** entre documentos (210 h-a × 60 h-a; SIN496 × SIN 494), o RAG citou só a norma específica e não apontou a divergência (parcial). A página do PPC com o outro valor não entrou no contexto.
- Busca, 7 consultas de validação (`python -m backend.medir_recuperacao`): hit@3 de 5/7 (só e5) para 6/7 (híbrido); hit@1 de 4/7 para 3/7.

Detalhes, por pergunta, em `eval/resultados/2026-11-12.csv` e `eval/resultados/resumo.json`.

## Limitações

- Cobre só os 10 documentos indexados. Normas mais novas ou de outros cursos não estão incluídas.
- Os documentos têm vigências diferentes (2021 a 2026) e se contradizem em pontos conhecidos, por exemplo a carga de atividades complementares (210 h-a no regulamento × 60 h-a no PPC) e o código da disciplina (SIN496 × SIN 494). O sistema avisa a divergência e cita as duas fontes em vez de escolher.
- As 9 páginas escaneadas do PPC (ata do CEPE) ficaram fora do índice (sem OCR). O PDF da Resolução de extensão tem erros de OCR na origem.
- Busca: o calendário repete as mesmas frases a cada semestre e o PPC repete informações em várias páginas, o que causa as 4 falhas de recall@3. O hit@1 do híbrido não melhorou em relação ao denso.
- 50 perguntas dão intervalos de confiança largos. Os resultados não generalizam para outros cursos.
- O juiz é um LLM (`gpt-oss-120b`, prompt versionado em `eval/judge_prompt_v1.md`) e erra às vezes (ver Q37). Não houve revisão humana dos vereditos.
- O plano gratuito limita o uso: o juiz no Groq tem 200 mil tokens por dia, e o experimento completo quase esgotou essa cota. O `eval.run` para com o progresso salvo e continua de onde parou.
- Modelos de linguagem podem errar mesmo com as fontes. Confira sempre a página citada.

## Privacidade

Não digite dados pessoais. CPF e número de matrícula são mascarados antes do envio ao LLM, mas outros dados não são. No plano gratuito do Gemini, o Google pode usar os dados enviados para melhorar seus produtos. O sistema não guarda histórico de conversas.

## Documentação

A especificação completa (requisitos, design e tarefas, com as decisões e medições de cada etapa) está em [`docs/spec/`](docs/spec/).
