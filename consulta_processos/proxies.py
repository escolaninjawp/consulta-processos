"""Pool de proxies (opcional).

Só é necessário quando a consulta sai de fora do Brasil ou em volume alto: a API
do Comunica é do gov.br e responde 403 para saídas estrangeiras. De um IP
brasileiro, rodando poucas consultas, deixe a lista vazia.

Fontes possíveis, combinadas nesta ordem:
1. gateway residencial expandido em N portas (cada porta = um IP/sessão);
2. API de um provedor que lista os proxies da conta (opcional);
3. lista fixa vinda da configuração.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from .config import Config, config_padrao

logger = logging.getLogger(__name__)

_PROXYSELLER_API = "https://proxy-seller.com/personal/api/v1"
_TIPOS_LISTA = ("ipv4", "isp", "mix", "mobile", "ipv6")
# Endereço usado só para testar se o proxy chega ao destino a partir de um IP BR
_URL_TESTE = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"


def _do_gateway(cfg: Config) -> list[str]:
    """Expande o gateway em uma URL por porta — cada porta costuma ser outro IP."""
    if not (cfg.gateway_host and cfg.gateway_login and cfg.gateway_senha and cfg.gateway_portas):
        return []
    qtd = max(1, min(cfg.gateway_portas, 1000))
    ini = cfg.gateway_porta_inicial
    return [f"http://{cfg.gateway_login}:{cfg.gateway_senha}@{cfg.gateway_host}:{porta}"
            for porta in range(ini, ini + qtd)]


def _eh_lista_brasileira(lista: dict) -> bool:
    if "brasil" in (lista.get("title") or "").lower():
        return True
    return any((g.get("country") or "").lower() in ("br", "brazil", "brasil")
               for g in lista.get("geo") or [])


def _do_proxyseller(chave: str) -> list[str]:
    """Lista os proxies da conta em um provedor com API (Proxy Seller).

    Opcional: serve de exemplo de como plugar um provedor. Qualquer outro serviço
    entra do mesmo jeito, bastando devolver URLs `http://login:senha@host:porta`.
    """
    if not chave:
        return []
    pool: list[str] = []
    for tipo in _TIPOS_LISTA:
        try:
            r = httpx.get(f"{_PROXYSELLER_API}/{chave}/proxy/list/{tipo}", timeout=20)
            if r.status_code != 200:
                continue
            dados = (r.json() or {}).get("data")
            itens = dados.get("items") if isinstance(dados, dict) else (dados or [])
            for item in itens or []:
                ip, porta = item.get("ip"), item.get("port_http") or item.get("port")
                login, senha = item.get("login"), item.get("password")
                if ip and porta and login and senha and item.get("active", True) not in (False, 0, "0"):
                    pool.append(f"http://{login}:{senha}@{ip}:{porta}")
        except Exception as e:
            logger.warning("[proxies] falha ao listar %s: %s", tipo, e)
    try:
        r = httpx.get(f"{_PROXYSELLER_API}/{chave}/resident/lists", timeout=20)
        if r.status_code == 200:
            listas = (r.json() or {}).get("data") or []
            # Prioriza listas brasileiras: o gov.br recusa saída estrangeira
            for lista in [x for x in listas if _eh_lista_brasileira(x)] or listas:
                login, senha, host = lista.get("login"), lista.get("password"), lista.get("host")
                porta = lista.get("port")
                if login and senha and host and porta:
                    pool.append(f"http://{login}:{senha}@{host}:{porta}")
    except Exception as e:
        logger.warning("[proxies] falha ao listar residenciais: %s", e)
    return pool


def _roteia_ate_o_destino(url: str, timeout: float = 6.0) -> bool:
    """Descarta proxy morto ou estrangeiro antes de usá-lo numa consulta real.

    Qualquer resposta HTTP do gov.br (200/400/5xx) prova que o proxy chegou lá e o
    IP foi aceito. 403 é IP de fora do país; erro/timeout é proxy ruim.
    """
    try:
        from curl_cffi import requests as cffi
    except ImportError:
        return True  # sem como testar, assume utilizável
    try:
        r = cffi.get(_URL_TESTE, params={"numeroOab": "1", "ufOab": "SP", "tamanhoPagina": 1},
                     impersonate="chrome124", timeout=timeout,
                     proxies={"http": url, "https": url}, verify=True)
        return r.status_code != 403
    except Exception:
        return False


class PoolProxies:
    """Lista de proxies com cache por tempo, recarregada sozinha."""

    def __init__(self, config: Config | None = None):
        self.config = config or config_padrao()
        self._cache: list[str] = []
        self._carregado_em: float = 0.0

    def carregar(self) -> list[str]:
        cfg = self.config
        pool: list[str] = []
        vistos: set[str] = set()

        def add(url: str):
            url = (url or "").strip()
            if url and url not in vistos:
                vistos.add(url)
                pool.append(url)

        for url in _do_gateway(cfg):
            add(url)
        for url in _do_proxyseller(cfg.proxyseller_api_key):
            add(url)

        # Lista fixa: passa por um teste rápido, senão um proxy quebrado atrasa tudo
        fixos = []
        for url in cfg.proxies:
            if not url.startswith(("http://", "https://", "socks5://", "socks4://")):
                url = "http://" + url
            fixos.append(url)
        if fixos:
            with ThreadPoolExecutor(max_workers=min(8, len(fixos))) as executor:
                saudaveis = list(executor.map(_roteia_ate_o_destino, fixos))
            for url, ok in zip(fixos, saudaveis, strict=False):
                if ok:
                    add(url)
            logger.info("[proxies] %s de %s proxies fixos responderam", sum(saudaveis), len(fixos))
        return pool

    def urls(self) -> list[str]:
        """Pool atual (recarrega quando o cache vence)."""
        agora = time.time()
        if not self._cache or (agora - self._carregado_em) > self.config.proxy_pool_ttl:
            novo = self.carregar()
            if novo or not self._cache:
                self._cache = novo
            self._carregado_em = agora
            if self._cache:
                logger.info("[proxies] pool com %s proxies", len(self._cache))
        return self._cache

    def __len__(self) -> int:
        return len(self.urls())

    def __bool__(self) -> bool:
        return bool(self.urls())
