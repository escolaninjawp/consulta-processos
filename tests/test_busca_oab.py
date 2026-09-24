"""Busca por OAB: vem do diário, agrupada por processo. Sem rede.

A API pública do Datajud não publica os advogados do processo — os documentos dela
só têm classe, assunto, órgão, datas e movimentos. Por isso a busca por advogado
passa pelo DJEN.
"""
from datetime import date
from unittest.mock import patch

from consulta_processos.api import buscar_por_oab
from consulta_processos.modelos import Publicacao


def _pub(numero, dia, texto="Intimação"):
    return Publicacao(
        id_externo=f"{numero}-{dia}",
        data_disponibilizacao=date(2026, 9, dia),
        numero_processo=numero,
        tipo_comunicacao=texto,
    )


PUBLICACOES = [
    _pub("5010754-07.2024.8.13.0625", 10),   # TJMG
    _pub("5010754-07.2024.8.13.0625", 15),   # mesmo processo, outra publicação
    _pub("4000180-71.2026.8.26.0604", 12),   # TJSP
    _pub("não é número de processo", 13),    # lixo: tem de ser descartado
]


def _buscar(**kwargs):
    with patch("consulta_processos.fontes.comunica.publicacoes_por_oab",
               return_value=PUBLICACOES) as chamada:
        return buscar_por_oab("123456", "mg", **kwargs), chamada


def test_agrupa_publicacoes_no_mesmo_processo():
    processos, _ = _buscar()
    numeros = {p.numero for p in processos}
    assert numeros == {"5010754-07.2024.8.13.0625", "4000180-71.2026.8.26.0604"}
    tjmg = next(p for p in processos if p.tribunal == "TJMG")
    assert len(tjmg.publicacoes) == 2


def test_descarta_numero_invalido():
    processos, _ = _buscar()
    assert len(processos) == 2


def test_filtra_por_tribunal():
    processos, _ = _buscar(tribunal="tjsp")
    assert [p.numero for p in processos] == ["4000180-71.2026.8.26.0604"]


def test_ordena_do_mais_recente_para_o_mais_antigo():
    processos, _ = _buscar()
    datas = [p.data_ultima_movimentacao for p in processos]
    assert datas == sorted(datas, reverse=True)


def test_periodo_chega_a_fonte():
    _processos, chamada = _buscar(dias=90)
    inicio = chamada.call_args.kwargs["inicio"]
    fim = chamada.call_args.kwargs["fim"]
    assert (fim - inicio).days == 90


def test_sem_publicacoes_devolve_lista_vazia():
    with patch("consulta_processos.fontes.comunica.publicacoes_por_oab", return_value=[]):
        assert buscar_por_oab("123456", "MG") == []
