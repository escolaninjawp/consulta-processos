"""Leitura da resposta do Datajud. Dados fictícios, sem acessar a rede."""
from consulta_processos import CNJ, Fonte, Polo, TipoMovimentacao
from consulta_processos.fontes.datajud import classificar_tipo, montar_processo

RESPOSTA = {
    "numeroProcesso": "10002542020258130079",
    "tribunal": "TJMG",
    "grau": "G1",
    "classe": {"codigo": 436, "nome": "Procedimento Comum Cível"},
    "assuntos": [{"codigo": 10375, "nome": "Indenização por Dano Moral"}],
    "orgaoJulgador": {"nome": "2ª Vara Cível da Comarca de Contagem"},
    "valorCausa": "15000.50",
    "dataAjuizamento": "2025-02-10T09:00:00.000Z",
    "partes": [
        {"nome": "CLIENTE EXEMPLO", "polo": "ATIVO",
         "advogados": [{"nome": "ADVOGADA EXEMPLO", "numero": "123456", "uf": "MG"}]},
        {"nome": "EMPRESA EXEMPLO S.A.", "polo": "PASSIVO", "advogados": []},
    ],
    "movimentos": [
        {"codigo": 26, "nome": "Distribuição", "dataHora": "2025-02-10T09:05:00.000Z"},
        {"codigo": 193, "nome": "Sentença de procedência", "dataHora": "2025-08-01T14:30:00.000Z",
         "complementosTabelados": [{"nome": "tipo_de_sentença", "descricao": "com resolução do mérito"}]},
        {"codigo": 0, "nome": "Ato ordinatório praticado", "dataHora": "2025-09-01T10:00:00.000Z"},
    ],
}


def test_monta_o_processo_com_os_metadados():
    processo = montar_processo(RESPOSTA, CNJ("1000254-20.2025.8.13.0079"))
    assert processo.tribunal == "TJMG"
    assert processo.classe == "Procedimento Comum Cível"
    assert processo.assunto == "Indenização por Dano Moral"
    assert processo.comarca == "Contagem"          # extraída do nome do órgão
    assert processo.valor_causa == 15000.50
    assert processo.fontes == [Fonte.DATAJUD]


def test_separa_os_polos_e_os_advogados():
    processo = montar_processo(RESPOSTA, CNJ("1000254-20.2025.8.13.0079"))
    assert processo.polo_ativo == ["CLIENTE EXEMPLO"]
    assert processo.polo_passivo == ["EMPRESA EXEMPLO S.A."]
    assert processo.partes[0].polo == Polo.ATIVO
    assert processo.advogados[0].oab_uf == "MG"
    assert processo.titulo == "CLIENTE EXEMPLO × EMPRESA EXEMPLO S.A."


def test_movimentacoes_vem_da_mais_nova_para_a_mais_antiga():
    processo = montar_processo(RESPOSTA, CNJ("1000254-20.2025.8.13.0079"))
    datas = [m.data.date().isoformat() for m in processo.movimentacoes]
    assert datas == sorted(datas, reverse=True)
    assert processo.data_ultima_movimentacao.isoformat() == "2025-09-01"


def test_cada_movimentacao_tem_identificador_estavel():
    processo = montar_processo(RESPOSTA, CNJ("1000254-20.2025.8.13.0079"))
    ids = [m.id_externo for m in processo.movimentacoes]
    assert len(ids) == len(set(ids))                       # não duplica
    # O id junta código, data e um resumo da descrição
    sem_codigo = next(m for m in processo.movimentacoes if m.descricao.startswith("Ato ordinatório"))
    assert sem_codigo.id_externo.startswith("0_2025-09-01T10:00:00_")
    # Rodar de novo dá exatamente o mesmo id (é o que evita duplicar na segunda consulta)
    de_novo = montar_processo(RESPOSTA, CNJ("1000254-20.2025.8.13.0079"))
    assert [m.id_externo for m in de_novo.movimentacoes] == ids


def test_classifica_o_tipo_pela_descricao():
    assert classificar_tipo("Sentença de procedência") == TipoMovimentacao.SENTENCA
    assert classificar_tipo("Decisão interlocutória") == TipoMovimentacao.DECISAO
    assert classificar_tipo("Despacho de mero expediente") == TipoMovimentacao.DESPACHO
    assert classificar_tipo("Audiência de conciliação designada") == TipoMovimentacao.AUDIENCIA
    assert classificar_tipo("Conclusos para decisão") == TipoMovimentacao.DECISAO
    assert classificar_tipo("Remessa ao arquivo") == TipoMovimentacao.OUTRO


def test_guarda_o_complemento_do_movimento():
    processo = montar_processo(RESPOSTA, CNJ("1000254-20.2025.8.13.0079"))
    sentenca = next(m for m in processo.movimentacoes if m.tipo == TipoMovimentacao.SENTENCA)
    assert "com resolução do mérito" in sentenca.complemento


def test_to_dict_vira_json():
    import json
    processo = montar_processo(RESPOSTA, CNJ("1000254-20.2025.8.13.0079"))
    texto = json.dumps(processo.to_dict(), ensure_ascii=False)
    assert "CLIENTE EXEMPLO" in texto
    assert '"fonte": "datajud"' in texto


def test_dois_atos_no_mesmo_segundo_nao_perdem_o_identificador():
    """O tribunal registra duas juntadas no mesmo segundo — as duas têm de sobreviver."""
    resposta = {**RESPOSTA, "movimentos": [
        {"codigo": 51, "nome": "Juntada de petição", "dataHora": "2025-03-01T11:00:00.000Z"},
        {"codigo": 51, "nome": "Juntada de petição", "dataHora": "2025-03-01T11:00:00.000Z"},
        {"codigo": 51, "nome": "Juntada de documento", "dataHora": "2025-03-01T11:00:00.000Z"},
    ]}
    processo = montar_processo(resposta, CNJ("1000254-20.2025.8.13.0079"))
    ids = [m.id_externo for m in processo.movimentacoes]
    assert len(processo.movimentacoes) == 3      # nenhuma se perde
    assert len(set(ids)) == 3                    # e cada uma tem id próprio
