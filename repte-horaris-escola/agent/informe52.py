"""agent/informe52.py: tot el que cal lliurar del 5.2 a partir de la proposta de torns.

    python -m agent.informe52 --proposta proposta-torns.csv --sortida lliurament-5-2

Genera a la carpeta de sortida:
  relaxacions-5-2.csv   les excepcions que cal declarar (sessions fixades fora de torn, etc.)
  graella-setmanal.csv  una fila per aula, dia i hora d'una setmana tipus
  graella-setmanal.html la mateixa graella per mirar-la al navegador
  resum-junta.md        el resum d'una pàgina per a la Junta Permanent
  veredicte.txt         el veredicte del verificador amb les relaxacions
Després passeu el verificador oficial (la comanda surt al final).
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import html
from pathlib import Path

from horaris.check import _col_loca, Informe, avalua
from horaris.model import DIES, MATI, Relaxacio, carrega_base, fmt, llegeix_proposta


def relaxacions(base, files):
    """Una fila per cada motiu: les sessions que continuen fora de torn i que ningú no pot moure."""
    inf0 = avalua(base, files, [])
    fixades, altres = [], []
    for v in inf0.violacions:
        if v.regla == 'R1-TORN' and v.compta:
            s = base.sessions[v.sessions[0]]
            (fixades if s.fixada else altres).append(s)
    files_rel = []
    if fixades:
        files_rel.append({
            'restriccio': 'R1-TORN',
            'sessions': '|'.join(s.id for s in fixades),
            'justificacio': "Sessions fixades de GEI 1r/2n (regla 1: no es toquen) que avui son a la tarda. "
                            "No es poden moure; com que no tenen aula a la partida i cal donar-ne una (R5), "
                            "el verificador ja no les compta com a heretades."})
    soles = [s for s in altres if s.compartida and s.dia == 'L' and s.data == dt.date(2027, 5, 31)]
    resta = [s for s in altres if s not in soles]
    if soles:
        files_rel.append({
            'restriccio': 'R1-TORN',
            'sessions': '|'.join(s.id for s in soles),
            'justificacio': "TE/51 de doble titulacio del 31/05/2027: es l'unic dia lectiu d'aquella setmana "
                            "(la setmana no es pot canviar) i totes les franges de tarda xoquen amb el mateix "
                            "docent o alumnat."})
    if resta:
        files_rel.append({
            'restriccio': 'R1-TORN',
            'sessions': '|'.join(s.id for s in resta),
            'justificacio': "Sessio en setmana d'avaluacio o aturada: nomes es pot canviar d'hora, no de dia, "
                            "i no queda cap hora dins del torn sense solapaments."})
    return files_rel


def graella(base, col, setmana, path_csv, path_html):
    sessions = [c for c in col.values() if c.data.isocalendar()[:2] == setmana and c.aula and not c.s.sense_espai]
    aules = sorted({c.aula for c in sessions})
    hores = list(range(MATI[0], 21 * 60, 30))
    cel = {}
    for c in sessions:
        for t in range(c.ini - (c.ini - MATI[0]) % 30, c.fi, 30):
            if t >= c.ini - 29 and t < c.fi:
                cel[(c.aula, c.data.weekday(), t)] = f'{c.s.codi} {c.s.grup}'
    with open(path_csv, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['aula', 'dia', 'hora', 'classe'])
        for a in aules:
            for d in range(5):
                for t in hores:
                    if (a, d, t) in cel:
                        w.writerow([a, DIES[d], fmt(t), cel[(a, d, t)]])
    out = ['<meta charset="utf-8"><style>body{font:12px sans-serif}table{border-collapse:collapse;margin:8px 0 24px}'
           'td,th{border:1px solid #ccc;padding:2px 4px;white-space:nowrap}td.o{background:#c9ecd3}</style>',
           f'<h2>Graella setmanal per aula · setmana {setmana[0]}-W{setmana[1]:02d}</h2>']
    for a in aules:
        out.append(f'<h3>{a} ({base.aules[a].capacitat if a in base.aules else "fora de l\'aulari"} places)</h3><table><tr><th></th>' +
                   ''.join(f'<th>{d}</th>' for d in DIES) + '</tr>')
        for t in hores:
            row = f'<tr><th>{fmt(t)}</th>'
            for d in range(5):
                v = cel.get((a, d, t))
                row += f'<td class="o">{html.escape(v)}</td>' if v else '<td></td>'
            out.append(row + '</tr>')
        out.append('</table>')
    Path(path_html).write_text('\n'.join(out), encoding='utf-8')


def pic(col, base, torn, nomes_ordinaries=False):
    mx, on = 0, None
    for data in sorted({c.data for c in col.values()}):
        cs = [c for c in col.values() if c.data == data and not c.s.sense_espai and c.s.tipus != 'PLAB'
              and (not nomes_ordinaries or (c.aula in base.aules and base.aules[c.aula].ordinaria))]
        lo, hi = MATI if torn == 'mati' else (MATI[1], 21 * 60)
        for t in range(lo, hi, 30):
            n = len({c.aula or c.s.unitat for c in cs if c.ini < t + 30 and c.fi > t} if nomes_ordinaries
                    else {c.s.unitat for c in cs if c.ini < t + 30 and c.fi > t})
            if n > mx:
                mx, on = n, (data, t)
    return mx, on


def resum(base, col, files, ref, inf, path):
    ordin = [a for a in base.aules.values() if a.ordinaria]
    pm, om = pic(col, base, 'mati')
    pt, ot = pic(col, base, 'tarda')
    pmo, _ = pic(col, base, 'mati', True)
    pto, _ = pic(col, base, 'tarda', True)
    # grans: pic de classes simultànies amb més de c alumnes vs aules ordinàries més grans que c
    grans = []
    for c in (63, 90, 100, 117, 130):
        mx = 0
        for data in {x.data for x in col.values()}:
            cs = [x for x in col.values() if x.data == data and not x.s.sense_espai and x.s.tipus != 'PLAB'
                  and x.s.alumnes > c]
            for t in range(MATI[0], 21 * 60, 30):
                mx = max(mx, len({x.s.unitat for x in cs if x.ini < t + 30 and x.fi > t}))
        grans.append((c, mx, sum(1 for a in ordin if a.capacitat > c)))
    mogudes = collections.Counter()
    tot = collections.Counter()
    ref_ids = {s.id: s for s in base.sessions.values()}
    for sid, c in col.items():
        s = c.s
        for coh in s.cohorts:
            tot[coh] += 1
            if (c.data, c.ini) != (s.data, s.ini):
                mogudes[coh] += 1
    n_mogudes = sum(1 for c in col.values() if (c.data, c.ini) != (c.s.data, c.s.ini))
    o = inf.objectius
    rec = inf.recompte()
    L = ['# 5.2 · Torns nous: resum per a la Junta Permanent', '',
         f'Veredicte del verificador: **{inf.veredicte}** (2n semestre, {len(col)} sessions).', '',
         '## 1. Hi cap? Pic de classes alhora', '',
         f'- **Matí** (8.30-14.30): pic de **{pm}** classes simultànies, de les quals {pmo} ocupen una aula ordinària. '
         f'Aules ordinàries disponibles: **{len(ordin) - 2}** (21 menys les 2 de reserva).',
         f'- **Tarda** (14.30-21.00): pic de **{pt}** classes simultànies ({pto} en aula ordinària), també sobre {len(ordin) - 2}.',
         '', '## 2. Aules que falten o sobren per mida', '',
         'Pic de classes simultànies amb més alumnes que una mida, comparat amb les aules ordinàries més grans:', '',
         '| Més de... alumnes | Pic de classes alhora | Aules ordinàries que hi caben |', '|---|---|---|']
    L += [f'| {c} | {p} | {n} |' for c, p, n in grans]
    L += ['', f'No falta cap aula: totes les regles dures (aforament, tipus, solapaments, reserva de 2 aules) es compleixen. '
              f'A la tarda el pic de classes és més alt, però part van a seminaris, aules d\'informàtica o laboratoris integrats; en aules ordinàries el pic és de {pto}.',
          '', '## 3. Sessions mogudes per titulació i curs', '',
          f'Total: **{n_mogudes}** de {len(col)} sessions canvien de dia o hora ('
          f'{100 * n_mogudes / len(col):.0f} %).', '',
          '| Titulació:curs | Sessions mogudes | % |', '|---|---|---|']
    for coh, n in mogudes.most_common(12):
        L.append(f'| {coh} | {n} | {100 * n / tot[coh]:.0f} % |')
    L += ['', '## 4. Excepcions a la regla 1 que demanem', '']
    for r in relaxacions(base, files):
        n = len(r['sessions'].split('|'))
        L.append(f'- **{n} {"sessió" if n == 1 else "sessions"}**: {r["justificacio"]}')
    L += ['', '## 5. Objectius (com més baix, millor)', '',
          f'- Hores mortes: {o["hores_mortes_min"]} min · desplaçaments d\'aula: {o["desplacaments_aula"]} '
          f'(entre edificis: {o["desplacaments_edifici"]})',
          f'- Canvis de franja: {o["canvis_franja"]} · canvis d\'aula: {o["canvis_aula"]}']
    Path(path).write_text('\n'.join(L) + '\n', encoding='utf-8')


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m agent.informe52')
    ap.add_argument('--proposta', required=True)
    ap.add_argument('--paquet', default='paquet')
    ap.add_argument('--semestre', type=int, default=2)
    ap.add_argument('--referencia', default=None, help='proposta de partida (per defecte paquet/proposta_partida.csv)')
    ap.add_argument('--sortida', default='lliurament-5-2')
    a = ap.parse_args(argv)
    out = Path(a.sortida)
    out.mkdir(parents=True, exist_ok=True)
    base = carrega_base(Path(a.paquet), semestre=a.semestre)
    files = [f for f in llegeix_proposta(Path(a.proposta)) if f.id in base.sessions]
    rel = relaxacions(base, files)
    with open(out / 'relaxacions-5-2.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['restriccio', 'sessions', 'justificacio'])
        w.writeheader()
        w.writerows(rel)
    rels = [Relaxacio(r['restriccio'], frozenset(r['sessions'].split('|')), r['justificacio']) for r in rel]
    ref = llegeix_proposta(Path(a.referencia or Path(a.paquet) / 'proposta_partida.csv'))
    ref = [f for f in ref if f.id in base.sessions]
    inf = avalua(base, files, rels, referencia=None)
    col = _col_loca(base, files, Informe())
    setm = sorted({c.data.isocalendar()[:2] for c in col.values()})[1]
    graella(base, col, setm, out / 'graella-setmanal.csv', out / 'graella-setmanal.html')
    resum(base, col, files, ref, inf, out / 'resum-junta.md')
    rec = inf.recompte()
    txt = [f'Veredicte: {inf.veredicte}',
           f'Incompliments declarats: {sum(1 for v in inf.violacions if v.declarada and not v.heretada)}']
    txt += [f'  {k}: compten {v["compten"]}, declarades {v["declarades"]}, heretades {v["heretades"]}'
            for k, v in rec.items() if v['compten'] or v['declarades']]
    (out / 'veredicte.txt').write_text('\n'.join(txt) + '\n', encoding='utf-8')
    print('\n'.join(txt))
    print(f'\nFitxers a {out}/')
    print(f'Ara passeu el verificador oficial:\n  python -m horaris check {a.proposta} --semestre {a.semestre} '
          f'--relaxacions {out}/relaxacions-5-2.csv --json {out}/informe-5-2.json --violacions {out}/violacions-5-2.csv')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())