from consulta_processos import CNJ


def test_aceita_com_e_sem_pontuacao():
    com = CNJ("1000254-20.2025.8.13.0079")
    sem = CNJ("10002542020258130079")
    assert com.valido and sem.valido
    assert com.formatado == sem.formatado == "1000254-20.2025.8.13.0079"
    assert com == sem
    assert sem.digitos == "10002542020258130079"


def test_le_os_campos_do_numero():
    cnj = CNJ("1000254-20.2025.8.13.0079")
    assert cnj.ano == 2025
    assert cnj.segmento == 8
    assert cnj.tribunal_codigo == 13
    assert cnj.origem_codigo == 79
    assert cnj.nome_segmento == "Justiça Estadual"


def test_descobre_o_tribunal_pelo_numero():
    assert CNJ("1000254-20.2025.8.13.0079").tribunal == "TJMG"     # estadual, MG
    assert CNJ("5001234-56.2024.4.06.3800").tribunal == "TRF6"     # federal, 6ª região
    assert CNJ("0010123-45.2023.5.03.0001").tribunal == "TRT3"     # trabalho, 3ª região
    assert CNJ("1234567-89.2024.3.00.0000").tribunal == "STJ"      # superior


def test_indice_do_datajud_vem_do_tribunal():
    assert CNJ("1000254-20.2025.8.13.0079").indice_datajud == "api_publica_tjmg"


def test_numero_invalido_nao_quebra():
    for entrada in ["", "abc", "123", "1000254-20.2025.8.13"]:
        cnj = CNJ(entrada)
        assert not cnj.valido
        assert cnj.tribunal.startswith(("SEG", "TJ", "CNJ")) or cnj.tribunal == "STF"
        assert cnj.ano == 0
