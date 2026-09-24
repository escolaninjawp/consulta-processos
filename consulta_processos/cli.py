"""Linha de comando.

    consulta-processos processo 1000254-20.2025.8.13.0079
    consulta-processos processo 1000254-20.2025.8.13.0079 --json > processo.json
    consulta-processos oab 123456 MG --tribunal TJMG
    consulta-processos publicacoes 123456 MG --dias 7
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta

from . import __version__
from .api import buscar_por_oab, consultar_processo, publicacoes_por_oab
from .erros import ConsultaError
from .modelos import Processo


def _saida_em_utf8() -> None:
    """Evita quebrar no console do Windows, que por padrão não é UTF-8.

    Nomes de parte, "×" e acentos derrubariam o comando com UnicodeEncodeError
    num `cmd` comum. Caracteres que o console não souber desenhar viram "?".
    """
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):       # saída redirecionada para outro lugar
            pass


def _imprimir_processo(processo: Processo, movimentos: int) -> None:
    print(f"\n{processo.numero}  ·  {processo.tribunal}  ·  {processo.segmento}")
    print(f"{processo.titulo}")
    if processo.classe:
        print(f"Classe: {processo.classe}")
    if processo.assunto:
        print(f"Assunto: {processo.assunto}")
    if processo.orgao_julgador:
        print(f"Órgão: {processo.orgao_julgador}")
    if processo.valor_causa:
        # Formato brasileiro: 1.234.567,89
        valor = f"{processo.valor_causa:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
        print(f"Valor da causa: R$ {valor}")
    if processo.advogados:
        print("Advogados: " + "; ".join(str(a) for a in processo.advogados[:8]))
    print(f"Fontes: {', '.join(f.value for f in processo.fontes)}")

    if processo.movimentacoes:
        print(f"\nMovimentações ({len(processo.movimentacoes)}), as {movimentos} mais recentes:")
        for mov in processo.movimentacoes[:movimentos]:
            print(f"  {mov.data:%d/%m/%Y}  {mov.tipo.value:<15} {mov.descricao[:90]}")
    if processo.publicacoes:
        print(f"\nPublicações no diário: {len(processo.publicacoes)}")


def _cmd_processo(args) -> int:
    processo = consultar_processo(args.numero, com_publicacoes=not args.sem_publicacoes)
    if processo is None:
        print(f"Processo não encontrado nas fontes públicas: {args.numero}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(processo.to_dict(), ensure_ascii=False, indent=2))
    else:
        _imprimir_processo(processo, args.movimentos)
    return 0


def _cmd_oab(args) -> int:
    processos = buscar_por_oab(args.numero, args.uf, tribunal=args.tribunal)
    if args.json:
        print(json.dumps([p.to_dict() for p in processos], ensure_ascii=False, indent=2))
        return 0
    print(f"{len(processos)} processo(s) para a OAB {args.uf.upper()} {args.numero}")
    for processo in processos:
        print(f"  {processo.numero}  {processo.tribunal:<7} {processo.titulo[:80]}")
    return 0


def _cmd_publicacoes(args) -> int:
    fim = date.today()
    inicio = fim - timedelta(days=args.dias)
    publicacoes = publicacoes_por_oab(args.numero, args.uf, inicio=inicio, fim=fim,
                                      paginas=args.paginas)
    if args.json:
        print(json.dumps([p.to_dict() for p in publicacoes], ensure_ascii=False, indent=2))
        return 0
    print(f"{len(publicacoes)} publicação(ões) para a OAB {args.uf.upper()} {args.numero} "
          f"entre {inicio:%d/%m/%Y} e {fim:%d/%m/%Y}")
    for pub in publicacoes:
        quando = pub.data_disponibilizacao.strftime("%d/%m/%Y") if pub.data_disponibilizacao else "—"
        print(f"  {quando}  {pub.numero_processo:<27} {pub.tipo_comunicacao[:40]:<40} {pub.orgao[:40]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    _saida_em_utf8()
    parser = argparse.ArgumentParser(
        prog="consulta-processos",
        description="Busca e consulta de processos judiciais nas fontes públicas (Datajud e DJEN).",
    )
    parser.add_argument("--version", action="version", version=f"consulta-processos {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="mostra o que está acontecendo")
    # Repetido nos subcomandos para que `-v` funcione antes ou depois do comando
    comum = argparse.ArgumentParser(add_help=False)
    comum.add_argument("-v", "--verbose", action="store_true", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("processo", parents=[comum], help="consulta um processo pelo número")
    p.add_argument("numero", help="número CNJ, com ou sem pontuação")
    p.add_argument("--json", action="store_true", help="devolve JSON")
    p.add_argument("--movimentos", type=int, default=10, help="quantas movimentações mostrar")
    p.add_argument("--sem-publicacoes", action="store_true", help="não consulta o diário")
    p.set_defaults(func=_cmd_processo)

    o = sub.add_parser("oab", parents=[comum], help="processos de um advogado (Datajud)")
    o.add_argument("numero", help="número da inscrição")
    o.add_argument("uf", help="UF da inscrição, ex.: MG")
    o.add_argument("--tribunal", default="", help="limita a um tribunal, ex.: TJMG (bem mais rápido)")
    o.add_argument("--json", action="store_true")
    o.set_defaults(func=_cmd_oab)

    d = sub.add_parser("publicacoes", parents=[comum], help="publicações de um advogado no diário (DJEN)")
    d.add_argument("numero", help="número da inscrição")
    d.add_argument("uf", help="UF da inscrição")
    d.add_argument("--dias", type=int, default=7, help="janela em dias (padrão: 7)")
    d.add_argument("--paginas", type=int, default=1, help="páginas a buscar (0 = todas)")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=_cmd_publicacoes)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(message)s")
    try:
        return args.func(args)
    except ConsultaError as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
