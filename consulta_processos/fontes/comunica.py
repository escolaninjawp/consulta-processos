"""Comunica / DJEN — API pública de comunicações do CNJ.

https://comunicaapi.pje.jus.br/api/v1/comunicacao

É o Diário de Justiça Eletrônico Nacional: traz as intimações, despachos,
decisões e sentenças publicadas, com o teor completo do ato, as partes e os
advogados. Cobre os tribunais que publicam no DJEN, inclusive os que usam PJe,
eSAJ e eProc. Para o histórico interno do processo, use o Datajud.

Duas consultas: por número de processo e por OAB (todas as publicações de um
advogado num intervalo de datas).

Não exige chave de API. De um IP brasileiro funciona direto; de fora do país o
gov.br responde 403, e aí é preciso proxy (veja `proxies.py`).
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime
from html import unescape

from ..config import Config, config_padrao
from ..erros import FonteIndisponivel
from ..http import Cliente
from ..modelos import Advogado, Parte, Polo, Publicacao, TipoMovimentacao

logger = logging.getLogger(__name__)

URL_API = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
ORIGEM = "https://comunica.pje.jus.br"
REFERER = "https://comunica.pje.jus.br/"

_TIPOS = {
    "intimação": TipoMovimentacao.INTIMACAO,
    "intimacao": TipoMovimentacao.INTIMACAO,
    "despacho": TipoMovimentacao.DESPACHO,
    "decisão": TipoMovimentacao.DECISAO,
    "decisao": TipoMovimentacao.DECISAO,
    "sentença": TipoMovimentacao.SENTENCA,
    "sentenca": TipoMovimentacao.SENTENCA,
    "acórdão": TipoMovimentacao.SENTENCA,
    "acordao": TipoMovimentacao.SENTENCA,
    "edital": TipoMovimentacao.PUBLICACAO_DJE,
    "publicação": TipoMovimentacao.PUBLICACAO_DJE,
    "publicacao": TipoMovimentacao.PUBLICACAO_DJE,
}

_POLOS = {"A": Polo.ATIVO, "P": Polo.PASSIVO, "T": Polo.TERCEIRO}


def classificar_tipo(tipo_comunicacao: str) -> TipoMovimentacao:
    chave = (tipo_comunicacao or "").lower().strip()
    for termo, tipo in _TIPOS.items():
        if termo in chave:
            return tipo
    return TipoMovimentacao.OUTRO


# ── limpeza do HTML ──────────────────────────────────────────────────────────

def _sem_html(html: str) -> str:
    """Tira as tags e devolve o texto legível."""
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    texto = unescape(re.sub(r"<[^>]+>", " ", html))
    return re.sub(r"\s+", " ", texto).strip()


def extrair_teor(html: str) -> str:
    """Pega só o corpo do ato, sem o cabeçalho com partes e advogados.

    O HTML da publicação vem com um `divHeader` (partes/advogados) e um `divBody`
    (o ato em si). Para leitura e para IA, o que interessa é o corpo.
    """
    if not html:
        return ""
    corpo = re.search(r'<div[^>]+id=["\']divBody["\'][^>]*>(.*?)</div>', html,
                      flags=re.DOTALL | re.IGNORECASE)
    return _sem_html(corpo.group(1)).strip() if corpo else _sem_html(html)


def _data(item: dict) -> date | None:
    bruto = item.get("data_disponibilizacao") or item.get("datadisponibilizacao") or ""
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(bruto[:19], formato).date()
        except (ValueError, TypeError):
            continue
    return None


def montar_publicacao(item: dict) -> Publicacao:
    """Converte um item cru da API em `Publicacao`."""
    partes = [
        Parte(nome=(d.get("nome") or "").strip(),
              polo=_POLOS.get(d.get("polo", ""), Polo.TERCEIRO))
        for d in item.get("destinatarios") or [] if (d.get("nome") or "").strip()
    ]
    advogados = []
    for entrada in item.get("destinatarioadvogados") or []:
        adv = entrada.get("advogado") or {}
        nome = (adv.get("nome") or "").strip()
        if nome:
            advogados.append(Advogado(nome=nome,
                                      oab_numero=(adv.get("numero_oab") or "").strip(),
                                      oab_uf=(adv.get("uf_oab") or "").strip().upper()))
    return Publicacao(
        id_externo=str(item.get("id") or ""),
        data_disponibilizacao=_data(item),
        tipo_comunicacao=item.get("tipoComunicacao") or "",
        tipo_documento=item.get("tipoDocumento") or "",
        orgao=item.get("nomeOrgao") or "",
        numero_processo=item.get("numero_processo") or item.get("numeroprocessocommascara") or "",
        classe=item.get("nomeClasse") or "",
        texto=extrair_teor(item.get("texto") or ""),
        link=item.get("link") or "",
        partes=partes,
        advogados=advogados,
    )


# ── consultas ────────────────────────────────────────────────────────────────

def _buscar(params: dict, cfg: Config, cliente: Cliente) -> tuple[list[dict], int, bool]:
    """Devolve (itens, total, respondeu).

    `respondeu=False` quer dizer que a API não deu resposta definitiva (5xx, tempo
    esgotado, proxies esgotados): vale tentar de novo. Já uma resposta 200 com lista
    vazia significa que realmente não há publicação — não adianta insistir.
    """
    resposta = cliente.get(URL_API, params, timeout=cfg.comunica_timeout,
                           origem=ORIGEM, referer=REFERER)
    if resposta.ok:
        dados = resposta.json()
        return dados.get("items") or [], int(dados.get("count") or 0), True
    if resposta.status in (400, 404):
        return [], 0, True
    logger.warning("[comunica] resposta HTTP %s", resposta.status)
    return [], 0, False


def publicacoes_do_processo(numero: str, *, inicio: date | None = None,
                            fim: date | None = None, config: Config | None = None,
                            cliente: Cliente | None = None) -> list[Publicacao]:
    """Todas as publicações de um processo.

    A API indexa o número só com dígitos; o formatado fica como segunda tentativa.
    """
    cfg = config or config_padrao()
    cliente = cliente or Cliente(cfg)
    digitos = re.sub(r"\D", "", numero)
    inicio = inicio or date(2015, 1, 1)
    fim = fim or date.today()

    respondeu_alguma = False
    for tentativa in (digitos, numero):
        if not tentativa:
            continue
        itens, _, respondeu = _buscar({
            "numeroProcesso": tentativa,
            "dataDisponibilizacaoInicio": inicio.strftime("%Y-%m-%d"),
            "dataDisponibilizacaoFim": fim.strftime("%Y-%m-%d"),
            "tamanhoPagina": cfg.comunica_tamanho_pagina,
        }, cfg, cliente)
        respondeu_alguma = respondeu_alguma or respondeu
        if itens:
            return [montar_publicacao(i) for i in itens]
        if not respondeu:
            raise FonteIndisponivel("Comunica", "sem resposta definitiva")
    if not respondeu_alguma:
        raise FonteIndisponivel("Comunica", "sem resposta definitiva")
    return []


def publicacoes_por_oab(oab_numero: str, oab_uf: str, *, inicio: date | None = None,
                        fim: date | None = None, paginas: int = 1,
                        config: Config | None = None,
                        cliente: Cliente | None = None) -> list[Publicacao]:
    """Publicações de um advogado no período (o DJEN devolve 100 por página).

    `paginas=0` busca todas as páginas disponíveis.
    """
    cfg = config or config_padrao()
    cliente = cliente or Cliente(cfg)
    base = {
        "numeroOab": re.sub(r"\D", "", oab_numero),
        "ufOab": oab_uf.upper(),
        "tamanhoPagina": cfg.comunica_tamanho_pagina,
    }
    if inicio:
        base["dataDisponibilizacaoInicio"] = inicio.strftime("%Y-%m-%d")
    if fim:
        base["dataDisponibilizacaoFim"] = fim.strftime("%Y-%m-%d")

    todas: list[Publicacao] = []
    pagina = 1
    while True:
        itens, total, respondeu = _buscar({**base, "pagina": pagina}, cfg, cliente)
        if not respondeu and pagina == 1:
            raise FonteIndisponivel("Comunica", "sem resposta definitiva")
        todas.extend(montar_publicacao(i) for i in itens)
        vistas = pagina * cfg.comunica_tamanho_pagina
        acabou = (not itens) or vistas >= total
        if acabou or (paginas and pagina >= paginas):
            break
        pagina += 1
        if cfg.pausa_entre_paginas:
            time.sleep(cfg.pausa_entre_paginas)   # respeite o serviço público
    return todas
