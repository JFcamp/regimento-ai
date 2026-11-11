"""Regimento.AI: pipeline RAG sobre documentos oficiais da UFV."""
import os

# O pipeline usa só PyTorch. Sem isto, o transformers importa o TensorFlow quando ele está instalado,
# o que atrasa o import por minutos e gera erros de protobuf sem relação com o projeto.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
