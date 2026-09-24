"""A tela do navegador: serve a página e responde as consultas em JSON. Sem rede."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import pytest

from consulta_processos import web
from consulta_processos.config import Config
from consulta_processos.erros import NumeroInvalido
from consulta_processos.modelos import Processo


@pytest.fixture
def endereco():
    """Sobe o servidor numa porta livre e devolve o endereço base."""
    web._Handler.config = Config()
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), web._Handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{servidor.server_address[1]}"
    servidor.shutdown()
    servidor.server_close()


def _post(endereco, caminho, corpo):
    pedido = urllib.request.Request(
        endereco + caminho, data=json.dumps(corpo).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(pedido, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def test_pagina_abre(endereco):
    with urllib.request.urlopen(endereco + "/", timeout=10) as r:
        pagina = r.read().decode("utf-8")
    assert r.status == 200
    assert "<title>Consulta de Processos</title>" in pagina
    # a página tem de bastar sozinha: nada de buscar script ou estilo na internet
    assert "http://" not in pagina.split("<script>")[0].replace("http://localhost", "")


def test_consulta_devolve_o_processo(endereco):
    processo = Processo(numero="1234567-89.2025.8.13.0001", tribunal="TJMG", classe="Execução")
    with patch("consulta_processos.web.consultar_processo", return_value=processo):
        status, corpo = _post(endereco, "/api/processo", {"numero": processo.numero})
    assert status == 200
    assert corpo["ok"] is True
    assert corpo["dado"]["tribunal"] == "TJMG"


def test_processo_inexistente_vira_resposta_vazia(endereco):
    with patch("consulta_processos.web.consultar_processo", return_value=None):
        _status, corpo = _post(endereco, "/api/processo", {"numero": "1234567-89.2025.8.13.0001"})
    assert corpo["ok"] is True
    assert corpo["dado"] is None


def test_numero_invalido_vira_recado_legivel(endereco):
    with patch("consulta_processos.web.consultar_processo",
               side_effect=NumeroInvalido("Número fora do padrão CNJ: 123")):
        _status, corpo = _post(endereco, "/api/processo", {"numero": "123"})
    assert corpo["ok"] is False
    assert "padrão CNJ" in corpo["erro"]


def test_falha_inesperada_nao_vaza_detalhe_tecnico(endereco):
    with patch("consulta_processos.web.consultar_processo", side_effect=RuntimeError("boom")):
        status, corpo = _post(endereco, "/api/processo", {"numero": "1234567-89.2025.8.13.0001"})
    assert status == 500
    assert corpo["ok"] is False
    assert "boom" not in corpo["erro"]


def test_endereco_desconhecido(endereco):
    status, corpo = _post(endereco, "/api/inexistente", {})
    assert status == 404
    assert corpo["ok"] is False
