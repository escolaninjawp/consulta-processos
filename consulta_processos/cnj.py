"""Número único do processo (padrão CNJ, Resolução 65/2008).

Formato: NNNNNNN-DD.AAAA.J.TR.OOOO

    1000254-20.2025.8.13.0079
    │       │  │    │ │  └── OOOO  unidade de origem (comarca/vara/subseção)
    │       │  │    │ └───── TR    tribunal dentro do segmento
    │       │  │    └─────── J     segmento da justiça (8 = estadual)
    │       │  └──────────── AAAA  ano do ajuizamento
    │       └─────────────── DD    dígito verificador
    └─────────────────────── NNNNNNN  sequencial por unidade/ano

Os dois campos do meio (J e TR) dizem qual tribunal julga o processo, e é isso
que permite consultar direto o índice certo do Datajud, sem varrer todos.
"""
from __future__ import annotations

import re

# Segmentos conforme a Resolução CNJ 65/2008
SEGMENTOS_JUSTICA = {
    1: "Supremo Tribunal Federal",
    2: "Conselho Nacional de Justiça",
    3: "Superior Tribunal de Justiça",
    4: "Justiça Federal",
    5: "Justiça do Trabalho",
    6: "Justiça Eleitoral",
    7: "Justiça Militar da União",
    8: "Justiça Estadual",
    9: "Justiça Militar Estadual",
}

TRIBUNAIS_TJ = {
    1: "TJAC", 2: "TJAL", 3: "TJAP", 4: "TJAM", 5: "TJBA",
    6: "TJCE", 7: "TJDFT", 8: "TJES", 9: "TJGO", 10: "TJMA",
    11: "TJMT", 12: "TJMS", 13: "TJMG", 14: "TJPA", 15: "TJPB",
    16: "TJPR", 17: "TJPE", 18: "TJPI", 19: "TJRJ", 20: "TJRN",
    21: "TJRS", 22: "TJRO", 23: "TJRR", 24: "TJSC", 25: "TJSE",
    26: "TJSP", 27: "TJTO",
}

TRIBUNAIS_TRF = {1: "TRF1", 2: "TRF2", 3: "TRF3", 4: "TRF4", 5: "TRF5", 6: "TRF6"}

TRIBUNAIS_TRT = {n: f"TRT{n}" for n in range(1, 25)}

# Justiça Eleitoral e Militar estadual usam a mesma numeração de UF da Justiça Estadual
UFS_POR_CODIGO = {
    1: "AC", 2: "AL", 3: "AP", 4: "AM", 5: "BA", 6: "CE", 7: "DF", 8: "ES", 9: "GO",
    10: "MA", 11: "MT", 12: "MS", 13: "MG", 14: "PA", 15: "PB", 16: "PR", 17: "PE",
    18: "PI", 19: "RJ", 20: "RN", 21: "RS", 22: "RO", 23: "RR", 24: "SC", 25: "SE",
    26: "SP", 27: "TO",
}

TRIBUNAIS_SUPERIORES = ("STF", "STJ", "TST", "STM", "TSE")


class CNJ:
    """Lê um número de processo e responde o que dá para saber só pelo número.

    >>> cnj = CNJ("10002542020258130079")
    >>> cnj.valido, cnj.formatado, cnj.tribunal
    (True, '1000254-20.2025.8.13.0079', 'TJMG')
    """

    REGEX = re.compile(r"^(\d{7})-(\d{2})\.(\d{4})\.(\d)\.(\d{1,2})\.(\d{4})$")

    def __init__(self, numero: str):
        self.numero_original = (numero or "").strip()
        self.formatado = self._formatar(self.numero_original)
        self._partes = self._separar()

    # ── leitura ───────────────────────────────────────────────────────────────

    @staticmethod
    def _formatar(numero: str) -> str:
        """Aceita o número com ou sem pontuação e devolve sempre pontuado."""
        digitos = re.sub(r"\D", "", numero)
        if len(digitos) == 20:
            return (f"{digitos[0:7]}-{digitos[7:9]}.{digitos[9:13]}"
                    f".{digitos[13]}.{digitos[14:16]}.{digitos[16:20]}")
        return numero

    def _separar(self) -> dict | None:
        m = self.REGEX.match(self.formatado)
        if not m:
            return None
        sequencial, digito, ano, segmento, tribunal, origem = m.groups()
        return {
            "sequencial": sequencial,
            "digito": digito,
            "ano": int(ano),
            "segmento": int(segmento),
            "tribunal_codigo": int(tribunal),
            "origem": int(origem),
        }

    # ── propriedades ──────────────────────────────────────────────────────────

    @property
    def valido(self) -> bool:
        return self._partes is not None

    @property
    def digitos(self) -> str:
        """Só os 20 dígitos — é a forma que as APIs indexam."""
        return re.sub(r"\D", "", self.formatado)

    @property
    def ano(self) -> int:
        return self._partes["ano"] if self._partes else 0

    @property
    def segmento(self) -> int:
        return self._partes["segmento"] if self._partes else 0

    @property
    def tribunal_codigo(self) -> int:
        return self._partes["tribunal_codigo"] if self._partes else 0

    @property
    def origem_codigo(self) -> int:
        return self._partes["origem"] if self._partes else 0

    @property
    def nome_segmento(self) -> str:
        return SEGMENTOS_JUSTICA.get(self.segmento, "Desconhecido")

    @property
    def tribunal(self) -> str:
        """Sigla do tribunal (TJMG, TRF6, TRT3, STJ...).

        Quando o código do tribunal é 00, o processo é do tribunal superior do
        segmento (TST na trabalhista, TSE na eleitoral).
        """
        seg, cod = self.segmento, self.tribunal_codigo
        if seg == 1:
            return "STF"
        if seg == 2:
            return "CNJ"
        if seg == 3:
            return "STJ"
        if seg == 4:
            return TRIBUNAIS_TRF.get(cod, f"TRF{cod}")
        if seg == 5:
            return "TST" if cod == 0 else TRIBUNAIS_TRT.get(cod, f"TRT{cod}")
        if seg == 6:
            return "TSE" if cod == 0 else f"TRE-{UFS_POR_CODIGO.get(cod, str(cod))}"
        if seg == 7:
            return "STM"
        if seg == 8:
            return TRIBUNAIS_TJ.get(cod, f"TJ{cod:02d}")
        if seg == 9:
            return f"TJM-{UFS_POR_CODIGO.get(cod, str(cod))}"
        return f"SEG{seg}-TR{cod}"

    @property
    def indice_datajud(self) -> str:
        """Nome do índice desse tribunal na API pública do Datajud.

        Confirmado para justiça estadual, federal, trabalhista e tribunais
        superiores. Eleitoral e militar seguem o mesmo padrão, mas não foram
        testadas — confira na documentação do CNJ antes de confiar.
        """
        return f"api_publica_{self.tribunal.lower()}"

    def __str__(self) -> str:
        return self.formatado

    def __repr__(self) -> str:
        return f"CNJ({self.formatado!r}, tribunal={self.tribunal!r}, valido={self.valido})"

    def __eq__(self, outro) -> bool:
        return isinstance(outro, CNJ) and self.digitos == outro.digitos

    def __hash__(self) -> int:
        return hash(self.digitos)


def todos_os_tribunais() -> list[str]:
    """Todas as siglas que existem como índice no Datajud."""
    return [
        *TRIBUNAIS_TJ.values(),
        *TRIBUNAIS_TRF.values(),
        *TRIBUNAIS_TRT.values(),
        *TRIBUNAIS_SUPERIORES,
    ]
