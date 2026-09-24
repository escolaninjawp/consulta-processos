"""Datajud — API pública do CNJ.

https://datajud-wiki.cnj.jus.br/api-publica/

Traz os metadados do processo (classe, assunto, órgão julgador, valor, partes) e
todos os movimentos internos, inclusive os que não saem no diário (conclusão,
remessa, baixa). É a fonte mais completa do histórico, porém demora alguns dias
para indexar o que acabou de acontecer.

A chave de API é pública e está na documentação do CNJ; mesmo assim ela não fica
no código: informe em `DATAJUD_API_KEY`.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import datetime
from datetime import timezone as dt_timezone

from ..cnj import CNJ, todos_os_tribunais
from ..config import Config, config_padrao
from ..erros import ChaveAusente, FonteIndisponivel, NumeroInvalido
from ..http import Cliente
from ..modelos import Advogado, Fonte, Movimentacao, Parte, Polo, Processo, TipoMovimentacao

logger = logging.getLogger(__name__)

URL_BASE = "https://api-publica.datajud.cnj.jus.br"


def _cabecalhos(cfg: Config) -> dict:
    if not cfg.datajud_api_key:
        raise ChaveAusente(
            "Defina DATAJUD_API_KEY. A chave pública está na documentação do CNJ: "
            "https://datajud-wiki.cnj.jus.br/api-publica/acesso"
        )
    return {"Authorization": f"ApiKey {cfg.datajud_api_key}", "Content-Type": "application/json"}


def classificar_tipo(descricao: str) -> TipoMovimentacao:
    """Classifica o andamento pela descrição."""
    d = (descricao or "").lower()
    if "sentença" in d or "sentenca" in d:
        return TipoMovimentacao.SENTENCA
    if "decisão" in d or "decisao" in d:
        return TipoMovimentacao.DECISAO
    if "despacho" in d:
        return TipoMovimentacao.DESPACHO
    if "audiência" in d or "audiencia" in d:
        return TipoMovimentacao.AUDIENCIA
    if "intimação" in d or "intimacao" in d:
        return TipoMovimentacao.INTIMACAO
    if "diário" in d or "publicação" in d or "djen" in d:
        return TipoMovimentacao.PUBLICACAO_DJE
    return TipoMovimentacao.OUTRO


def _consultar(indice: str, payload: dict, cfg: Config, cliente: Cliente,
               timeout: float | None = None) -> dict:
    """Consulta um índice do Datajud, insistindo quando a API pede calma.

    O Datajud limita requisições seguidas (HTTP 429) e, em horário cheio,
    demora ou devolve erro de servidor. Nesses casos vale esperar e repetir —
    é diferente de "chave recusada" ou "processo não existe", que não adianta
    insistir.
    """
    url = f"{URL_BASE}/{indice}/_search"
    cabecalhos = _cabecalhos(cfg)
    espera = cfg.datajud_espera_retry
    ultima = None

    for tentativa in range(1, max(1, cfg.datajud_tentativas) + 1):
        resposta = cliente.post_json(url, payload, cabecalhos,
                                     timeout or cfg.datajud_timeout, cfg.datajud_timeout_conexao)
        if resposta.status == 200:
            return resposta.json()
        if resposta.status in (401, 403):
            raise FonteIndisponivel("Datajud", "chave de API recusada", resposta.status)
        if resposta.status not in (429, 504) and resposta.status < 500:
            raise FonteIndisponivel("Datajud", status=resposta.status)

        ultima = resposta
        if tentativa < cfg.datajud_tentativas:
            pausa = resposta.esperar_segundos or espera
            motivo = "limite de requisições" if resposta.status == 429 else f"HTTP {resposta.status}"
            logger.info("[datajud] %s — esperando %.0fs e tentando de novo (%d/%d)",
                        motivo, pausa, tentativa, cfg.datajud_tentativas)
            time.sleep(pausa)
            espera *= 2                       # cada nova espera é o dobro da anterior

    raise FonteIndisponivel("Datajud", "não respondeu depois de várias tentativas",
                            ultima.status if ultima else None)


# ── leitura da resposta ──────────────────────────────────────────────────────

def _movimentos(bruto: list[dict]) -> list[Movimentacao]:
    movimentacoes = []
    for mov in bruto or []:
        data_str = mov.get("dataHora") or ""
        descricao = mov.get("nome") or mov.get("descricao") or ""
        if not data_str or not descricao:
            continue
        try:
            quando = datetime.fromisoformat(data_str.replace("Z", "+00:00"))
        except ValueError:
            continue
        if quando.tzinfo is None:                      # algumas bases devolvem sem fuso
            quando = quando.replace(tzinfo=dt_timezone.utc)
        codigo = str(mov.get("codigo", "0"))
        if codigo == "0":
            # Sem código: usa data + resumo da descrição para não duplicar o mesmo ato
            resumo = hashlib.md5(descricao[:100].encode()).hexdigest()[:8]
            id_externo = f"s_{data_str[:10]}_{resumo}"
        else:
            id_externo = f"{codigo}_{data_str[:19]}"
        complementos = [
            f"{c.get('nome', '')}: {c.get('descricao', '')}".strip(": ")
            for c in mov.get("complementosTabelados") or []
        ]
        movimentacoes.append(Movimentacao(
            data=quando,
            descricao=descricao[:2000],
            tipo=classificar_tipo(descricao),
            fonte=Fonte.DATAJUD,
            id_externo=id_externo,
            complemento="; ".join(c for c in complementos if c),
        ))
    movimentacoes.sort(key=lambda m: m.data, reverse=True)
    return movimentacoes


def _partes(bruto: list[dict]) -> list[Parte]:
    mapa = {"ATIVO": Polo.ATIVO, "PASSIVO": Polo.PASSIVO}
    partes = []
    for p in bruto or []:
        nome = (p.get("nome") or "").strip()
        if not nome:
            continue
        advogados = [
            Advogado(nome=(a.get("nome") or "").strip(),
                     oab_numero=str(a.get("numero") or a.get("oab") or "").strip(),
                     oab_uf=(a.get("uf") or "").strip().upper())
            for a in p.get("advogados") or [] if (a.get("nome") or "").strip()
        ]
        partes.append(Parte(nome=nome, polo=mapa.get(p.get("polo", ""), Polo.TERCEIRO),
                            advogados=advogados))
    return partes


def montar_processo(dados: dict, numero: CNJ) -> Processo:
    """Converte a resposta crua do Datajud no nosso `Processo`."""
    partes = _partes(dados.get("partes"))
    orgao = (dados.get("orgaoJulgador") or {}).get("nome", "")
    comarca = dados.get("municipioInicioFormatado") or ""
    if not comarca and orgao:
        achado = re.search(r"da Comarca de (.+?)$", orgao, re.IGNORECASE)
        if achado:
            comarca = achado.group(1).strip()

    assuntos = dados.get("assuntos") or dados.get("assunto") or []
    ajuizamento = None
    if dados.get("dataAjuizamento"):
        try:
            ajuizamento = datetime.fromisoformat(dados["dataAjuizamento"].replace("Z", "+00:00"))
        except ValueError:
            ajuizamento = None
    try:
        valor = float(dados["valorCausa"]) if dados.get("valorCausa") else None
    except (TypeError, ValueError):
        valor = None

    movimentacoes = _movimentos(dados.get("movimentos"))
    return Processo(
        numero=numero.formatado,
        tribunal=dados.get("tribunal") or numero.tribunal,
        segmento=numero.nome_segmento,
        grau=dados.get("grau") or "",
        classe=(dados.get("classe") or {}).get("nome", ""),
        assunto=(assuntos[0].get("nome", "") if isinstance(assuntos, list) and assuntos else ""),
        orgao_julgador=orgao,
        comarca=comarca,
        valor_causa=valor,
        data_ajuizamento=ajuizamento,
        data_ultima_movimentacao=movimentacoes[0].data.date() if movimentacoes else None,
        partes=partes,
        advogados=[a for p in partes for a in p.advogados],
        movimentacoes=movimentacoes,
        fontes=[Fonte.DATAJUD],
    )


# ── consultas ────────────────────────────────────────────────────────────────

def consultar_processo(numero: str, *, config: Config | None = None,
                       cliente: Cliente | None = None,
                       timeout: float | None = None) -> Processo | None:
    """Consulta um processo pelo número. Devolve None quando não existe na base.

    O próprio número diz o tribunal, então a consulta vai direto ao índice certo
    (nada de varrer os 90 tribunais).
    """
    cfg = config or config_padrao()
    cliente = cliente or Cliente(cfg)
    cnj = CNJ(numero)
    if not cnj.valido:
        raise NumeroInvalido(f"Número fora do padrão CNJ: {numero}")

    dados = _consultar(cnj.indice_datajud,
                       {"size": 1, "query": {"match": {"numeroProcesso": cnj.digitos}}},
                       cfg, cliente, timeout)
    hits = (dados.get("hits") or {}).get("hits") or []
    if not hits:
        return None
    return montar_processo(hits[0].get("_source") or {}, cnj)


def buscar_por_oab(oab_numero: str, oab_uf: str, *, tribunal: str = "",
                   limite_por_tribunal: int = 100, config: Config | None = None,
                   cliente: Cliente | None = None) -> list[Processo]:
    """Processos em que a OAB informada aparece como advogado.

    Sem `tribunal`, varre todos os índices — são dezenas de consultas, leva minutos.
    Informe o tribunal (ex.: "TJMG") sempre que souber onde procurar.
    """
    cfg = config or config_padrao()
    cliente = cliente or Cliente(cfg)
    alvos = [tribunal.upper()] if tribunal else todos_os_tribunais()
    payload = {
        "size": limite_por_tribunal,
        "query": {"bool": {"must": [
            {"match": {"advogados.oab": re.sub(r"\D", "", oab_numero)}},
            {"match": {"advogados.uf": oab_uf.upper()}},
        ]}},
    }

    encontrados: list[Processo] = []
    for sigla in alvos:
        try:
            dados = _consultar(f"api_publica_{sigla.lower()}", payload, cfg, cliente)
        except FonteIndisponivel as e:
            logger.warning("[datajud] %s indisponível: %s", sigla, e)
            continue
        for hit in (dados.get("hits") or {}).get("hits") or []:
            fonte = hit.get("_source") or {}
            numero = CNJ(fonte.get("numeroProcesso") or "")
            if numero.valido:
                encontrados.append(montar_processo(fonte, numero))
    return encontrados
