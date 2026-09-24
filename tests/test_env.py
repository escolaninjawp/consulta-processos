"""O .env precisa ser lido sozinho: o README manda criar o arquivo, e quem instala
não vai definir variável de ambiente na mão. Sem rede."""
import os

import pytest

from consulta_processos import config as mod
from consulta_processos.config import CHAVE_PUBLICA_DATAJUD, Config, carregar_env


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    """Cada teste começa sem as variáveis e sem a marca de 'já carregado'."""
    for nome in ("DATAJUD_API_KEY", "CONSULTA_PROXIES", "DATAJUD_TIMEOUT", "UMA_QUALQUER"):
        monkeypatch.delenv(nome, raising=False)
    monkeypatch.setattr(mod, "_env_carregado", False)
    yield


def _escrever(pasta, conteudo):
    arquivo = pasta / ".env"
    arquivo.write_text(conteudo, encoding="utf-8")
    return arquivo


def test_le_o_arquivo_da_pasta_atual(tmp_path, monkeypatch):
    _escrever(tmp_path, "DATAJUD_API_KEY=abc123\n")
    monkeypatch.chdir(tmp_path)
    carregar_env()
    assert os.environ["DATAJUD_API_KEY"] == "abc123"


def test_config_do_ambiente_usa_o_arquivo(tmp_path, monkeypatch):
    """É o caminho real: instalar, preencher o .env e consultar."""
    _escrever(tmp_path, "DATAJUD_API_KEY=chave-do-arquivo\nDATAJUD_TIMEOUT=45\n")
    monkeypatch.chdir(tmp_path)
    cfg = Config.do_ambiente()
    assert cfg.datajud_api_key == "chave-do-arquivo"
    assert cfg.datajud_timeout == 45.0


def test_variavel_de_ambiente_tem_preferencia(tmp_path, monkeypatch):
    _escrever(tmp_path, "DATAJUD_API_KEY=do-arquivo\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATAJUD_API_KEY", "do-ambiente")
    carregar_env()
    assert os.environ["DATAJUD_API_KEY"] == "do-ambiente"


def test_encontra_o_arquivo_em_pasta_acima(tmp_path, monkeypatch):
    """Rodar de dentro de uma subpasta não pode quebrar a configuração."""
    _escrever(tmp_path, "DATAJUD_API_KEY=de-cima\n")
    subpasta = tmp_path / "exemplos" / "mais_fundo"
    subpasta.mkdir(parents=True)
    monkeypatch.chdir(subpasta)
    carregar_env()
    assert os.environ["DATAJUD_API_KEY"] == "de-cima"


def test_ignora_comentarios_aspas_e_export(tmp_path, monkeypatch):
    _escrever(tmp_path, '# comentário\n\nexport DATAJUD_API_KEY="com aspas"\n'
                        "UMA_QUALQUER='simples'\nlinha sem igual\n")
    monkeypatch.chdir(tmp_path)
    carregar_env()
    assert os.environ["DATAJUD_API_KEY"] == "com aspas"
    assert os.environ["UMA_QUALQUER"] == "simples"


def test_sem_arquivo_nao_quebra(tmp_path, monkeypatch):
    """Sem .env e sem variável, a biblioteca ainda consulta: usa a chave pública do CNJ."""
    monkeypatch.chdir(tmp_path)
    assert carregar_env() is None
    assert Config.do_ambiente().datajud_api_key == CHAVE_PUBLICA_DATAJUD


def test_chave_propria_substitui_a_publica(tmp_path, monkeypatch):
    _escrever(tmp_path, "DATAJUD_API_KEY=a-minha-chave\n")
    monkeypatch.chdir(tmp_path)
    assert Config.do_ambiente().datajud_api_key == "a-minha-chave"


def test_le_uma_vez_so(tmp_path, monkeypatch):
    """Ler a cada consulta seria desperdício; a releitura é sob pedido."""
    arquivo = _escrever(tmp_path, "DATAJUD_API_KEY=primeira\n")
    monkeypatch.chdir(tmp_path)
    carregar_env()
    arquivo.write_text("DATAJUD_API_KEY=segunda\n", encoding="utf-8")
    carregar_env()
    assert os.environ["DATAJUD_API_KEY"] == "primeira"
    monkeypatch.delenv("DATAJUD_API_KEY")
    carregar_env(forcar=True)
    assert os.environ["DATAJUD_API_KEY"] == "segunda"


def test_caminho_explicito(tmp_path, monkeypatch):
    outro = tmp_path / "config_de_producao"
    outro.mkdir()
    arquivo = outro / ".env"
    arquivo.write_text("DATAJUD_API_KEY=explicita\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert carregar_env(arquivo) == arquivo
    assert os.environ["DATAJUD_API_KEY"] == "explicita"
