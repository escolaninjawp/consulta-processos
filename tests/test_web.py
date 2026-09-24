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
    # A página tem de bastar sozinha: em auditório com rede ruim, um script ou uma
    # fonte vindos de CDN deixam a tela quebrada ou em branco.
    assert "<script src=" not in pagina
    assert "<link rel=\"stylesheet\"" not in pagina
    assert "@import" not in pagina


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


def test_configuracao_informa_o_estado_atual(endereco):
    from consulta_processos.config import CHAVE_PUBLICA_DATAJUD
    web._Handler.config = Config(datajud_api_key=CHAVE_PUBLICA_DATAJUD)
    import urllib.request as req
    with req.urlopen(endereco + "/api/configuracao", timeout=10) as r:
        corpo = json.loads(r.read().decode("utf-8"))
    assert corpo["ok"] is True
    assert corpo["dado"]["chave_definida"] is True
    assert corpo["dado"]["chave_e_a_publica"] is True


def test_configuracao_grava_no_env_e_passa_a_valer(endereco, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(web, "ARQUIVO_ENV", None)
    status, corpo = _post(endereco, "/api/configuracao", {
        "datajud_api_key": "minha-chave",
        "proxies": "http://usuario:senha@host:8080\n# comentário\n\nsocks5h://outro:9090",
    })
    assert status == 200 and corpo["ok"] is True
    assert corpo["dado"]["proxies"] == 2          # o comentário e a linha vazia saem

    escrito = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "DATAJUD_API_KEY=minha-chave" in escrito
    assert "socks5h://outro:9090" in escrito
    # e já vale sem reiniciar
    assert web._Handler.config.datajud_api_key == "minha-chave"
    assert len(web._Handler.config.proxies) == 2


def test_a_chave_nao_volta_para_a_tela(endereco):
    web._Handler.config = Config(datajud_api_key="segredo-que-nao-pode-vazar")
    import urllib.request as req
    with req.urlopen(endereco + "/api/configuracao", timeout=10) as r:
        corpo = r.read().decode("utf-8")
    assert "segredo-que-nao-pode-vazar" not in corpo
