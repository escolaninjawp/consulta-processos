"""Publicações de um advogado nos últimos dias, agrupadas por processo.

É o começo de um controle de prazos: rode uma vez por dia e compare com o que
você já tinha, para saber o que é novo.

    python exemplos/publicacoes_da_semana.py 123456 MG 7
"""
import sys
from collections import defaultdict
from datetime import date, timedelta

from consulta_processos import FonteIndisponivel, publicacoes_por_oab


def main(numero: str, uf: str, dias: int) -> int:
    fim = date.today()
    inicio = fim - timedelta(days=dias)
    try:
        publicacoes = publicacoes_por_oab(numero, uf, inicio=inicio, fim=fim, paginas=0)
    except FonteIndisponivel as e:
        print(f"Diário fora do ar ({e}). Tente de novo mais tarde.")
        return 1

    print(f"{len(publicacoes)} publicação(ões) entre {inicio:%d/%m} e {fim:%d/%m}\n")

    por_processo = defaultdict(list)
    for pub in publicacoes:
        por_processo[pub.numero_processo or "sem número"].append(pub)

    for processo, itens in sorted(por_processo.items()):
        print(f"{processo}  ({len(itens)})")
        for pub in sorted(itens, key=lambda p: p.data_disponibilizacao or date.min, reverse=True):
            quando = pub.data_disponibilizacao.strftime("%d/%m") if pub.data_disponibilizacao else "—"
            print(f"   {quando}  {pub.tipo_comunicacao[:45]:<45} {pub.orgao[:45]}")
        print()
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 7))
