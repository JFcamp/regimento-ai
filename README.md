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

## Aviso

Esta ferramenta não substitui os documentos oficiais. Em caso de dúvida, a fonte oficial da UFV prevalece.
