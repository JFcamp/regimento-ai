# Regimento.AI — Requisitos

Assistente acadêmico com RAG sobre os documentos oficiais da UFV (campus Rio Paranaíba, Sistemas de Informação). O sistema responde só com base nos documentos, cita trecho literal com página e artigo, e é avaliado contra o mesmo LLM sem RAG.

Status: **APROVADA** (ver seção 7 para as decisões).

## 1. Corpus (caminho oficial: `data/pdfs/`)

`documentos-rag/` é só backup local e vai para o `.gitignore`. A pasta `data/pdfs/` é o único caminho usado na spec e no código. Cópias já feitas: 10 PDFs.

| # | Arquivo | Págs | Vigência | Resumo (1 linha) | Texto extraível |
|---|---------|------|----------|------------------|-----------------|
| 1 | `SEI-UFV-Resolucao-30-2026.pdf` | 25 | 2026 (23/04/2026) | Resolução CEPE 30/2026: Regime Didático da graduação (matrícula, trancamento, frequência, aprovação, desligamento). | Sim |
| 2 | `calendario.pdf` | 10 | 2026/1 e 2026/2 | Resolução CEPE 24/2025 (texto consolidado): calendário escolar dos campi Viçosa, Florestal e Rio Paranaíba. | Sim |
| 3 | `MatrizCurricular2023-Sistemas-de-informacao.pdf` | 5 | Catálogo 2023 | Catálogo de Sistemas de Informação (Integral): disciplinas por período, créditos e pré-requisitos. | Sim |
| 4 | `PPC-Sistemas_de_Informacao2022-.pdf` | 272 | 2022 | Projeto Pedagógico do Bacharelado em SI (perfil, matriz, anexos de atividades complementares, extensão, TCC). | Parcial: 9 págs escaneadas (48 a 56) |
| 5 | `RegulamentoTCC_Sistemas_2026-1.pdf` | 9 | A partir de 2025 | Regulamento do TCC de SI (Integral e Noturno): oferta, orientação, banca, prazos. | Sim |
| 6 | `RegulamentoAtividadeComplementares_2021_atual.pdf` | 5 | A partir de 2021 | Regulamento de Atividades Complementares de SI: carga horária, tabela de atividades e limites, registro. | Sim |
| 7 | `Resolucao-Cepe-6-2022-Creditacao-das-atividades-de-extensao-1.pdf` | 5 | 2022 (vigor 01/04/2022) | Resolução CEPE 6/2022: creditação curricular da extensão (mínimo de 10% da carga horária). | Sim |
| 8 | `Resolucao-Cepe-no-8-2024-Regulamenta-a-politica-e-estabelece-os-procedimentos-de-Mobilidade-Academica-da-graduacao-da-UFV.pdf` | 5 | 2024 | Resolução CEPE 8/2024: mobilidade acadêmica (intercampi, nacional e internacional). | Sim |
| 9 | `Orientacoes-Colacao-de-Grau.pdf` | 2 | 2026/1 | Aviso da Diretoria de Ensino: datas e locais da colação de grau de 31/07/2026 e eventos. | Sim |
| 10 | `REGIMENTO-GERAL-UFV-2026.pdf` | 23 | 2026 (23/03/2026) | **Atenção ao nome**: é a Resolução CEPE 29/2026, Regimento da Pós-Graduação Stricto Sensu, não o Regimento Geral. | Corrompido (ver 1.2) |

Total: 10 PDFs, 361 páginas.

### 1.1 Decisões sobre o corpus

- **R1.1** O doc 10 é pós-graduação, mas fica no índice por decisão do usuário (fica se estiver na pasta). Por ser fora do foco (graduação), a UI e o prompt devem tratá-lo como `escopo: pos-graduacao`. A resposta deve avisar quando a fonte for de pós-graduação e não valer para o aluno de graduação.
- **R1.2** Cada documento tem um registro em `data/pdfs/manifest.json` com: `id`, `arquivo`, `titulo`, `tipo`, `escopo` (`graduacao` | `curso-si` | `pos-graduacao`), `vigencia` (data ou ano de início), `fonte_oficial` (URL, quando houver) e `paginas`. O nome real do doc 10 fica no manifesto como título, e o arquivo mantém o nome atual.
- **R1.3** Documentos de anos diferentes podem se contradizer. O sistema deve expor `vigencia` em cada citação e, em conflito, preferir o documento mais recente e específico. Quando os trechos recuperados divergirem, a resposta deve apontar a divergência em vez de escolher em silêncio.

### 1.2 Problemas de extração já medidos (PyMuPDF 1.25.5)

1. **Doc 10 com glifos privados.** O PDF usa caracteres Unicode da área privada no lugar de "t", "f", "fi", "ti" (`\ue044`, `\ue01c`, `\ue02e`, `\ue02f`, `\ue046`). Exemplo: "Ar\ue044." em vez de "Art.", "S\ue01cric\ue01co" em vez de "Stricto". Os outros 9 PDFs não têm o problema (contagem de "Art." e "estudante" normal). Sem tratamento, o artigo não é detectado e a busca falha. Exige remapeamento validado ou OCR (ver design 3.2).
2. **Doc 4 (PPC) com 9 páginas escaneadas**, páginas 48 a 56: Anexo I, ata da 448ª reunião do CEPE que autoriza a criação do curso. Sem texto extraível, só imagem. As outras 263 páginas têm texto. Exige OCR ou exclusão consciente (ver R2.5).
3. **Ruído SEI.** Os PDFs com origem no SEI têm cabeçalho e rodapé repetidos em toda página (data/hora, "SEI/UFV - nnnnnnn - Resolução", URL longa, "n/N"). Devem ser removidos antes do chunking.
4. **Tesseract não está instalado** nesta máquina. O OCR depende de instalação (ver tasks, Etapa 2).

### 1.3 Inconsistências conhecidas entre documentos

Servem de armadilha para o RAG e entram no banco de avaliação com o campo `observacao`.

- **Atividades complementares:** o Regulamento de AC (doc 6, art. 4º) exige **210 horas/aula** e cita a disciplina **SIN496**. A leitura do PPC (anexos) e do catálogo aponta carga e códigos diferentes (60 h-aula e SIN494/496 em partes do texto). A spec não decide qual é o certo. O gabarito deve citar o documento e a página, e a pergunta é marcada `conflito: true`.
- **TCC:** códigos de disciplina divergem entre PPC e grade (SIN498/499 versus SIN488/489).
- **TCC regulamento:** os arts. 16 e 19 se referem ao "Art. 13º" de forma circular.
- **Doc 10** tem remissões internas que parecem desalinhadas com a numeração (ex.: o art. 39 e o art. 56, § 1º, citam o "art. 34" para créditos, mas o art. 34 trata do ano letivo e os créditos estão nos arts. 33 e 35). O sistema cita o texto como está, sem corrigir.

## 2. Requisitos funcionais

Numeração por etapa, na ordem pedida.

### Etapa 1: Estrutura do repositório

- **R1.4** Criar repositório **novo e público** `regimento-ai` na conta GitHub `JFcamp`, com esta estrutura:
  ```
  regimento-ai/
  ├── backend/        # FastAPI + pipeline RAG portado do notebook do rag-plantas-medicinais (sem a parte de CNN)
  ├── frontend/       # React + Vite + TypeScript + Tailwind
  ├── data/pdfs/      # PDFs oficiais
  ├── data/index/     # FAISS + metadados (gerado, no .gitignore)
  ├── eval/           # banco de perguntas, scripts e resultados
  ├── docs/           # spec e figuras do pôster
  ├── .env.example
  ├── .gitignore
  └── README.md
  ```
- **R1.5** `.gitignore` deve ignorar: `data/index/`, `documentos-rag/`, `.env`, `__pycache__/`, `.venv/`, `node_modules/`, `dist/`, caches de modelos.
- **R1.6** Esta etapa é um commit isolado, com a mensagem exata `chore: estrutura inicial do Regimento.AI`, seguido de push.
- **R1.7** Pastas vazias não são rastreadas pelo git. Usar `.gitkeep` onde necessário.
- **R1.8** Os PDFs oficiais são documentos públicos da UFV. Antes do push público, o usuário confirma que pode versioná-los (ver Perguntas em aberto).

### Etapa 2: Ingestão

- **R2.1** `python -m backend.ingest` reconstrói tudo do zero, de forma determinística, a partir de `data/pdfs/`.
- **R2.2** Extrair texto por página com PyMuPDF. Cada trecho guarda `documento` (id do manifesto), `pagina` (1-indexada, física do PDF) e `artigo` (ex.: "Art. 45", "§ 2º") quando detectável.
- **R2.3** Chunking de ~800 caracteres com overlap de ~150, sem quebrar um artigo ao meio quando ele couber em um chunk. Artigos maiores que o limite são divididos por parágrafo (§) ou inciso, repetindo o cabeçalho do artigo no chunk seguinte.
- **R2.4** Embeddings com `intfloat/multilingual-e5-base`, usando os prefixos `passage: ` na indexação e `query: ` na consulta. Índice FAISS e metadados JSON gravados em `data/index/`.
- **R2.5** Páginas sem texto: OCR (pt-BR). Se o OCR não estiver disponível, a página é registrada como `ignorada` em `data/index/ingest_report.json` e a ingestão segue, sem falhar em silêncio.
- **R2.6** Limpar ruído SEI (cabeçalho e rodapé) antes do chunking, sem apagar conteúdo normativo.
- **R2.7** Remapear os glifos privados do doc 10 e validar o resultado: o texto remapeado deve conter ao menos N ocorrências de "Art." e nenhum caractere de área privada restante. Se a validação falhar, usar OCR para esse documento.
- **R2.8** Gerar `ingest_report.json`: por documento, nº de páginas, páginas ignoradas, nº de chunks, nº de artigos detectados.

### Etapa 3: Backend (FastAPI)

- **R3.1** Módulos: `retriever.py`, `generator.py`, `prompts.py`, `config.py`, mais `main.py` (rotas) e `citations.py` (verificação).
- **R3.2** Provedor de LLM via `.env`: `LLM_PROVIDER=local|openai|anthropic`. `local` = Qwen2.5-3B via `transformers`. Chaves e nomes de modelo vêm do `.env`, nunca do código.
- **R3.3** System prompt: responder **somente** com base nos trechos fornecidos. Se não houver base, responder exatamente: **"Não encontrei isso nos documentos oficiais"**. Toda afirmação carrega citação `[n]`.
- **R3.4** Endpoints:
  - `POST /chat`: streaming SSE; ao final envia as citações `{id, documento, pagina, artigo, trecho_literal, score}`.
  - `POST /chat?modo=sem_rag`: mesmo LLM, sem recuperação (baseline).
  - `GET /documentos`: lista do manifesto (id, título, vigência, escopo, páginas).
  - `GET /health`: estado do índice e do provedor de LLM.
- **R3.5** Verificação de citação: o `trecho_literal` de cada citação precisa existir no chunk recuperado (correspondência exata ou fuzzy acima de limiar configurável). Se não existir, a citação é marcada `valida: false`.
- **R3.6** Recusa: se o melhor `score` ficar abaixo de um limiar configurável, ou o LLM responder a frase de recusa, o backend devolve a recusa padrão sem inventar citação.
- **R3.7** Erros do provedor (timeout, chave ausente) viram resposta estruturada com código HTTP adequado, sem vazar a chave.

### Etapa 4: Banco de perguntas

- **R4.1** `eval/perguntas.json` com **50 perguntas**: `{id, pergunta, resposta_gabarito, documento, pagina, categoria, revisado, observacao?, conflito?, respondivel}`.
- **R4.2** Categorias: `trancamento`, `pre-requisitos`, `horas-complementares-extensao`, `prazos-calendario`, `outros`.
- **R4.3** Rascunho gerado a partir dos PDFs, cada pergunta com a página de origem. Todas entram com `"revisado": false`. O usuário revisa antes de qualquer número ser publicado.
- **R4.4** **45 respondíveis + 5 sem resposta** nos documentos (`respondivel: false`, `documento: null`), para medir recusa correta.
- **R4.5** Distribuição entre os 10 documentos e entre as categorias: ver seção 3.

### Etapa 5: Avaliação

- **R5.1** `python -m eval.run` roda as 50 perguntas nos dois modos (com e sem RAG), com o mesmo LLM e `temperature=0`.
- **R5.2** Métricas por pergunta: `correta` | `parcial` | `incorreta` (LLM-juiz com prompt versionado em `eval/judge_prompt_v1.md`); `alucinou` (bool); `recusa_correta` (nas não respondíveis); e, só no RAG, `precisao_citacao` (a página citada bate com o gabarito? o literal existe?).
- **R5.3** Saídas: `eval/resultados/<data>.csv` e `eval/resultados/resumo.json`.
- **R5.4** Figuras em `docs/figuras/` (PNG 300 dpi e SVG, rótulos em português):
  1. Taxa de alucinação sem RAG × com RAG, com IC 95% por bootstrap.
  2. Acerto por categoria nos dois modos.
  3. Precisão de citação do RAG.
- **R5.5** Um único comando gera as 3 figuras ao fim do experimento.
- **R5.6** Resultados só entram no README e na UI com `revisado: true` em todas as perguntas, ou com aviso explícito do percentual revisado.

### Etapa 6: Frontend

- **R6.1** React + Vite + TypeScript + Tailwind. Identidade UFV (vinho/bordô), fonte Inter, modo escuro.
- **R6.2** **Chat** com streaming SSE; citações `[n]` clicáveis; painel lateral "Fontes" com documento, página, artigo e o trecho literal destacado; selo de confiança ("Fundamentado em N trechos" ou "Não encontrado nos documentos"); sugestões iniciais; chave "Comparar com LLM sem RAG" que mostra lado a lado.
- **R6.3** Tela **Avaliação**: lê `resumo.json`, gráficos em Recharts, tabela das 50 perguntas filtrável por categoria e resultado.
- **R6.4** Tela **Sobre**: metodologia, lista de documentos (com vigência), aviso de que a fonte oficial prevalece.
- **R6.5** Responsivo, acessível (foco visível, contraste AA, rótulos ARIA, navegação por teclado), com estados de carregamento e erro. A validação completa de acessibilidade exige teste manual com leitores de tela.

### Etapa 7: Docker e README

- **R7.1** `docker-compose.yml` com backend e frontend.
- **R7.2** `README.md` em português: problema, arquitetura (Mermaid), como rodar, como reindexar, como rodar a avaliação, resultados com o gráfico central, limitações, aviso legal.

## 3. Distribuição das 50 perguntas

| Documento | Respondíveis | Foco |
|-----------|-------------:|------|
| Regime Didático (Res. 30/2026) | 8 | trancamento, frequência, aprovação, desligamento, créditos |
| Calendário 2026 | 6 | datas de trancamento, início e fim de aulas |
| Catálogo 2023 (matriz curricular) | 5 | pré-requisitos, créditos, carga horária por período |
| PPC 2022 | 5 | perfil, carga total, tempo de integralização, anexos |
| Regulamento do TCC | 5 | oferta, banca, prazos, aproveitamento de horas |
| Regulamento de Atividades Complementares | 5 | aproveitamento de horas, limites da tabela, registro |
| Res. CEPE 6/2022 (extensão) | 4 | 10% mínimo, o que conta e o que não conta |
| Res. CEPE 8/2024 (mobilidade) | 3 | limites de períodos, prazos, desligamento |
| Colação de grau 2026/1 | 2 | datas, horários, locais |
| Pós-graduação (Res. 29/2026) | 2 | trancamento e prazos de pós (teste de escopo) |
| **Sem resposta nos documentos** | **5** | recusa correta |
| **Total** | **50** | |

Distribuição por categoria (meta): `trancamento` 8, `pre-requisitos` 8, `horas-complementares-extensao` 12, `prazos-calendario` 12, `outros` 10 (inclui as 5 sem resposta).

Observações:
- A matriz curricular alimenta a categoria `pre-requisitos`.
- Os regulamentos de TCC e de AC alimentam `horas-complementares-extensao` (aproveitamento de horas).
- A colação de grau e o calendário alimentam `prazos-calendario`.
- Pelo menos 2 perguntas de atividades complementares são marcadas `conflito: true` (210 h-a versus o valor do PPC).

### Exemplos verificados no texto (sementes do banco; página = página física do PDF)

| Pergunta | Gabarito | Fonte |
|----------|----------|-------|
| Qual a carga horária mínima de atividades complementares exigida no regulamento do curso? | 210 horas/aula (art. 4º). Marcar conflito com o PPC. | AC, p. 2 |
| Quantas horas de monitoria contam como atividade complementar? | 30 h-a por semestre letivo, máximo de 60 h-a. | AC, p. 4 |
| Qual o limite para atividades culturais e esportivas? | 5 h-a por semestre, máximo de 10 h-a. | AC, p. 4 |
| Qual o percentual mínimo da carga horária que deve ser de extensão? | 10% da carga horária total (art. 8º). | Res. 6/2022, p. 3 |
| Quantos períodos letivos pode durar o afastamento para mobilidade? | No máximo 3, consecutivos ou não, exceto intercampi (art. 5º). | Res. 8/2024, p. 2 |
| Quantos períodos um aluno de curso não tecnológico pode cursar em outro campus? | 4 períodos (art. 10). | Res. 8/2024, p. 3 |
| Quando e onde é a colação de grau de 2026/1? | 31/07/2026, às 18h, no Espaço Multiuso do Campus Rio Paranaíba. | Colação, p. 1 |
| Quantas vezes um mestrando pode trancar a matrícula? (pós) | No máximo 2 períodos letivos (art. 28, § 3º). | Pós, p. 8 |

As demais perguntas (Regime Didático, Calendário, Catálogo, PPC, TCC) são redigidas na Etapa 4 a partir dos PDFs, com página, e conferidas pelo usuário.

Exemplos de perguntas sem resposta nos documentos: valor da taxa de inscrição na pós, cardápio do restaurante universitário, telefone da coordenação do curso, regras de estacionamento no campus, nota de corte do SiSU.

## 4. Critérios de aceite

1. Toda resposta do RAG tem **pelo menos uma citação válida** ou uma **recusa explícita**.
2. O experimento roda ponta a ponta com **um comando** e gera as 3 figuras.
3. Cada etapa vira **um commit próprio** em `JFcamp/regimento-ai`.
4. Código tipado (type hints no Python, TypeScript estrito) e testes `pytest` básicos para: ingestão, retriever e verificação de citação.
5. `python -m backend.ingest` reconstrói o índice do zero e gera `ingest_report.json` sem erro.
6. O doc 10 não deixa caracteres de área privada no índice.

## 5. Fora de escopo

- Autenticação e contas de usuário.
- Atualização automática dos PDFs a partir do SEI.
- Aconselhamento acadêmico individual (o sistema só informa o que os documentos dizem).
- Cobertura de outros cursos além de Sistemas de Informação, exceto os documentos gerais de graduação.

## 6. Perguntas em aberto (precisam de decisão antes da Etapa 1)

1. **Conta GitHub.** O `gh` local está logado como `pedro-aguila-hub`, com escopo `repo`. Criar o repositório em `JFcamp` exige que essa conta tenha permissão lá (ser a própria `JFcamp` ou membro com direito de criar). Se não tiver, preciso que você faça login na conta certa (`gh auth login`) ou crie o repo vazio.
2. **Notebook do `rag-plantas-medicinais`.** O backend é "portado" desse notebook, mas eu não tenho acesso a ele. Preciso do repositório ou do arquivo `.ipynb`. Sem isso, escrevo o pipeline do zero seguindo esta spec.
3. **Versionar os PDFs em repositório público.** São documentos públicos da UFV, mas confirme que pode publicá-los. A alternativa é ignorar `data/pdfs/*.pdf` e manter só o `manifest.json` com links.
4. **OCR.** O Tesseract não está instalado. Preciso poder instalá-lo (com o pacote de idioma `por`), ou aceitar que as 9 páginas escaneadas do PPC (e o doc 10, se o remapeamento falhar) fiquem fora do índice.
5. **Hardware para o LLM local.** Qwen2.5-3B via `transformers` precisa de GPU ou muita RAM. Qual máquina vai rodar a avaliação? Sem GPU, a avaliação com `local` fica lenta.
6. **Qual provedor usar na avaliação final** (`local`, `openai` ou `anthropic`) e qual modelo-juiz. O juiz pode ser o mesmo LLM ou outro; escolher outro reduz viés.

## 7. Decisões aprovadas (substituem as perguntas em aberto da seção 6)

1. **GitHub:** repositório público `JFcamp/regimento-ai`. A conta JFcamp está logada no `gh`, mas pode não ser a ativa; usar o token dela só nos comandos do projeto (`GH_TOKEN`), sem trocar a conta ativa global.
2. **Notebook:** clonar `https://github.com/JFcamp/rag-plantas-medicinais` numa pasta temporária fora do projeto, ler `rag_plantas_medicinais_colab.ipynb` e portar só a parte de RAG (chunking, e5, FAISS, recuperação de páginas inteiras, prompt e streaming). Sem CNN. O clone não é versionado.
3. **PDFs:** podem ser versionados. O arquivo 10 foi renomeado para `Resolucao-CEPE-29-2026-Pos-Graduacao.pdf`; o nome original (`REGIMENTO-GERAL-UFV-2026.pdf`) fica em `manifest.json` (`arquivo_original`).
4. **OCR:** Tesseract **não** será instalado agora.
   - PPC, páginas 48 a 56 (ata do CEPE): excluídas do índice e registradas no relatório de ingestão (`paginas_excluidas` no manifesto).
   - Doc 10: remapear os glifos privados e validar (contagem de "Art." > 0 e "Stricto" presente). **Se a validação falhar, avisar o usuário; não partir para OCR.**
5. **Hardware:** a avaliação roda via API, sem modelo local. O provedor `local` (Qwen2.5-3B) permanece só como opção no código, documentado para rodar no Colab com T4.
6. **Provedores:** modelo avaliado nos dois modos (sem RAG e com RAG), temperatura 0: OpenAI `gpt-4o-mini`. Juiz: Anthropic (Claude), outro fornecedor, para reduzir viés; prompt do juiz versionado em `eval/`. Chaves em `.env` (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`), nunca commitadas.
7. **Conflito de atividades complementares:** aprovado como está (`conflito: true` e citar a vigência de cada fonte). No pôster, vira exemplo de por que citar a fonte importa.
8. **Fluxo:** um commit por etapa, push ao final de cada uma.