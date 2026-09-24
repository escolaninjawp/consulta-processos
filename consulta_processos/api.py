"""Funções de alto nível — é por aqui que a maioria dos usos começa.

    from consulta_processos import consultar_processo

    processo = consultar_processo("1000254-20.2025.8.13.0079")
    print(processo.titulo)
    for mov in processo.movimentacoes[:5]:
        print(mov)
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from .cnj import CNJ
from .config import Config, config_padrao
from .erros import ChaveAusente, FonteIndisponivel, NumeroInvalido
from .fontes import comunica, datajud
from .http import Cliente
from .modelos import Fonte, Parte, Polo, Processo, Publicacao

logger = logging.getLogger(__name__)


def consultar_processo(numero: str, *, com_publicacoes: bool = True,
                       config: Config | None = None) -> Processo | None:
    """Tudo o que as fontes públicas sabem sobre um processo.

    Junta as duas fontes, que se completam:
      • Datajud — metadados e o histórico interno (conclusão, remessa, baixa);
      • Comunica/DJEN — as publicações, com o teor de cada ato.

    Devolve None quando nenhuma das duas conhece o processo. Sem
    `DATAJUD_API_KEY` definida, consulta só o Comunica.
    """
    cfg = config or config_padrao()
    cliente = Cliente(cfg)
    cnj = CNJ(numero)
    if not cnj.valido:
        raise NumeroInvalido(f"Número fora do padrão CNJ: {numero}")

    processo: Processo | None = None
    try:
        processo = datajud.consultar_processo(cnj.formatado, config=cfg, cliente=cliente)
    except ChaveAusente:
        logger.info("[consulta] sem DATAJUD_API_KEY — usando apenas o Comunica")
    except FonteIndisponivel as e:
        logger.warning("[consulta] Datajud falhou: %s", e)

    publicacoes: list[Publicacao] = []
    if com_publicacoes:
        try:
            publicacoes = comunica.publicacoes_do_processo(cnj.formatado, config=cfg, cliente=cliente)
        except FonteIndisponivel as e:
            logger.warning("[consulta] Comunica falhou: %s", e)

    if processo is None and not publicacoes:
        return None

    if processo is None:
        processo = _processo_das_publicacoes(cnj, publicacoes)
    elif publicacoes:
        _juntar_publicacoes(processo, publicacoes)
    return processo


def _processo_das_publicacoes(cnj: CNJ, publicacoes: list[Publicacao]) -> Processo:
    """Monta o processo só com o que as publicações mostram.

    Acontece com processo recém-distribuído: o diário já publicou, mas o Datajud
    ainda não indexou.
    """
    recentes = sorted(publicacoes, key=lambda p: p.data_disponibilizacao or date.min, reverse=True)
    primeira = recentes[0]
    partes: dict[str, Parte] = {}
    advogados: dict[str, object] = {}
    for pub in recentes:
        for parte in pub.partes:
            if parte.nome not in partes or partes[parte.nome].polo == Polo.TERCEIRO:
                partes[parte.nome] = parte
        for adv in pub.advogados:
            advogados.setdefault(f"{adv.nome}|{adv.oab_uf}{adv.oab_numero}", adv)

    processo = Processo(
        numero=cnj.formatado,
        tribunal=cnj.tribunal,
        segmento=cnj.nome_segmento,
        classe=primeira.classe,
        orgao_julgador=primeira.orgao,
        data_ultima_movimentacao=primeira.data_disponibilizacao,
        partes=list(partes.values()),
        advogados=list(advogados.values()),  # type: ignore[arg-type]
        movimentacoes=[p.como_movimentacao() for p in recentes],
        publicacoes=recentes,
        fontes=[Fonte.COMUNICA],
    )
    return processo


def _juntar_publicacoes(processo: Processo, publicacoes: list[Publicacao]) -> None:
    """Acrescenta as publicações ao processo vindo do Datajud, sem duplicar."""
    processo.publicacoes = sorted(publicacoes,
                                  key=lambda p: p.data_disponibilizacao or date.min, reverse=True)
    if Fonte.COMUNICA not in processo.fontes:
        processo.fontes.append(Fonte.COMUNICA)

    ja_tem = {m.id_externo for m in processo.movimentacoes}
    novas = [p.como_movimentacao() for p in processo.publicacoes]
    processo.movimentacoes.extend(m for m in novas if m.id_externo not in ja_tem)
    processo.movimentacoes.sort(key=lambda m: m.data, reverse=True)

    # As publicações trazem partes e advogados que o Datajud nem sempre tem
    nomes = {p.nome for p in processo.partes}
    for pub in processo.publicacoes:
        for parte in pub.partes:
            if parte.nome not in nomes:
                nomes.add(parte.nome)
                processo.partes.append(parte)
    conhecidos = {f"{a.nome}|{a.oab_uf}{a.oab_numero}" for a in processo.advogados}
    for pub in processo.publicacoes:
        for adv in pub.advogados:
            chave = f"{adv.nome}|{adv.oab_uf}{adv.oab_numero}"
            if chave not in conhecidos:
                conhecidos.add(chave)
                processo.advogados.append(adv)

    if processo.movimentacoes:
        mais_recente = processo.movimentacoes[0].data.date()
        if not processo.data_ultima_movimentacao or mais_recente > processo.data_ultima_movimentacao:
            processo.data_ultima_movimentacao = mais_recente


def existe(numero: str, *, config: Config | None = None) -> tuple[bool, str]:
    """Só verifica se o processo já aparece em alguma fonte. Devolve (achou, fonte).

    Serve para fila de espera: você cadastra o número assim que o cliente contrata
    e fica tentando até o processo ser distribuído e indexado.
    """
    cfg = config or config_padrao()
    cliente = Cliente(cfg)
    try:
        # Datajud primeiro: é direto e rápido, sem proxy
        if datajud.consultar_processo(numero, config=cfg, cliente=cliente, timeout=12):
            return True, "datajud"
    except (ChaveAusente, FonteIndisponivel, NumeroInvalido) as e:
        logger.debug("[existe] Datajud: %s", e)
    try:
        if comunica.publicacoes_do_processo(numero, config=cfg, cliente=cliente):
            return True, "comunica"
    except FonteIndisponivel as e:
        logger.debug("[existe] Comunica: %s", e)
    return False, ""


def buscar_por_oab(oab_numero: str, oab_uf: str, *, tribunal: str = "", dias: int = 30,
                   paginas: int = 1, config: Config | None = None) -> list[Processo]:
    """Processos em que a OAB apareceu no diário, no período.

    Vai pelo DJEN, e não pelo Datajud: a API pública do Datajud não publica os
    advogados do processo — os documentos dela têm apenas classe, assunto, órgão,
    datas e movimentos. Procurar advogado lá devolve sempre vazio.

    A consequência é que este caminho enxerga o que foi publicado no período, não
    a carteira inteira do advogado. Aumente `dias` para alcançar mais.
    """
    cfg = config or config_padrao()
    cliente = Cliente(cfg)
    fim = date.today()
    publicacoes = comunica.publicacoes_por_oab(
        oab_numero, oab_uf, inicio=fim - timedelta(days=max(1, dias)), fim=fim,
        paginas=paginas, config=cfg, cliente=cliente)

    alvo = tribunal.strip().upper()
    agrupadas: dict[str, list[Publicacao]] = {}
    for publicacao in publicacoes:
        cnj = CNJ(publicacao.numero_processo or "")
        if not cnj.valido:
            continue
        if alvo and cnj.tribunal != alvo:
            continue
        agrupadas.setdefault(cnj.formatado, []).append(publicacao)

    processos = [_processo_das_publicacoes(CNJ(numero), lista)
                 for numero, lista in agrupadas.items()]
    processos.sort(key=lambda p: p.data_ultima_movimentacao or date.min, reverse=True)
    return processos


def publicacoes_por_oab(oab_numero: str, oab_uf: str, *, inicio: date | None = None,
                        fim: date | None = None, paginas: int = 1,
                        config: Config | None = None) -> list[Publicacao]:
    """Publicações de um advogado no período (é assim que se acompanha o diário)."""
    return comunica.publicacoes_por_oab(oab_numero, oab_uf, inicio=inicio, fim=fim,
                                        paginas=paginas, config=config)
