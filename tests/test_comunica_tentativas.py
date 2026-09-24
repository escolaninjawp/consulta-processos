"""O DJEN oscila: 5xx é instabilidade e vale insistir; lista vazia é resposta. Sem rede."""
from unittest.mock import patch

from consulta_processos.config import Config
from consulta_processos.fontes import comunica


class RespostaFalsa:
    def __init__(self, status, corpo=None, esperar=None):
        self.status = status
        self._corpo = corpo or {}
        self.esperar_segundos = esperar

    @property
    def ok(self):
        return self.status == 200

    def json(self):
        return self._corpo


def _rodar(sequencia, tentativas=3):
    """Executa _buscar contra uma sequência de respostas e devolve (resultado, nº de chamadas)."""
    chamadas = []

    def falso_get(self, *args, **kwargs):
        chamadas.append(1)
        return sequencia[min(len(chamadas) - 1, len(sequencia) - 1)]

    cfg = Config(comunica_tentativas=tentativas, comunica_espera_retry=0.001)
    with patch("consulta_processos.http.Cliente.get", falso_get):
        resultado = comunica._buscar({"pagina": 1}, cfg, comunica.Cliente(cfg))
    return resultado, len(chamadas)


def test_insiste_quando_o_djen_devolve_503():
    ok = RespostaFalsa(200, {"items": [{"id": 1}], "count": 1})
    (itens, total, respondeu), chamadas = _rodar([RespostaFalsa(503), RespostaFalsa(503), ok])
    assert chamadas == 3
    assert respondeu is True
    assert len(itens) == 1


def test_desiste_depois_do_limite():
    (itens, _total, respondeu), chamadas = _rodar([RespostaFalsa(503)], tentativas=3)
    assert chamadas == 3
    assert respondeu is False
    assert itens == []


def test_lista_vazia_nao_vira_insistencia():
    """200 com lista vazia significa que não há publicação — insistir só castiga o serviço."""
    vazio = RespostaFalsa(200, {"items": [], "count": 0})
    (itens, _total, respondeu), chamadas = _rodar([vazio])
    assert chamadas == 1
    assert respondeu is True
    assert itens == []


def test_404_e_resposta_definitiva():
    (_itens, _total, respondeu), chamadas = _rodar([RespostaFalsa(404)])
    assert chamadas == 1
    assert respondeu is True


def test_respeita_o_tempo_pedido_pela_fonte():
    """Quando a resposta diz quanto esperar, é esse tempo que vale."""
    ok = RespostaFalsa(200, {"items": [], "count": 0})
    with patch("consulta_processos.fontes.comunica.time.sleep") as dormiu:
        _rodar([RespostaFalsa(429, esperar=7.0), ok])
    dormiu.assert_called_once_with(7.0)
