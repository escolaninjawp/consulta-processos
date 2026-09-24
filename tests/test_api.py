"""Junção das duas fontes num processo só. Sem rede."""
from datetime import date

from consulta_processos import CNJ, Fonte, TipoMovimentacao
from consulta_processos.api import _juntar_publicacoes, _processo_das_publicacoes
from consulta_processos.fontes.comunica import montar_publicacao
from consulta_processos.fontes.datajud import montar_processo

from .test_comunica import ITEM
from .test_datajud import RESPOSTA

NUMERO = CNJ("1000254-20.2025.8.13.0079")


def test_so_com_publicacoes_monta_o_processo():
    """Processo recém-distribuído: o diário já publicou, o Datajud ainda não indexou."""
    processo = _processo_das_publicacoes(NUMERO, [montar_publicacao(ITEM)])
    assert processo.numero == "1000254-20.2025.8.13.0079"
    assert processo.tribunal == "TJMG"                 # veio do próprio número
    assert processo.fontes == [Fonte.COMUNICA]
    assert processo.titulo == "CLIENTE EXEMPLO × EMPRESA EXEMPLO S.A."
    assert processo.orgao_julgador == "2ª Vara Cível da Comarca de Exemplo"
    assert len(processo.movimentacoes) == 1


def test_junta_publicacoes_ao_historico_do_datajud():
    processo = montar_processo(RESPOSTA, NUMERO)
    movimentos_datajud = len(processo.movimentacoes)

    _juntar_publicacoes(processo, [montar_publicacao(ITEM)])

    assert set(processo.fontes) == {Fonte.DATAJUD, Fonte.COMUNICA}
    assert len(processo.movimentacoes) == movimentos_datajud + 1
    assert len(processo.publicacoes) == 1
    # A publicação é a mais recente, então passa a ser a primeira da lista
    assert processo.movimentacoes[0].fonte == Fonte.COMUNICA
    assert processo.data_ultima_movimentacao == date(2026, 9, 22)


def test_nao_duplica_ao_juntar_duas_vezes():
    processo = montar_processo(RESPOSTA, NUMERO)
    publicacao = montar_publicacao(ITEM)
    _juntar_publicacoes(processo, [publicacao])
    quantas = len(processo.movimentacoes)

    _juntar_publicacoes(processo, [publicacao])          # segunda consulta do mesmo processo

    assert len(processo.movimentacoes) == quantas
    ids = [m.id_externo for m in processo.movimentacoes]
    assert len(ids) == len(set(ids))


def test_publicacao_completa_partes_e_advogados_que_faltavam():
    processo = montar_processo(RESPOSTA, NUMERO)
    item = {**ITEM,
            "destinatarios": [{"nome": "TERCEIRO INTERESSADO", "polo": "T"}],
            "destinatarioadvogados": [
                {"advogado": {"nome": "OUTRO ADVOGADO", "numero_oab": "999", "uf_oab": "SP"}}]}

    _juntar_publicacoes(processo, [montar_publicacao(item)])

    assert "TERCEIRO INTERESSADO" in [p.nome for p in processo.partes]
    assert "OUTRO ADVOGADO" in [a.nome for a in processo.advogados]


def test_tipos_das_duas_fontes_convivem():
    processo = montar_processo(RESPOSTA, NUMERO)
    _juntar_publicacoes(processo, [montar_publicacao(ITEM)])
    tipos = {m.tipo for m in processo.movimentacoes}
    assert TipoMovimentacao.SENTENCA in tipos            # veio do Datajud
    assert TipoMovimentacao.INTIMACAO in tipos           # veio do diário
