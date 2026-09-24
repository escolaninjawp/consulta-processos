"""Leitura das publicações do DJEN. Dados fictícios, sem acessar a rede."""
from datetime import date

from consulta_processos import Fonte, Polo, TipoMovimentacao
from consulta_processos.fontes.comunica import classificar_tipo, extrair_teor, montar_publicacao

ITEM = {
    "id": 987654,
    "data_disponibilizacao": "2026-09-22",
    "tipoComunicacao": "Intimação",
    "tipoDocumento": "Sentença",
    "nomeOrgao": "2ª Vara Cível da Comarca de Exemplo",
    "nomeClasse": "Procedimento Comum Cível",
    "numero_processo": "1000254-20.2025.8.13.0079",
    "link": "https://comunica.pje.jus.br/consulta/987654",
    "texto": (
        '<div id="divHeader"><p>CLIENTE EXEMPLO (Polo Ativo)</p>'
        '<p>Advogado: ADVOGADA EXEMPLO OAB/MG 123456</p></div>'
        '<div id="divBody"><style>.x{color:red}</style>'
        '<p>Fica a parte <b>intimada</b> para, no prazo de 15 dias, '
        'manifestar-se sobre a senten&ccedil;a.</p></div>'
    ),
    "destinatarios": [
        {"nome": "CLIENTE EXEMPLO", "polo": "A"},
        {"nome": "EMPRESA EXEMPLO S.A.", "polo": "P"},
    ],
    "destinatarioadvogados": [
        {"advogado": {"nome": "ADVOGADA EXEMPLO", "numero_oab": "123456", "uf_oab": "mg"}},
    ],
}


def test_le_os_campos_da_publicacao():
    pub = montar_publicacao(ITEM)
    assert pub.id_externo == "987654"
    assert pub.data_disponibilizacao == date(2026, 9, 22)
    assert pub.tipo_comunicacao == "Intimação"
    assert pub.tipo_documento == "Sentença"
    assert pub.classe == "Procedimento Comum Cível"


def test_texto_vem_limpo_e_so_com_o_ato():
    pub = montar_publicacao(ITEM)
    assert pub.texto.startswith("Fica a parte intimada")
    assert "sentença" in pub.texto           # entidade HTML foi decodificada
    assert "<" not in pub.texto              # sem tags
    assert "color:red" not in pub.texto      # sem CSS
    assert "Advogado:" not in pub.texto      # cabeçalho descartado


def test_fallback_quando_nao_ha_corpo_marcado():
    assert extrair_teor("<p>Ato <b>sem</b> divBody</p>") == "Ato sem divBody"
    assert extrair_teor("") == ""


def test_partes_e_advogados():
    pub = montar_publicacao(ITEM)
    assert [p.polo for p in pub.partes] == [Polo.ATIVO, Polo.PASSIVO]
    assert pub.advogados[0].oab_uf == "MG"   # normaliza a UF para maiúsculas
    assert str(pub.advogados[0]) == "ADVOGADA EXEMPLO (OAB MG 123456)"


def test_publicacao_vira_movimentacao_do_historico():
    mov = montar_publicacao(ITEM).como_movimentacao()
    assert mov.fonte == Fonte.COMUNICA
    assert mov.tipo == TipoMovimentacao.INTIMACAO
    assert mov.id_externo == "comunica-987654"     # prefixo evita bater com id do Datajud
    assert mov.data.date() == date(2026, 9, 22)
    assert "intimada" in mov.complemento


def test_classifica_o_tipo_da_comunicacao():
    assert classificar_tipo("Intimação") == TipoMovimentacao.INTIMACAO
    assert classificar_tipo("Despacho") == TipoMovimentacao.DESPACHO
    assert classificar_tipo("Acórdão") == TipoMovimentacao.SENTENCA
    assert classificar_tipo("Edital de citação") == TipoMovimentacao.PUBLICACAO_DJE
    assert classificar_tipo("Comunicação diversa") == TipoMovimentacao.OUTRO


def test_data_ausente_nao_quebra():
    pub = montar_publicacao({**ITEM, "data_disponibilizacao": ""})
    assert pub.data_disponibilizacao is None
    assert pub.como_movimentacao().data.date() == date.today()
