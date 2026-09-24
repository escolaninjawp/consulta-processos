"""Estruturas de dados devolvidas pela biblioteca.

São dataclasses simples, sem banco e sem framework: cada uma tem `.to_dict()`
para você gravar onde quiser (JSON, ORM, planilha).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from enum import Enum


class Fonte(str, Enum):
    """De onde o dado veio."""
    DATAJUD = "datajud"          # API pública do CNJ (metadados + movimentos internos)
    COMUNICA = "comunica"        # API Comunica/DJEN do CNJ (publicações do diário)


class TipoMovimentacao(str, Enum):
    DESPACHO = "despacho"
    DECISAO = "decisao"
    SENTENCA = "sentenca"
    AUDIENCIA = "audiencia"
    INTIMACAO = "intimacao"
    PUBLICACAO_DJE = "publicacao_dje"
    OUTRO = "outro"


class Polo(str, Enum):
    ATIVO = "ativo"
    PASSIVO = "passivo"
    TERCEIRO = "terceiro"


def _limpo(dado):
    """Converte datas e enums para texto, para o dicionário virar JSON direto."""
    if isinstance(dado, (datetime, date)):
        return dado.isoformat()
    if isinstance(dado, Enum):
        return dado.value
    if isinstance(dado, dict):
        return {k: _limpo(v) for k, v in dado.items()}
    if isinstance(dado, (list, tuple)):
        return [_limpo(v) for v in dado]
    return dado


@dataclass
class Base:
    def to_dict(self) -> dict:
        return {k: _limpo(v) for k, v in asdict(self).items()}


@dataclass
class Advogado(Base):
    nome: str
    oab_numero: str = ""
    oab_uf: str = ""

    def __str__(self) -> str:
        oab = f" (OAB {self.oab_uf} {self.oab_numero})" if self.oab_numero else ""
        return f"{self.nome}{oab}"


@dataclass
class Parte(Base):
    nome: str
    polo: Polo = Polo.TERCEIRO
    advogados: list[Advogado] = field(default_factory=list)

    def __str__(self) -> str:
        return f"{self.nome} ({self.polo.value})"


@dataclass
class Movimentacao(Base):
    """Um andamento do processo."""
    data: datetime
    descricao: str
    tipo: TipoMovimentacao = TipoMovimentacao.OUTRO
    fonte: Fonte = Fonte.DATAJUD
    id_externo: str = ""          # identificador na origem — serve para não duplicar
    complemento: str = ""
    orgao: str = ""
    link: str = ""

    def __str__(self) -> str:
        return f"{self.data:%d/%m/%Y} — {self.descricao[:80]}"


@dataclass
class Publicacao(Base):
    """Uma comunicação publicada no Diário de Justiça Eletrônico Nacional."""
    id_externo: str
    data_disponibilizacao: date | None
    tipo_comunicacao: str = ""
    tipo_documento: str = ""
    orgao: str = ""
    numero_processo: str = ""
    classe: str = ""
    texto: str = ""               # teor do ato, já sem HTML
    link: str = ""
    partes: list[Parte] = field(default_factory=list)
    advogados: list[Advogado] = field(default_factory=list)

    def como_movimentacao(self) -> Movimentacao:
        """Converte para andamento, para juntar com o histórico do Datajud.

        A data sai com fuso (UTC) porque o Datajud também devolve com fuso, e
        misturar data com e sem fuso quebra qualquer ordenação.
        """
        from .fontes.comunica import classificar_tipo
        quando = self.data_disponibilizacao or date.today()
        return Movimentacao(
            data=datetime(quando.year, quando.month, quando.day, tzinfo=timezone.utc),
            descricao=self.tipo_comunicacao or "Comunicação",
            tipo=classificar_tipo(self.tipo_comunicacao),
            fonte=Fonte.COMUNICA,
            id_externo=f"comunica-{self.id_externo}",
            complemento=self.texto,
            orgao=self.orgao,
            link=self.link,
        )


@dataclass
class Processo(Base):
    """O processo como as fontes públicas o descrevem."""
    numero: str
    tribunal: str = ""
    segmento: str = ""
    grau: str = ""
    classe: str = ""
    assunto: str = ""
    orgao_julgador: str = ""
    comarca: str = ""
    # Consulta pública do próprio tribunal, quando o diário informa. Nem todos
    # informam, então trate como opcional.
    link: str = ""
    valor_causa: float | None = None
    data_ajuizamento: datetime | None = None
    data_ultima_movimentacao: date | None = None
    partes: list[Parte] = field(default_factory=list)
    advogados: list[Advogado] = field(default_factory=list)
    movimentacoes: list[Movimentacao] = field(default_factory=list)
    publicacoes: list[Publicacao] = field(default_factory=list)
    fontes: list[Fonte] = field(default_factory=list)

    @property
    def polo_ativo(self) -> list[str]:
        return [p.nome for p in self.partes if p.polo == Polo.ATIVO]

    @property
    def polo_passivo(self) -> list[str]:
        return [p.nome for p in self.partes if p.polo == Polo.PASSIVO]

    @property
    def titulo(self) -> str:
        """"Fulano × Beltrano", como aparece na capa dos autos."""
        ativo = ", ".join(self.polo_ativo) or "—"
        passivo = ", ".join(self.polo_passivo) or "—"
        return f"{ativo} × {passivo}"

    def __str__(self) -> str:
        return f"{self.numero} ({self.tribunal}) — {self.titulo}"
