"""Baixa o modelo de embeddings antes da ingestão: `python -m backend.download_model`.

Separar o download da indexação deixa claro onde está a demora e permite retomar um download interrompido
(o huggingface_hub continua de onde parou e só baixa arquivos que faltam ou estão incompletos).
"""
from __future__ import annotations

import sys

from huggingface_hub import snapshot_download

from backend.config import get_settings

# Só o que o SentenceTransformer carrega. O repositório também tem .eval_results/*.yaml (benchmarks), onnx,
# openvino etc. Os YAMLs exigem symlinks, que no Windows pedem privilégio de administrador.
PERMITIR = ["*.json", "*.model", "*.safetensors", "1_Pooling/*"]
IGNORAR = [".eval_results/*", "onnx/*", "openvino/*"]


def main() -> int:
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8")
    modelo = get_settings().embedding_model
    print(f"Baixando {modelo} ...", flush=True)
    caminho = snapshot_download(repo_id=modelo, allow_patterns=PERMITIR, ignore_patterns=IGNORAR)
    print(f"Modelo em: {caminho}", flush=True)

    from sentence_transformers import SentenceTransformer  # confirma que carrega de verdade

    st = SentenceTransformer(caminho, device="cpu")
    vetor = st.encode(["query: teste"], normalize_embeddings=True)
    print(f"OK: dimensão {vetor.shape[1]}, max_seq_length {st.max_seq_length}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
