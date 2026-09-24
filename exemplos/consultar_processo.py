"""Consulta um processo e mostra o essencial.

    python exemplos/consultar_processo.py 1000254-20.2025.8.13.0079
"""
import sys

from consulta_processos import FonteIndisponivel, consultar_processo


def main(numero: str) -> int:
    try:
        processo = consultar_processo(numero)
    except FonteIndisponivel as e:
        print(f"Fonte fora do ar ({e}). Tente de novo mais tarde.")
        return 1

    if processo is None:
        print("Processo não encontrado nas fontes públicas.")
        print("Se ele acabou de ser distribuído, aguarde alguns dias e tente de novo.")
        return 1

    print(f"{processo.numero} — {processo.tribunal}")
    print(processo.titulo)
    print(f"Classe: {processo.classe or '—'} | Órgão: {processo.orgao_julgador or '—'}")
    print(f"Fontes consultadas: {', '.join(f.value for f in processo.fontes)}")

    print(f"\nÚltimas movimentações ({len(processo.movimentacoes)} no total):")
    for mov in processo.movimentacoes[:10]:
        print(f"  {mov.data:%d/%m/%Y}  {mov.tipo.value:<15} {mov.descricao[:80]}")

    if processo.publicacoes:
        ultima = processo.publicacoes[0]
        print(f"\nPublicação mais recente ({ultima.data_disponibilizacao:%d/%m/%Y}):")
        print(f"  {ultima.tipo_comunicacao} — {ultima.orgao}")
        print(f"  {ultima.texto[:400]}...")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
