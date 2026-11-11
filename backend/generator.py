"""Provedores de LLM (Gemini e Groq) via HTTP, com streaming, espaçamento de pedidos e retry em 429/5xx.

Só estes dois provedores existem hoje (decisão do projeto). A chave vai em cabeçalho, nunca na URL, e nunca
aparece em mensagens de erro.
"""
from __future__ import annotations

import asyncio
import json
import random
import time
from typing import AsyncIterator, Awaitable, Callable

import httpx

from backend.config import Settings

SleepFn = Callable[[float], Awaitable[None]]
RETRY_STATUS = {429, 500, 502, 503, 504}


class ErroProvedor(RuntimeError):
    def __init__(self, codigo: str, mensagem: str, status: int | None = None) -> None:
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem
        self.status = status


class Espacador:
    """Garante um intervalo mínimo entre pedidos (plano gratuito tem limite de pedidos por minuto)."""

    def __init__(self, rpm: int) -> None:
        self.intervalo = 60.0 / rpm if rpm > 0 else 0.0
        self._proximo = 0.0
        self._lock: asyncio.Lock | None = None

    async def esperar(self, sleep: SleepFn = asyncio.sleep) -> None:
        if not self.intervalo:
            return
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            agora = time.monotonic()
            if agora < self._proximo:
                await sleep(self._proximo - agora)
            self._proximo = max(agora, self._proximo) + self.intervalo


def _espera_retry(resp: httpx.Response, tentativa: int, base: float) -> float:
    ra = resp.headers.get("retry-after")
    if ra:
        try:
            return min(float(ra), 90.0)
        except ValueError:
            pass
    return min(base * (2**tentativa), 60.0) + random.uniform(0, 1.0)


class Provedor:
    nome = ""

    def __init__(self, modelo: str, chave: str | None, s: Settings, rpm: int,
                 client: httpx.AsyncClient | None = None, sleep: SleepFn = asyncio.sleep) -> None:
        if not chave:
            raise ErroProvedor("chave_ausente", f"A chave do provedor '{self.nome}' não está configurada no .env.")
        if not modelo:
            raise ErroProvedor("modelo_ausente", f"O modelo do provedor '{self.nome}' não está configurado.")
        self.modelo, self._chave, self.s = modelo, chave, s
        self._client = client
        self._sleep = sleep
        self._espacador = Espacador(rpm)

    # --- a implementar ---
    def _requisicao(self, system: str, user: str, temperature: float, max_tokens: int) -> tuple[str, dict, dict]:
        raise NotImplementedError

    def _texto_da_linha(self, linha: str) -> str | None:
        raise NotImplementedError

    # --- comum ---
    async def stream(self, system: str, user: str, temperature: float | None = None,
                     max_tokens: int | None = None) -> AsyncIterator[str]:
        temperature = self.s.temperature if temperature is None else temperature
        url, headers, corpo = self._requisicao(system, user, temperature, max_tokens or self.s.max_output_tokens)
        cliente = self._client or httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=15.0))
        try:
            for tentativa in range(self.s.max_retries + 1):
                await self._espacador.esperar(self._sleep)
                try:
                    async with cliente.stream("POST", url, headers=headers, json=corpo) as r:
                        if r.status_code in RETRY_STATUS:
                            await r.aread()
                            if tentativa >= self.s.max_retries:
                                raise ErroProvedor(
                                    "limite_de_uso" if r.status_code == 429 else "provedor_indisponivel",
                                    f"{self.nome}: HTTP {r.status_code} após {tentativa + 1} tentativas.", r.status_code)
                            await self._sleep(_espera_retry(r, tentativa, self.s.backoff_base))
                            continue
                        if r.status_code >= 400:
                            detalhe = (await r.aread()).decode("utf-8", "replace")[:300]
                            raise ErroProvedor("erro_do_provedor", f"{self.nome}: HTTP {r.status_code}. {detalhe}", r.status_code)
                        async for linha in r.aiter_lines():
                            texto = self._texto_da_linha(linha)
                            if texto:
                                yield texto
                        return
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    if tentativa >= self.s.max_retries:
                        raise ErroProvedor("rede", f"{self.nome}: falha de rede ({type(e).__name__}).") from e
                    await self._sleep(min(self.s.backoff_base * (2**tentativa), 60.0))
        finally:
            if self._client is None:
                await cliente.aclose()

    async def completar(self, system: str, user: str, temperature: float | None = None,
                        max_tokens: int | None = None) -> str:
        return "".join([t async for t in self.stream(system, user, temperature, max_tokens)])


class Gemini(Provedor):
    nome = "gemini"

    def _requisicao(self, system, user, temperature, max_tokens):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.modelo}:streamGenerateContent?alt=sse"
        corpo = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            # margem larga: em modelos com "raciocínio", os tokens de pensamento entram no limite de saída
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max(max_tokens, 2048)},
        }
        return url, {"x-goog-api-key": self._chave, "content-type": "application/json"}, corpo

    def _texto_da_linha(self, linha: str) -> str | None:
        if not linha.startswith("data:"):
            return None
        try:
            dados = json.loads(linha[5:].strip())
        except json.JSONDecodeError:
            return None
        partes = ((dados.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in partes if not p.get("thought")) or None


class Groq(Provedor):
    nome = "groq"

    def _requisicao(self, system, user, temperature, max_tokens):
        corpo = {
            "model": self.modelo,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        headers = {"authorization": f"Bearer {self._chave}", "content-type": "application/json"}
        return "https://api.groq.com/openai/v1/chat/completions", headers, corpo

    def _texto_da_linha(self, linha: str) -> str | None:
        if not linha.startswith("data:") or "[DONE]" in linha:
            return None
        try:
            dados = json.loads(linha[5:].strip())
        except json.JSONDecodeError:
            return None
        return ((dados.get("choices") or [{}])[0].get("delta") or {}).get("content") or None


def obter_provedor(nome: str, s: Settings, client: httpx.AsyncClient | None = None) -> Provedor:
    chave = lambda k: k.get_secret_value() if k else None  # noqa: E731
    if nome == "gemini":
        return Gemini(s.gemini_model, chave(s.gemini_api_key), s, s.gemini_rpm, client)
    if nome == "groq":
        return Groq(s.groq_model, chave(s.groq_api_key), s, s.groq_rpm, client)
    raise ErroProvedor("provedor_nao_suportado", f"Provedor '{nome}' não suportado (disponíveis: gemini, groq).")
