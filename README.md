# Regimento.AI

Assistente acadêmico com RAG sobre os documentos oficiais da UFV (campus Rio Paranaíba, Sistemas de Informação). Responde só com base nos documentos, cita página e artigo, e é avaliado contra o mesmo LLM sem RAG.

> Em construção. A especificação está em [`docs/spec/`](docs/spec/).

## Estrutura

```
backend/     FastAPI + pipeline RAG
frontend/    React + Vite + TypeScript + Tailwind
data/pdfs/   PDFs oficiais + manifest.json
data/index/  FAISS + metadados (gerado, fora do git)
eval/        banco de perguntas, scripts e resultados
docs/        spec e figuras
```

## Ingestão (Etapa 2)

Requer Python 3.12. Instale as dependências de `backend/requirements.txt` (para o `torch`, use a build adequada ao seu hardware).

```bash
python -m backend.download_model   # baixa o multilingual-e5-base (~1 GB), só na primeira vez
python -m backend.ingest           # reconstrói o índice do zero em data/index/
python -m backend.ingest --dry-run # só extrai e gera o relatório, sem embeddings
python -m pytest                   # testes
```

A ingestão gera em `data/index/`: `index.faiss`, `chunks.json`, `paginas.json`, `meta.json` e `ingest_report.json` (páginas excluídas, ruído removido, glifos remapeados, artigos detectados por documento). Em CPU, os embeddings levam cerca de 20 minutos.

Se o remapeamento de glifos de algum PDF não passar na validação, a ingestão para com código de saída 2 e mantém o índice anterior.

## Aviso

Esta ferramenta não substitui os documentos oficiais. Em caso de dúvida, a fonte oficial da UFV prevalece.
