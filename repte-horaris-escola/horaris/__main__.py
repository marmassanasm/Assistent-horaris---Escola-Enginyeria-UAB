"""python -m horaris check <proposta.csv> [--paquet paquet] [--relaxacions r.csv] [--json f] [--violacions f]

Codi de sortida: 0 si la proposta és VÀLIDA (o vàlida amb relaxacions declarades), 1 si no ho és, 2 si
l'entrada no es pot llegir.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

from horaris.check import DESCRIPCIO, avalua
from horaris.model import carrega_base, llegeix_proposta, llegeix_relaxacions


def _cel(x: str) -> str:
    """El text de la proposta és de l'equip: que Excel no el llegeixi com a fórmula (/challenge I4)."""
    return "'" + x if x[:1] in ('=', '+', '-', '@') else x


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog='python -m horaris')
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('check', help='verifica una proposta d\'horari')
    c.add_argument('proposta')
    c.add_argument('--paquet', default=str(Path(__file__).resolve().parents[1] / 'paquet'))
    c.add_argument('--relaxacions')
    c.add_argument('--json', help='escriu l\'informe complet en JSON')
    c.add_argument('--violacions', help='escriu totes les violacions en CSV')
    c.add_argument('--semestre', type=int, choices=(1, 2), help='avalua només les sessions d\'un semestre (per data)')
    c.add_argument('--escenari', help='carpeta d\'escenari (paquet/escenaris/...): sessions extra, aules tancades')
    c.add_argument('--referencia', help='una altra proposta: compta els canvis respecte d\'ella')
    c.add_argument('--nomes-aules', action='store_true',
                   help="només es reparteixen aules: l'horari d'avui no es mou i els torns nous no s'apliquen")
    a = ap.parse_args(argv)
    try:
        base = carrega_base(Path(a.paquet), semestre=a.semestre, escenari=Path(a.escenari) if a.escenari else None)
        files = llegeix_proposta(Path(a.proposta))
        ref = llegeix_proposta(Path(a.referencia)) if a.referencia else None
        rel = llegeix_relaxacions(Path(a.relaxacions) if a.relaxacions else None)
    except (OSError, ValueError, KeyError) as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 2
    if a.semestre:
        # una proposta de tot el curs també val: les sessions de l'altre semestre s'ignoren
        tot = carrega_base(Path(a.paquet), escenari=Path(a.escenari) if a.escenari else None).sessions
        fora = [f for f in files if f.id not in base.sessions and f.id in tot]
        files = [f for f in files if not (f.id not in base.sessions and f.id in tot)]
        ref = [f for f in ref if f.id in base.sessions] if ref is not None else None
        print(f'Semestre {a.semestre}: {len(fora)} files de l\'altre semestre ignorades')
    if base.escenari:
        print(f'Escenari: {base.escenari}')
    inf = avalua(base, files, rel, referencia=ref, nomes_aules=a.nomes_aules)
    rec = inf.recompte()
    n_decl = sum(1 for v in inf.violacions if v.declarada and not v.heretada)
    print(f'Veredicte: {inf.veredicte}' + (f' ({n_decl} incompliments declarats com a relaxació)' if n_decl else ''))
    print(f'Sessions a la base: {len(base.sessions)} · a la proposta: {len(files)}')
    print('\nRestriccions dures          compten  declarades  heretades')
    for regla, desc in DESCRIPCIO.items():
        r = rec.get(regla, {'total': 0, 'compten': 0, 'declarades': 0, 'heretades': 0})
        marca = 'KO ' if r['compten'] else ('REL' if r['declarades'] else 'OK ')
        print(f"  [{marca}] {regla:<14} {r['compten']:>8} {r['declarades']:>11} {r['heretades']:>10}  {desc}")
    print('  (heretades = no imputables a la proposta: només hi intervenen sessions fixades sense moure, o\n'
          '   solapaments de docent/alumnat que ja hi eren a l\'horari de partida; es llisten però no compten)')
    if inf.no_avaluables:
        print('\nNo avaluades (dades de partida incompletes, o regla no aplicable en aquest mode): ' +
              ', '.join(f'{k}: {v} sessions' for k, v in sorted(inf.no_avaluables.items())))
    print('\nObjectius (restricció 9, com més baix millor)')
    for k, v in inf.objectius.items():
        print(f'  {k:<24} {v}')
    if a.json:
        # /challenge 07/11/2026: l'informe porta el context i l'empremta del que s'ha avaluat (paquet, proposta,
        # referència, semestre, escenari), perquè el jurat el pugui reproduir; i quants incompliments s'han declarat,
        # no només quantes files té el CSV de relaxacions.
        def _sha(p):
            return hashlib.sha256(Path(p).read_bytes()).hexdigest() if p else None
        paq = Path(a.paquet)
        h = hashlib.sha256()
        for f in sorted(paq.glob('*.csv')):
            h.update(f'{f.name}\0{_sha(f)}\n'.encode())
        Path(a.json).write_text(json.dumps({
            'veredicte': inf.veredicte, 'restriccions': rec, 'no_avaluables': dict(inf.no_avaluables),
            'objectius': inf.objectius, 'relaxacions_declarades': len(inf.relaxacions),
            'incompliments_declarats': n_decl,
            'context': {'semestre': a.semestre, 'escenari': a.escenari, 'nomes_aules': a.nomes_aules,
                        'paquet_sha256': h.hexdigest(), 'proposta_sha256': _sha(a.proposta),
                        'referencia_sha256': _sha(a.referencia), 'relaxacions_sha256': _sha(a.relaxacions)}},
            ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if a.violacions:
        with open(a.violacions, 'w', encoding='utf-8', newline='') as f:
            w = csv.writer(f)
            w.writerow(['regla', 'sessions', 'detall', 'compta', 'declarada', 'heretada'])
            for v in inf.violacions:
                w.writerow([_cel(v.regla), _cel('|'.join(v.sessions)), _cel(v.detall), int(v.compta),
                            int(v.declarada), v.heretada])
    return 0 if inf.veredicte.startswith('VALIDA') else 1


if __name__ == '__main__':
    sys.exit(main())
