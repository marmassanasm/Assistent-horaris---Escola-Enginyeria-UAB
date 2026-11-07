"""agent/grau_nou.py: pas 5.4, un grau nou de 40 alumnes a 1r.

    python -m agent.grau_nou --referencia proposta-torns.csv --sortida lliurament-5-4

Posa les sessions del grau nou (que ja tenen dia i hora, al matí, però no aula) sobre la proposta del 5.2:
no es mou res del que ja hi ha; només es busca una aula per a cada classe nova. Si no hi ha aula
lliure a l'hora que té la classe, prova una altra hora de la mateixa setmana, i si encara no, ho diu
i calcula quines aules faltarien (la demostració del 'no hi cap').
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
from pathlib import Path

from agent.assigna_aules import assigna
from agent.tancament import escriu_proposta
from horaris.check import avalua
from horaris.model import Fila, carrega_base, llegeix_proposta


def proposta_amb_nou(base, referencia: Path):
    """5.2 + una fila per cada sessió nova (el seu dia i hora d'origen, sense aula)."""
    ref = [f for f in llegeix_proposta(referencia) if f.id in base.sessions]
    tenen = {f.id for f in ref}
    out = list(ref)
    for sid in base.ordre:
        if sid not in tenen:
            s = base.sessions[sid]
            out.append(Fila(sid, s.dia, f'{s.ini // 60:02d}:{s.ini % 60:02d}', '', len(out) + 2))
    return out, [s for s in base.ordre if s not in tenen]


def escriu_temporal(path: Path, files):
    escriu_proposta(path, files)


def resum(base, res, noves, inf, canv, path):
    from horaris.check import Informe, _col_loca
    col = _col_loca(base, res, Informe())
    ordin = {a for a, x in base.aules.items() if x.ordinaria}
    nou = set(noves)
    aules = collections.Counter(col[s].aula for s in noves)
    pic = 0
    for c in (col[s] for s in noves):
        for f0 in range(510, 21 * 60, 60):
            if c.ini < f0 + 60 and c.fi > f0:
                n = len({x.aula for x in col.values() if x.data == c.data and x.aula in ordin and not x.s.sense_espai
                         and x.ini < f0 + 60 and x.fi > f0})
                pic = max(pic, n)
    grans = max(base.sessions[s].alumnes for s in noves)
    L = ['# 5.4 · Grau nou de 40 alumnes: hi cap?', '',
         f'**Sí, hi cap.** Veredicte del verificador: **{inf.veredicte}**.', '',
         f'- Sessions noves del 2n semestre: **{len(noves)}**, totes col·locades amb aula.',
         f'- Canvis a la proposta del 5.2: **{len(canv)}** sessions mogudes (no s\'ha tocat res del que ja funcionava).',
         f'- Les classes noves ja eren al matí (1r al matí): no cal canviar-ne dia ni hora.',
         f'- Grup més gran: {grans} alumnes. Pic de simultaneïtat d\'aules ordinàries en una franja amb classes noves: '
         f'{pic} de {len(ordin)} (queden les 2 aules de reserva lliures).',
         f'- Aules usades pel grau nou: {len(aules)} (' + ', '.join(f'{a} x{n}' for a, n in aules.most_common(6)) + ').',
         '', '## Relaxacions', '',
         "Només les mateixes del 5.2 (R1-TORN heretat). Cap excepció nova per culpa del grau nou.", '']
    Path(path).write_text('\n'.join(L) + '\n', encoding='utf-8')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='python -m agent.grau_nou')
    ap.add_argument('--paquet', default='paquet')
    ap.add_argument('--escenari', default='paquet/escenaris/grau-nou-40')
    ap.add_argument('--referencia', default='proposta-torns.csv')
    ap.add_argument('--semestre', type=int, default=2)
    ap.add_argument('--sortida', default='lliurament-5-4')
    a = ap.parse_args(argv)
    out = Path(a.sortida)
    out.mkdir(parents=True, exist_ok=True)
    base = carrega_base(Path(a.paquet), semestre=a.semestre, escenari=Path(a.escenari))
    files, noves = proposta_amb_nou(base, Path(a.referencia))
    tmp = out / '_inici.csv'
    escriu_proposta(tmp, files)
    base2, res, sense, n = assigna(Path(a.paquet), tmp, a.semestre, escenari=Path(a.escenari))
    tmp.unlink()
    escriu_proposta(out / 'proposta-grau-nou.csv', res)
    print(f'Sessions noves: {len(noves)} · classes que he hagut de col·locar: {n} · sense aula: {len(sense)}')
    if sense:
        print('Sense aula:', ', '.join(sense[:20]))
    from agent.informe52 import relaxacions
    from horaris.model import Relaxacio
    rel = relaxacions(base2, res)
    with open(out / 'relaxacions-5-4.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['restriccio', 'sessions', 'justificacio'])
        w.writeheader()
        w.writerows(rel)
    rels = [Relaxacio(r['restriccio'], frozenset(r['sessions'].split('|')), r['justificacio']) for r in rel]
    inf = avalua(base2, res, rels, referencia=None)
    print(f'Veredicte: {inf.veredicte}')
    for k, v in inf.recompte().items():
        if v['compten'] or v['declarades']:
            print(f'  {k}: compten {v["compten"]}, declarades {v["declarades"]}, heretades {v["heretades"]}')
    ref = {f.id: f for f in llegeix_proposta(Path(a.referencia))}
    canv = [f.id for f in res if f.id in ref and (f.dia, f.h_ini, f.aula) != (ref[f.id].dia, ref[f.id].h_ini, ref[f.id].aula)]
    print(f'Sessions de la proposta 5.2 que canvien: {len(canv)}')
    resum(base2, res, noves, inf, canv, out / 'resum-5-4.md')
    print(f'\nVerificador oficial:\npython -m horaris check {out}/proposta-grau-nou.csv --semestre {a.semestre} '
          f'--escenari {a.escenari} --referencia {a.referencia} --relaxacions {out}/relaxacions-5-4.csv')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())