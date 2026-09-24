"""consulta-processos — busca e consulta de processos judiciais nas fontes públicas.

    from consulta_processos import consultar_processo

    processo = consultar_processo("1000254-20.2025.8.13.0079")
    print(processo.titulo)

Fontes: Datajud e Comunica/DJEN, ambas APIs públicas do CNJ.
"""
from .api import buscar_por_oab, consultar_processo, existe, publicacoes_por_oab
from .cnj import CNJ
from .config import Config, config_padrao, definir_config
from .erros import ChaveAusente, ConsultaError, FonteIndisponivel, NumeroInvalido
from .modelos import Advogado, Fonte, Movimentacao, Parte, Polo, Processo, Publicacao, TipoMovimentacao

__version__ = "0.1.0"

__all__ = [
    "CNJ",
    "Advogado",
    "ChaveAusente",
    "Config",
    "ConsultaError",
    "Fonte",
    "FonteIndisponivel",
    "Movimentacao",
    "NumeroInvalido",
    "Parte",
    "Polo",
    "Processo",
    "Publicacao",
    "TipoMovimentacao",
    "__version__",
    "buscar_por_oab",
    "config_padrao",
    "consultar_processo",
    "definir_config",
    "existe",
    "publicacoes_por_oab",
]
