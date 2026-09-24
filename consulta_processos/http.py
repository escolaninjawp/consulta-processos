"""Camada HTTP: cabeçalhos de navegador, proxies e tentativas em paralelo.

As APIs públicas do CNJ ficam atrás de proteção contra automação. Duas coisas
resolvem quase tudo: mandar os mesmos cabeçalhos que um navegador manda e, quando
disponível, usar o `curl_cffi`, que imita também a impressão digital TLS do Chrome.
Sem o `curl_cffi` instalado, cai para o `httpx` — funciona, mas é mais fácil de
ser barrado em volume.
"""
from __future__ import annotations

import logging
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx

from .config import Config, config_padrao
from .proxies import PoolProxies

logger = logging.getLogger(__name__)

try:  # opcional, mas muito recomendado
    from curl_cffi import requests as _cffi
    TEM_CURL_CFFI = True
except ImportError:                                   # pragma: no cover
    _cffi = None
    TEM_CURL_CFFI = False

# Perfis de navegador que o curl_cffi sabe imitar
_IMPERSONATIONS = ["chrome124", "chrome120", "chrome116", "edge101", "safari17_2_ios"]

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",  # noqa: E501
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",  # noqa: E501
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def cabecalhos_navegador(origem: str = "", referer: str = "", extra_ua: str = "") -> dict:
    """Cabeçalhos equivalentes aos de um navegador comum."""
    ua = random.choice(_USER_AGENTS)
    if extra_ua:
        ua = f"{ua} {extra_ua}"      # identifique-se aqui, se quiser (contato/projeto)
    cabecalhos = {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Chromium";v="131", "Google Chrome";v="131", "Not.A/Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if origem:
        cabecalhos["Origin"] = origem
    if referer:
        cabecalhos["Referer"] = referer
    return cabecalhos


class Resposta:
    """Resposta simples, igual para curl_cffi e httpx."""

    def __init__(self, status: int, texto: str = "", sem_conexao: bool = False):
        self.status = status
        self.texto = texto
        self.sem_conexao = sem_conexao      # nenhum proxy chegou a responder

    @property
    def ok(self) -> bool:
        return self.status == 200

    @property
    def definitiva(self) -> bool:
        """A fonte respondeu de verdade (inclusive dizendo 'não achei')."""
        return self.status in (200, 400, 404)

    def json(self):
        import json
        return json.loads(self.texto) if self.texto else {}

    def __repr__(self) -> str:
        return f"Resposta(status={self.status}, {len(self.texto)} bytes)"


class Cliente:
    """GET com proxies opcionais e disparo em paralelo.

    Quando há pool de proxies, dispara algumas tentativas ao mesmo tempo e fica com
    a primeira resposta boa: em pools residenciais, sempre há IPs lentos, e esperar
    um por vez torna a consulta lenta demais.
    """

    def __init__(self, config: Config | None = None, pool: PoolProxies | None = None):
        self.config = config or config_padrao()
        self.pool = pool if pool is not None else PoolProxies(self.config)

    # ── interno ───────────────────────────────────────────────────────────────

    def _uma_tentativa(self, url: str, params: dict, cabecalhos: dict,
                       timeout: float, proxy: str | None) -> Resposta | None:
        proxies = {"http": proxy, "https": proxy} if proxy else None
        try:
            if _cffi is not None:
                r = _cffi.get(url, params=params, headers=cabecalhos,
                              impersonate=random.choice(_IMPERSONATIONS),
                              timeout=timeout, verify=True, proxies=proxies)
                return Resposta(r.status_code, r.text)
            with httpx.Client(timeout=timeout, proxy=proxy, follow_redirects=True) as cliente:
                r = cliente.get(url, params=params, headers=cabecalhos)
                return Resposta(r.status_code, r.text)
        except Exception as e:
            logger.debug("[http] tentativa falhou (%s): %s", proxy or "sem proxy", e)
            return None

    # ── uso ───────────────────────────────────────────────────────────────────

    def get(self, url: str, params: dict, *, timeout: float | None = None,
            origem: str = "", referer: str = "") -> Resposta:
        cabecalhos = cabecalhos_navegador(origem, referer, self.config.user_agent_extra)
        timeout = timeout or self.config.comunica_timeout

        proxies = list(self.pool.urls()) if self.config.usa_proxy else []
        if not proxies:
            resposta = self._uma_tentativa(url, params, cabecalhos, timeout, None)
            return resposta or Resposta(503, "", sem_conexao=True)

        random.shuffle(proxies)
        em_paralelo = max(1, self.config.proxies_em_paralelo)
        teto = min(len(proxies), self.config.proxies_max_tentativas)
        ultima: Resposta | None = None

        for inicio in range(0, teto, em_paralelo):
            lote = proxies[inicio:inicio + em_paralelo]
            executor = ThreadPoolExecutor(max_workers=len(lote))
            futuros = [executor.submit(self._uma_tentativa, url, params, cabecalhos, timeout, p)
                       for p in lote]
            vencedora = None
            try:
                for futuro in as_completed(futuros):
                    resposta = futuro.result()
                    if resposta is None:
                        continue
                    if resposta.definitiva:
                        vencedora = resposta
                        break
                    ultima = resposta          # 403/429/5xx: guarda e tenta o próximo lote
            finally:
                executor.shutdown(wait=False)  # não espera as tentativas perdedoras
            if vencedora is not None:
                return vencedora

        return ultima or Resposta(503, "", sem_conexao=True)

    def post_json(self, url: str, payload: dict, cabecalhos: dict,
                  timeout: float, timeout_conexao: float) -> Resposta:
        """POST direto (Datajud aceita consulta sem proxy e sem disfarce)."""
        try:
            tempo = httpx.Timeout(timeout, connect=timeout_conexao)
            with httpx.Client(timeout=tempo) as cliente:
                r = cliente.post(url, json=payload, headers=cabecalhos)
                return Resposta(r.status_code, r.text)
        except httpx.TimeoutException:
            return Resposta(504, "", sem_conexao=True)
        except Exception as e:
            logger.debug("[http] POST falhou: %s", e)
            return Resposta(503, "", sem_conexao=True)
