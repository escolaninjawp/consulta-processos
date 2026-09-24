"""Configuração da biblioteca.

Tudo vem de variáveis de ambiente (ou do `.env`, se você usar python-dotenv).
Nenhuma credencial fica no código — veja `.env.exemplo`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(nome: str, padrao: str = "") -> str:
    return (os.environ.get(nome) or padrao).strip()


def _env_int(nome: str, padrao: int) -> int:
    try:
        return int(_env(nome) or padrao)
    except ValueError:
        return padrao


def _env_float(nome: str, padrao: float) -> float:
    try:
        return float(_env(nome) or padrao)
    except ValueError:
        return padrao


@dataclass
class Config:
    """Parâmetros de acesso às fontes.

    Use `Config.do_ambiente()` para ler do ambiente, ou monte na mão:

        Config(datajud_api_key="...", proxies=["http://user:senha@ip:porta"])
    """

    # ── Datajud (API pública do CNJ) ──────────────────────────────────────────
    datajud_api_key: str = ""
    # O Datajud costuma responder em segundos, mas em horário cheio passa de um
    # minuto (ele mesmo informa o tempo gasto no campo "took" da resposta). Por
    # isso a espera padrão é generosa. Em tela, onde alguém está esperando, passe
    # um tempo curto: `consultar_processo(..., timeout=12)` cai logo no diário.
    datajud_timeout: float = 90.0
    datajud_timeout_conexao: float = 10.0
    # O Datajud limita requisições seguidas e devolve HTTP 429. Vale esperar e
    # tentar de novo: costuma liberar em poucos segundos.
    datajud_tentativas: int = 3
    datajud_espera_retry: float = 3.0

    # ── Comunica / DJEN (API pública do CNJ) ──────────────────────────────────
    comunica_timeout: float = 12.0
    comunica_tamanho_pagina: int = 100

    # ── Proxies (opcional) ────────────────────────────────────────────────────
    # A API do Comunica é do gov.br e costuma recusar requisições vindas de fora
    # do Brasil. Rodando de um IP brasileiro, não é preciso proxy nenhum.
    proxies: list[str] = field(default_factory=list)
    # Gateway residencial que abre uma porta por sessão/IP (host:porta inicial + quantidade)
    gateway_host: str = ""
    gateway_login: str = ""
    gateway_senha: str = ""
    gateway_porta_inicial: int = 10000
    gateway_portas: int = 0
    # Provedor com API própria de listagem (opcional)
    proxyseller_api_key: str = ""
    # Quantos proxies disparar em paralelo por tentativa e teto de proxies testados.
    # Cada porta do gateway é um IP diferente e parte deles fica lenta; disparar
    # algumas ao mesmo tempo e ficar com a primeira resposta evita travar em um ruim.
    proxies_em_paralelo: int = 4
    proxies_max_tentativas: int = 16
    proxy_pool_ttl: int = 15 * 60

    # ── Educação com as fontes ────────────────────────────────────────────────
    user_agent_extra: str = ""      # acrescente contato/identificação, se quiser
    pausa_entre_paginas: float = 0.0

    @classmethod
    def do_ambiente(cls) -> Config:
        proxies_raw = _env("CONSULTA_PROXIES")
        separados = proxies_raw.replace(";", ",").replace("\n", ",").split(",")
        proxies = [p.strip() for p in separados if p.strip()]
        return cls(
            datajud_api_key=_env("DATAJUD_API_KEY"),
            datajud_timeout=_env_float("DATAJUD_TIMEOUT", 90.0),
            datajud_tentativas=_env_int("DATAJUD_TENTATIVAS", 3),
            comunica_timeout=_env_float("COMUNICA_TIMEOUT", 12.0),
            comunica_tamanho_pagina=_env_int("COMUNICA_TAMANHO_PAGINA", 100),
            proxies=proxies,
            gateway_host=_env("CONSULTA_GATEWAY_HOST"),
            gateway_login=_env("CONSULTA_GATEWAY_LOGIN"),
            gateway_senha=_env("CONSULTA_GATEWAY_SENHA"),
            gateway_porta_inicial=_env_int("CONSULTA_GATEWAY_PORTA_INICIAL", 10000),
            gateway_portas=_env_int("CONSULTA_GATEWAY_PORTAS", 0),
            proxyseller_api_key=_env("PROXYSELLER_API_KEY"),
            proxies_em_paralelo=_env_int("CONSULTA_PROXIES_PARALELO", 4),
            proxies_max_tentativas=_env_int("CONSULTA_PROXIES_MAX", 16),
            user_agent_extra=_env("CONSULTA_USER_AGENT_EXTRA"),
            pausa_entre_paginas=_env_float("CONSULTA_PAUSA_PAGINAS", 0.0),
        )

    @property
    def usa_proxy(self) -> bool:
        return bool(self.proxies or (self.gateway_host and self.gateway_login) or self.proxyseller_api_key)


_padrao: Config | None = None


def config_padrao() -> Config:
    """Configuração lida do ambiente uma única vez."""
    global _padrao
    if _padrao is None:
        _padrao = Config.do_ambiente()
    return _padrao


def definir_config(config: Config) -> None:
    """Troca a configuração usada por quem não passa `config=` explicitamente."""
    global _padrao
    _padrao = config
