"""agent/imprevist.py: pas 5.3, un imprevist sobre la proposta del 5.2.

    python -m agent.imprevist --referencia proposta-torns.csv --sortida lliurament-5-3

Resol, canviant el mínim possible respecte de la referència:
  (a)/(d) aules tancades: les classes que hi havia van a una altra aula lliure (si no n'hi ha, a una altra hora),
  (b) grups que ja no caben: canvien d'aula (una de prou gran, la mateixa per a tot el grup si pot ser),
  (c) sessions cancel·lades: es recuperen un altre dia, dins el termini, amb docent, alumnat i aula lliures.
Cada solució es valida amb el verificador. Només es toquen les classes afectades.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
from pathlib import Path

from agent.tancament import Estat, Incidencia, _a_files
from horaris.check import Colocada, Informe, _col_loca, avalua, passadis
from horaris.model import DIES, MATI, TARDA, Fila, Relaxacio, carrega_base, fmt, llegeix_proposta

RESERVA = 2
FRANGES = [MATI[0] + 60 * i for i in range(13)]


class EstatImprevist(Estat):
    def ordre_aules(self, sids):
        """Preferim aules del mateix passadís que l'actual i les més ajustades (menys canvis, menys sobrants)."""
        actual = self.col[sids[0]].aula
        ref = passadis(actual) if actual else ''
        return sorted(self.base.aules,
                      key=lambda a: (passadis(a) != ref, self.base.aules[a].capacitat, a))


def tancada(base, c):
    return any(c.aula == t.aula and t.data_ini <= c.data <= t.data_fi and c.ini < t.fi and c.fi > t.ini
               for t in base.tancaments)


def reserva_ok(est, ordinaries, aula, data, ini, fi, ignora=()):
    """Si posem una classe a `aula`, queden dues aules ordinàries lliures a cada franja?"""
    if aula not in ordinaries:
        return True
    ign = set(ignora)
    for f0 in FRANGES:
        if ini < f0 + 60 and fi > f0:
            usades = {c.aula for c in est.per_data.get(data, {}).values()
                      if c.s.id not in ign and c.aula in ordinaries and not c.s.sense_espai
                      and c.ini < f0 + 60 and c.fi > f0}
            if aula not in usades and len(usades) + 1 > len(ordinaries) - RESERVA:
                return False
    return True


def candidates_franja(est, sids, fins=None, des=None):
    c0 = est.col[sids[0]]
    dur = c0.s.durada
    lundi = c0.data - dt.timedelta(days=c0.data.weekday())
    out = []
    if fins:                                     # recuperació: dies posteriors fins al termini
        d = des + dt.timedelta(days=1)
        dies = []
        while d <= fins:
            if d.weekday() < 5:
                dies.append(d)
            d += dt.timedelta(days=1)
    else:
        dies = [lundi + dt.timedelta(days=i) for i in range(5)]
    for d in dies:
        for ini in range(MATI[0], 21 * 60 - dur + 1, 30):
            if (d, ini) != (c0.data, c0.ini):
                out.append((d, ini))
    ref = c0.s
    out.sort(key=lambda x: (abs((x[0] - ref.data).days) % 7 != 0, abs((x[0] - ref.data).days),
                            abs(x[1] - ref.ini)))
    return out


def resol_unitat(est, ordinaries, sids, permet_hora=True, aula_preferida=None):
    """Canvia d'aula (mateixa franja) o, si no hi ha cap aula, de franja. Retorna (canvi, motiu_error)."""
    c0 = est.col[sids[0]]
    de = (c0.data, c0.ini, c0.aula)
    fixades = est.fixades(sids)
    plab = any(est.col[s].s.tipus == 'PLAB' for s in sids)
    ordre = est.ordre_aules(sids)
    if aula_preferida:
        ordre = [aula_preferida] + [a for a in ordre if a != aula_preferida]
    for a in ordre:
        c = est.col[sids[0]]
        if a != c.aula and est.valida(sids, c.data, c.ini, a, moguda=False) \
                and reserva_ok(est, ordinaries, a, c.data, c.ini, c.fi, sids):
            est.mou(sids, c.data, c.ini, a)
            return ('aula', de, (c.data, c.ini, a), fixades), ''
    if plab:
        return None, 'PLAB: cap aula lliure (no es mou d\'hora)'
    if not permet_hora:
        return None, 'cap aula lliure'
    if not est.pot_canviar_hora(sids):
        return None, 'sessió fixada: no es pot moure d\'hora'
    for d, ini in est.franges(sids):
        for a in ordre:
            dur = c0.s.durada
            if est.valida(sids, d, ini, a, moguda=True) and reserva_ok(est, ordinaries, a, d, ini, ini + dur, sids):
                est.mou(sids, d, ini, a)
                return ('hora', de, (d, ini, a), fixades), ''
    return None, 'cap aula ni franja lliure'


def recupera(est, ordinaries, sid, fins):
    """Sessió cancel·lada: nova data (posterior, fins al termini) amb tot lliure."""
    s = est.base.sessions[sid]
    est.col[sid] = Colocada(s, s.data, s.ini, '')          # present però sense posició (no entra a per_data)
    sids = [sid]
    for d, ini in candidates_franja(est, sids, fins=fins, des=s.data):
        for a in est.ordre_aules(sids):
            if est.valida(sids, d, ini, a, moguda=True) and reserva_ok(est, ordinaries, a, d, ini, ini + s.durada, sids):
                est.mou(sids, d, ini, a)
                return ('recuperacio', (s.data, s.ini, ''), (d, ini, a), ()), ''
    return None, 'cap data lliure'


def resol(paquet, escenari, referencia, semestre=2):
    base = carrega_base(Path(paquet), semestre=semestre, escenari=Path(escenari))
    ref = [f for f in llegeix_proposta(Path(referencia)) if f.id in base.sessions]
    ordinaries = {a for a, x in base.aules.items() if x.ordinaria}
    sense_canc = [f for f in ref if f.id not in base.cancellades]
    col = _col_loca(base, sense_canc, Informe())
    est = EstatImprevist(base, col, Incidencia('', dt.date.min, dt.date.min))

    canvis, sense = [], []

    # (c) recuperar sessions cancel·lades (primer, perquè ocupen franja)
    for sid, fins in base.cancellades.items():
        ch, motiu = recupera(est, ordinaries, sid, fins)
        (canvis if ch else sense).append((sid, ch) if ch else (sid, motiu))

    # (a)(d) aules tancades + (b) grups que no hi caben: unitats afectades
    afectades = collections.OrderedDict()
    for sid in base.ordre:
        c = est.col.get(sid)
        if c is None or sid in base.cancellades or c.s.sense_espai or not c.aula:
            continue
        motiu = ''
        if tancada(base, c):
            motiu = 'tancada'
        elif c.aula in base.aules and c.s.alumnes > 0:
            n = sum(est.col[x].s.alumnes for x in est.grups[c.s.unitat] if est.col[x].aula == c.aula)
            if n > base.aules[c.aula].capacitat and not (c.s.fixada and c.s.aula == c.aula):
                motiu = 'aforament'
        if motiu:
            afectades.setdefault(c.s.unitat, [motiu, est.grups[c.s.unitat]])
    # grups que creixen: es mira per activitat per intentar una sola aula per a tot el grup
    per_act = collections.defaultdict(list)
    for u, (motiu, sids) in afectades.items():
        per_act[(est.col[sids[0]].s.activitat, motiu)].append(sids)
    for (act, motiu), llista in per_act.items():
        triada = None
        if motiu == 'aforament':
            for a in est.ordre_aules(llista[0]):
                if all(est.valida(g, est.col[g[0]].data, est.col[g[0]].ini, a, False)
                       and reserva_ok(est, ordinaries, a, est.col[g[0]].data, est.col[g[0]].ini,
                                      est.col[g[0]].fi, g) for g in llista):
                    triada = a
                    break
        for g in llista:
            ch, err = resol_unitat(est, ordinaries, g, aula_preferida=triada)
            if ch:
                canvis.append((motiu, g, ch))
            else:
                sense.append((g, err))
    return base, ref, est, canvis, sense


def a_fitxers(base, est, ref):
    out = []
    for i, sid in enumerate(base.ordre, start=2):
        c = est.col[sid]
        data = c.data.isoformat() if sid in base.cancellades else ''
        out.append(Fila(sid, DIES[c.data.weekday()], fmt(c.ini), c.aula, i, data))
    return out


def relaxacions(base, canvis, files):
    """R1-FIXADA / R7-PLAB per les sessions fixades amb canvi d'aula + R1-TORN heretat del 5.2."""
    from agent.informe52 import relaxacions as rel_torn
    fix, plab = [], []
    for item in canvis:
        if len(item) != 3:
            continue
        for s in item[1]:
            x = base.sessions[s]
            if x.tipus == 'PLAB':
                plab.append(s)
            elif x.fixada and x.aula:
                fix.append(s)
    out = []
    if fix:
        out.append({'restriccio': 'R1-FIXADA', 'sessions': '|'.join(sorted(fix)),
                    'justificacio': "Sessions fixades de GEI 1r/2n a una aula tancada per l'imprevist "
                                    "(R3-TANCADA no es pot relaxar): canvien d'aula, mateix dia i hora."})
    if plab:
        out.append({'restriccio': 'R7-PLAB', 'sessions': '|'.join(sorted(plab)),
                    'justificacio': "PLAB a Q3/0013, tancada per l'imprevist (R3-TANCADA no es pot relaxar): "
                                    "canvien d'aula, mateix dia i hora."})
    return out + rel_torn(base, files)


def escriu(path, files):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['id_sessio', 'dia', 'h_ini', 'aula', 'data'])
        for r in files:
            w.writerow([r.id, r.dia, r.h_ini, r.aula, r.data])


def registre(base, canvis, data_avis):
    motius = {'tancada': "aula tancada per l'imprevist", 'aforament': 'el grup ja no hi cap (més alumnes)'}
    rows = []
    for item in canvis:
        if len(item) == 2:                              # recuperació
            sid, ch = item
            motiu = 'sessió cancel·lada: es recupera dins el termini'
            sids = [sid]
        else:
            m, sids, ch = item
            motiu = motius.get(m, m)
        tipus, de, a, _ = ch
        for sid in sids:
            s = base.sessions[sid]
            rows.append({'id_sessio': sid, 'assignatura': f'{s.codi} {s.grup}', 'tipus_canvi': tipus,
                         'de': f'{de[0]} {fmt(de[1])} {de[2] or "-"}', 'a': f'{a[0]} {fmt(a[1])} {a[2]}',
                         'motiu': motiu, 'afecta_docents': '|'.join(sorted(s.docents)) or '(sense docent al llistat)',
                         'afecta_alumnat': '|'.join(s.cohorts), 'avisar': 'docent, alumnat, Gestió Acadèmica',
                         'data_avis': data_avis.isoformat()})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m agent.imprevist')
    ap.add_argument('--paquet', default='paquet')
    ap.add_argument('--escenari', default='paquet/escenaris/contingencies')
    ap.add_argument('--referencia', default='proposta-torns.csv')
    ap.add_argument('--semestre', type=int, default=2)
    ap.add_argument('--sortida', default='lliurament-5-3')
    a = ap.parse_args(argv)
    out = Path(a.sortida)
    out.mkdir(parents=True, exist_ok=True)
    base, ref, est, canvis, sense = resol(a.paquet, a.escenari, a.referencia, a.semestre)
    r0 = _col_loca(base, ref, Informe())
    files = a_fitxers(base, est, ref)
    escriu(out / 'proposta-imprevist.csv', files)
    rel = relaxacions(base, canvis, files)
    with open(out / 'relaxacions-5-3.csv', 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['restriccio', 'sessions', 'justificacio'])
        w.writeheader()
        w.writerows(rel)
    reg = registre(base, canvis, dt.date.today())
    if reg:
        with open(out / 'registre-canvis-5-3.csv', 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(reg[0]))
            w.writeheader()
            w.writerows(reg)
    rels = [Relaxacio(r['restriccio'], frozenset(r['sessions'].split('|')), r['justificacio']) for r in rel]
    inf = avalua(base, files, rels, referencia=ref)
    print(f'Veredicte: {inf.veredicte}')
    for k, v in inf.recompte().items():
        if v['compten'] or v['declarades']:
            print(f'  {k}: compten {v["compten"]}, declarades {v["declarades"]}, heretades {v["heretades"]}')
    n_h = sum(1 for sid in base.ordre if sid in r0 and (est.col[sid].data, est.col[sid].ini) != (r0[sid].data, r0[sid].ini))
    n_a = sum(1 for sid in base.ordre if sid in r0 and est.col[sid].aula != r0[sid].aula)
    print(f'Canvis respecte del 5.2: {n_h} sessions canvien de dia/hora · {n_a} canvien d\'aula')
    for s_, m in sense:
        print('  SENSE SOLUCIÓ:', s_, m)
    print(f'\nFitxers a {out}/. Verificador oficial:')
    print(f'python -m horaris check {out}/proposta-imprevist.csv --semestre {a.semestre} '
          f'--escenari {a.escenari} --referencia {a.referencia} '
          f'{"--relaxacions " + str(out) + "/relaxacions-5-3.csv " if rel else ""}'
          f'--json {out}/informe-5-3.json --violacions {out}/violacions-5-3.csv')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())