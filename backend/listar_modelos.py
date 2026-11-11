"""Lista os modelos que as suas chaves enxergam: python -m backend.listar_modelos"""
from __future__ import annotations

import sys

import httpx

from backend.config import get_settings


def main() -> int:
    for f in (sys.stdout, sys.stderr):
        f.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    s = get_settings()
    if s.gemini_api_key:
        r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                      headers={"x-goog-api-key": s.gemini_api_key.get_secret_value()}, timeout=30)
        print(f"Gemini (HTTP {r.status_code}):")
        if r.is_success:
            for m in r.json().get("models", []):
                if "generateContent" in m.get("supportedGenerationMethods", []):
                    print("  ", m["name"].removeprefix("models/"))
    else:
        print("Gemini: GEMINI_API_KEY não configurada")
    if s.groq_api_key:
        r = httpx.get("https://api.groq.com/openai/v1/models",
                      headers={"authorization": f"Bearer {s.groq_api_key.get_secret_value()}"}, timeout=30)
        print(f"Groq (HTTP {r.status_code}):")
        if r.is_success:
            for m in r.json().get("data", []):
                print("  ", m["id"])
    else:
        print("Groq: GROQ_API_KEY não configurada")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
