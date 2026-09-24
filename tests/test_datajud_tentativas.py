"""O Datajud limita requisições seguidas (HTTP 429): a consulta espera e repete."""
import pytest

from consulta_processos import ChaveAusente, Config, FonteIndisponivel
from consulta_processos.fontes import datajud
from consulta_processos.http import Resposta

CONFIG = Config(datajud_api_key="chave-de-teste", datajud_tentativas=3, datajud_espera_retry=0.01)


class ClienteFalso:
    """Devolve as respostas combinadas, uma por chamada."""

    def __init__(self, *respostas: Resposta):
        self.respostas = list(respostas)
        self.chamadas = 0

    def post_json(self, url, payload, cabecalhos, timeout, timeout_conexao):
        self.chamadas += 1
        return self.respostas.pop(0) if self.respostas else Resposta(500)


@pytest.fixture(autouse=True)
def _sem_espera(monkeypatch):
    monkeypatch.setattr(datajud.time, "sleep", lambda _: None)


def test_repete_depois_do_429_e_devolve_o_resultado():
    cliente = ClienteFalso(Resposta(429, cabecalhos={"retry-after": "0"}),
                           Resposta(200, '{"hits": {"hits": []}}'))
    dados = datajud._consultar("api_publica_tjmg", {}, CONFIG, cliente)
    assert dados == {"hits": {"hits": []}}
    assert cliente.chamadas == 2


def test_repete_tambem_em_erro_de_servidor_e_tempo_esgotado():
    cliente = ClienteFalso(Resposta(503), Resposta(504), Resposta(200, "{}"))
    assert datajud._consultar("api_publica_tjmg", {}, CONFIG, cliente) == {}
    assert cliente.chamadas == 3


def test_desiste_depois_do_limite_de_tentativas():
    cliente = ClienteFalso(Resposta(429), Resposta(429), Resposta(429))
    with pytest.raises(FonteIndisponivel) as erro:
        datajud._consultar("api_publica_tjmg", {}, CONFIG, cliente)
    assert cliente.chamadas == 3
    assert erro.value.status == 429


def test_chave_recusada_nao_repete():
    cliente = ClienteFalso(Resposta(403), Resposta(200, "{}"))
    with pytest.raises(FonteIndisponivel) as erro:
        datajud._consultar("api_publica_tjmg", {}, CONFIG, cliente)
    assert cliente.chamadas == 1                 # não adianta insistir
    assert "chave" in str(erro.value)


def test_erro_do_pedido_nao_repete():
    cliente = ClienteFalso(Resposta(400), Resposta(200, "{}"))
    with pytest.raises(FonteIndisponivel):
        datajud._consultar("api_publica_tjmg", {}, CONFIG, cliente)
    assert cliente.chamadas == 1


def test_sem_chave_avisa_onde_conseguir():
    with pytest.raises(ChaveAusente) as erro:
        datajud._consultar("api_publica_tjmg", {}, Config(), ClienteFalso(Resposta(200, "{}")))
    assert "DATAJUD_API_KEY" in str(erro.value)
    assert "cnj.jus.br" in str(erro.value)


def test_retry_after_manda_no_tempo_de_espera(monkeypatch):
    esperas = []
    monkeypatch.setattr(datajud.time, "sleep", esperas.append)
    cliente = ClienteFalso(Resposta(429, cabecalhos={"retry-after": "7"}), Resposta(200, "{}"))
    datajud._consultar("api_publica_tjmg", {}, CONFIG, cliente)
    assert esperas == [7.0]                      # obedece o que a API pediu
