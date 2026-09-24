"""Erros da biblioteca."""


class ConsultaError(Exception):
    """Erro genérico da consulta."""


class NumeroInvalido(ConsultaError):
    """O número informado não é um número de processo no padrão CNJ."""


class FonteIndisponivel(ConsultaError):
    """A fonte (Datajud/Comunica) não respondeu ou recusou a consulta.

    Diferente de "processo não encontrado": aqui vale tentar de novo mais tarde.
    """

    def __init__(self, fonte: str, detalhe: str = "", status: int | None = None):
        self.fonte = fonte
        self.status = status
        super().__init__(f"{fonte} indisponível{f' (HTTP {status})' if status else ''}"
                         f"{f': {detalhe}' if detalhe else ''}")


class ChaveAusente(ConsultaError):
    """Falta a chave de API da fonte (ex.: Datajud)."""
