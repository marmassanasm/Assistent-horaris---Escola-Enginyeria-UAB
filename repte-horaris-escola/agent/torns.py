"""agent/torns.py: pas 5.2, torns nous (1r i 2n al matí, 3r/4t/dobles/màsters a la tarda).

    python -m agent.torns --sortida proposta-torns.csv
    python -m horaris check proposta-torns.csv --semestre 2

Com funciona (en paraules senzilles):
  1. Agrupa les classes en "blocs": una activitat (mateix grup, dia i hora tota la setmana) es mou sencera.
     Si dues activitats comparteixen classe, es mouen juntes.
  2. Només es mouen els blocs que avui són al torn equivocat. La resta es queda tal com és.
  3. Un solucionador (OR-Tools CP-SAT) tria dia i hora nous per a cada bloc que cal moure, de manera que:
       - sigui dins del torn i de la finestra horària,
       - no caigui en festiu ni en aturada del calendari,
       - no coincideixi amb cap altra classe del mateix docent ni del mateix alumnat (ni amb un PLAB de la
         mateixa assignatura),
       - en cap moment hi hagi més classes alhora que aules ordinàries disponibles (19, deixant-ne 2 de reserva),
         ni més classes grans que aules grans.
     I intenta moure el mínim possible (mateix dia, hora propera).
  4. Després s'assignen aules (el mateix mètode del 5.1) a tot el que s'ha mogut.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import sys
import time
from pathlib import Path

from ortools.sat.python import cp_model

from horaris.check import _alumnat_comparteix
from horaris.model import DIES, MATI, TARDA, carrega_base, fmt, llegeix_proposta

RESERVA = 2
PES_FORATS = 1
STEP_TIPIC = 60


class Bloc:
    def __init__(self, bid, ses):
        self.id = bid
        self.ses = ses
        self.weeks = frozenset(s.data.isocalendar()[:2] for s in ses)
        s0 = ses[0]
        self.dur = s0.durada
        self.odia = s0.data.weekday()
        self.oini = s0.ini
        self.fixed = any(s.fixada for s in ses)
        self.torns = {s.torn for s in ses}
        self.mover = False
        self.alumnes = 0
        self.demand = None          # 'ord' | 'info' | None

    def n_ses(self):
        return len(self.ses)


def construeix_blocs(base):
    par = {}

    def f(x):
        while par.setdefault(x, x) != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    per_unitat = collections.defaultdict(list)
    for s in base.sessions.values():
        per_unitat[s.unitat].append(s)
    for l in per_unitat.values():
        a = f(l[0].activitat)
        for s in l[1:]:
            par[f(s.activitat)] = a
    grups = collections.defaultdict(list)
    for sid in base.ordre:
        s = base.sessions[sid]
        grups[f(s.activitat)].append(s)
    blocs = [Bloc(i, l) for i, l in enumerate(grups.values())]
    for b in blocs:
        assert len({(s.dia, s.ini, s.durada) for s in b.ses}) == 1, b.ses[0].id
    return blocs


def torn_ok(s):
    return (s.ini < MATI[1]) == (s.torn == 'mati')


def dins_finestra(ini, fi):
    return any(a <= ini and fi <= b for a, b in (MATI, TARDA))


def demanda(base, b):
    """'ord' si la classe pot consumir una aula ordinària, 'info' si va a una aula d'informàtica, None si no."""
    if all(s.sense_espai or s.tipus == 'PLAB' for s in b.ses):
        return None
    s0 = next(s for s in b.ses if not s.sense_espai and s.tipus != 'PLAB')
    if s0.aula in base.aules:
        t = base.aules[s0.aula].tipus
        if t == 'Aules informàtiques':
            return 'info'
        if t != 'Aules docents' and not b.mover:
            return None            # es queda en un seminari / laboratori on ja és
    return 'ord'


def alumnes_bloc(b, base):
    per_u = collections.defaultdict(int)
    for s in b.ses:
        per_u[(s.unitat, s.data)] += s.alumnes
    n = max(per_u.values()) if per_u else 0
    s0 = b.ses[0]
    if s0.aula in base.aules and not b.mover:
        n = min(n, base.aules[s0.aula].capacitat)
    return n


def conflicte(sa, sb):
    if sa.docents & sb.docents:
        return True
    if _alumnat_comparteix(sa, sb):
        return True
    tip = {sa.tipus, sb.tipus}
    return sa.codi == sb.codi and 'PLAB' in tip and bool(tip & {'TE', 'PAUL'})


def parelles_en_conflicte(blocs):
    """Parelles de blocs que no poden coincidir en el temps (docent, alumnat o PLAB), si comparteixen setmana."""
    idx = collections.defaultdict(set)
    for b in blocs:
        perfils = {(s.codi, s.grup, s.tipus, s.cohorts, s.docents) for s in b.ses}
        b.perfils = [next(s for s in b.ses if (s.codi, s.grup, s.tipus, s.cohorts, s.docents) == p) for p in perfils]
        for s in b.perfils:
            for d in s.docents:
                idx[('d', d)].add(b.id)
            for c in s.cohorts:
                idx[('c', c)].add(b.id)
            idx[('k', s.codi)].add(b.id)
    cand = set()
    for ids in idx.values():
        l = sorted(ids)
        for i, x in enumerate(l):
            for y in l[i + 1:]:
                cand.add((x, y))
    out = []
    for x, y in cand:
        a, b = blocs[x], blocs[y]
        if not (a.weeks & b.weeks):
            continue
        if any(conflicte(sa, sb) for sa in a.perfils for sb in b.perfils):
            out.append((x, y))
    return out


def opcions(base, b, grid):
    """(dia, inici) possibles per a un bloc a moure: dins torn i finestra, calendari ok."""
    turn = next(iter(b.torns))
    lo, hi = MATI if turn == 'mati' else TARDA
    if grid == 'tipic':
        a0 = lo if turn == 'mati' else 15 * 60
        starts = list(range(a0, hi - b.dur + 1, 60))
    else:
        starts = list(range(lo, hi - b.dur + 1, 30))
    if lo <= b.oini and b.oini + b.dur <= hi and b.oini not in starts:
        starts.append(b.oini)
    out = []
    for d in range(5):
        for st in starts:
            if not dins_finestra(st, st + b.dur):
                continue
            ok = True
            for s in b.ses:
                data = s.data + dt.timedelta(days=d - s.data.weekday())
                moguda = (data, st) != (s.data, s.ini)
                if not moguda:
                    continue
                if data != s.data and data in base.dies_sense_classe:
                    ok = False
                    break
                if any(st < y and st + b.dur > x for x, y in base.aturades.get(data, ())) and not (
                        data == s.data and any(s.ini < y and s.fi > x for x, y in base.aturades.get(s.data, ()))):
                    ok = False
                    break
            if ok:
                out.append((d, st))
    return out


def descarta_infactibles(blocs, mm, ops_de):
    """Si un grup de blocs que es molesten entre ells no té cap manera de col·locar-se, es deixa a la seva
    hora (es declararà) el bloc amb menys opcions, i es torna a provar."""
    par = {}

    def f(x):
        while par.setdefault(x, x) != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    for i in ops_de:
        f(i)
    for x, y in mm:
        par[f(x)] = f(y)
    comp = collections.defaultdict(list)
    for i in ops_de:
        comp[f(i)].append(i)
    adj = collections.defaultdict(int)
    for x, y in mm:
        adj[x] += 1
        adj[y] += 1
    sense = []
    for ids in comp.values():
        if len(ids) < 2:
            continue
        m = cp_model.CpModel()
        iv = {}
        for i in ids:
            tv = [d * 1440 + st for d, st in ops_de[i]]
            tt = m.NewIntVarFromDomain(cp_model.Domain.FromValues(tv), 't')
            iv[i] = m.NewFixedSizeIntervalVar(tt, blocs[i].dur, 'i')
        for x, y in mm:
            if x in iv and y in iv:
                m.AddNoOverlap([iv[x], iv[y]])
        s = cp_model.CpSolver()
        s.parameters.max_time_in_seconds = 20
        s.parameters.num_workers = 8
        if s.Solve(m) == cp_model.INFEASIBLE:
            pitjor = min(ids, key=lambda i: (len(ops_de[i]), -adj[i]))
            sense.append(blocs[pitjor])
    return sense


def cost_forats(b, ops, veins_b):
    """Per a cada (dia, hora): hores mortes (min) respecte de la classe més propera del mateix alumnat aquell dia."""
    nb = [v for v in veins_b if (v.weeks & b.weeks) and any(
        _alumnat_comparteix(sa, sb) for sa in b.perfils for sb in v.perfils)]
    out = []
    for d, st in ops:
        mati_b = st + b.dur <= MATI[1]
        millor = None
        for v in nb:
            if v.odia != d or ((v.oini + v.dur <= MATI[1]) != mati_b):
                continue
            g = v.oini - (st + b.dur) if v.oini >= st + b.dur else st - (v.oini + v.dur)
            if g >= 0 and (millor is None or g < millor):
                millor = g
        out.append(millor or 0)
    return out


def resol_horaris(base, blocs, grid='tipic', temps=180, ampliats=None, verbose=True, amb_capacitat=True, families=('ord', 'grans', 'info')):
    """Tria (dia, hora) per als blocs mòbils. Retorna {bloc_id: (dia, ini)} o None si no hi ha solució."""
    t0 = time.time()
    movers = [b for b in blocs if b.mover]
    ordin = [a for a in base.aules.values() if a.ordinaria]
    cap_ord = len(ordin) - RESERVA
    for b in blocs:
        b.alumnes = alumnes_bloc(b, base)
        b.demand = demanda(base, b)
    parelles = parelles_en_conflicte(blocs)
    descartats = []
    while True:
        veins = collections.defaultdict(list)
        mm = []
        for x, y in parelles:
            a, b = blocs[x], blocs[y]
            if a.mover and b.mover:
                mm.append((x, y))
            elif a.mover:
                veins[a.id].append(b)
            elif b.mover:
                veins[b.id].append(a)
        ops_de = {}
        sense = []
        for b in blocs:
            if not b.mover:
                continue
            ops = [o for o in opcions(base, b, grid)
                   if not any(v.odia == o[0] and o[1] < v.oini + v.dur and v.oini < o[1] + b.dur
                              for v in veins[b.id] if v.weeks & b.weeks)]
            if ops:
                ops_de[b.id] = ops
            else:
                sense.append(b)
        if not sense:
            sense = descarta_infactibles(blocs, mm, ops_de)
        if not sense:
            break
        for b in sense:
            b.mover = False
            descartats.append(b)
    if verbose:
        print(f'  blocs {len(blocs)} · a moure {sum(b.mover for b in blocs)} · parelles en conflicte {len(parelles)} '
              f'(mòbil-mòbil {len(mm)}) · sense opcions (es queden): {len(descartats)}')
    movers = [b for b in blocs if b.mover]
    for b in blocs:
        b.alumnes = alumnes_bloc(b, base)
        b.demand = demanda(base, b)

    m = cp_model.CpModel()
    var = {}
    nou, vell, actiu = {}, {}, {}
    cost_terms = []
    PENAL = 5000
    for b in movers:
        ops = ops_de[b.id]
        k = m.NewIntVar(0, len(ops) - 1, f'k{b.id}')
        tv = [d * 1440 + st for d, st in ops]
        tt = m.NewIntVarFromDomain(cp_model.Domain.FromValues(tv), f't{b.id}')
        m.AddElement(k, tv, tt)
        forats = cost_forats(b, ops, veins[b.id])
        torn_nou_mati = next(iter(b.torns)) == 'mati'
        if (b.oini < MATI[1]) != torn_nou_mati:      # canvia de torn: es trasllada 6,5 h perquè conservi la forma
            objectiu = b.oini - 390 if torn_nou_mati else b.oini + 390
        else:
            objectiu = b.oini
        costs = [b.n_ses() * (20 * (d != b.odia) + abs(st - objectiu) // 6 + PES_FORATS * g // 3)
                 for (d, st), g in zip(ops, forats)]
        c = m.NewIntVar(0, max(costs), f'c{b.id}')
        m.AddElement(k, costs, c)
        act = m.NewBoolVar(f'a{b.id}')              # 1 = el bloc es mou; 0 = es queda a la seva hora d'avui
        cost_terms.append(c)
        cost_terms.append(PENAL * b.n_ses() * act.Not())
        var[b.id] = (tt, ops, k)
        actiu[b.id] = act
        nou[b.id] = m.NewOptionalFixedSizeIntervalVar(tt, b.dur, act, f'n{b.id}')
        vell[b.id] = m.NewOptionalFixedSizeIntervalVar(b.odia * 1440 + b.oini, b.dur, act.Not(), f'v{b.id}')
    for x, y in mm:
        m.AddNoOverlap([nou[x], nou[y]])
        m.AddNoOverlap([nou[x], vell[y]])
        m.AddNoOverlap([vell[x], nou[y]])

    # aules d'informàtica (només 2): cal triar-ne una per a cada classe, perquè n'hi ha de fixades en una concreta
    info_rooms = sorted(a.aula for a in base.aules.values() if a.tipus == 'Aules informàtiques')
    info_nou, info_vell, info_sel = {}, {}, {}
    for b in movers:
        if b.demand != 'info':
            continue
        sel = [m.NewBoolVar(f'r{b.id}_{r}') for r in range(len(info_rooms))]
        m.AddExactlyOne(sel)
        info_sel[b.id] = sel
        info_nou[b.id] = {}
        for ri, room in enumerate(info_rooms):
            lit = m.NewBoolVar(f'ln{b.id}_{ri}')
            m.AddBoolAnd([actiu[b.id], sel[ri]]).OnlyEnforceIf(lit)
            m.AddBoolOr([actiu[b.id].Not(), sel[ri].Not()]).OnlyEnforceIf(lit.Not())
            info_nou[b.id][room] = m.NewOptionalFixedSizeIntervalVar(var[b.id][0], b.dur, lit, f'in{b.id}_{ri}')
        info_vell[b.id] = (b.ses[0].aula, vell[b.id])

    # capacitat per setmana: totes les classes que demanen aula ordinària, les grans i les d'informàtica
    caps = sorted({a.capacitat for a in ordin})
    nivells = [(c, sum(1 for a in ordin if a.capacitat > c)) for c in caps[:-1]]
    info_cap = sum(1 for a in base.aules.values() if a.tipus == 'Aules informàtiques')
    setmanes = sorted({w for b in blocs for w in b.weeks})
    vistos = set()
    for w in (setmanes if amb_capacitat else []):
        actius = [b for b in blocs if w in b.weeks and b.demand]
        sig = frozenset(b.id for b in actius)
        if sig in vistos:
            continue
        vistos.add(sig)

        def ivs(b):
            if b.mover:
                return [nou[b.id], vell[b.id]]
            return [m.NewFixedSizeIntervalVar(b.odia * 1440 + b.oini, b.dur, f'f{b.id}_{len(vistos)}')]
        ordb = [b for b in actius if b.demand == 'ord']
        if ordb and any(b.mover for b in ordb):
            if 'ord' in families:
                l = [x for b in ordb for x in ivs(b)]
                m.AddCumulative(l, [1] * len(l), cap_ord)
            for c, n in (nivells if 'grans' in families else []):
                grans = [b for b in ordb if b.alumnes > c]
                if grans and any(b.mover for b in grans):
                    l = [x for b in grans for x in ivs(b)]
                    m.AddCumulative(l, [1] * len(l), n)
        if 'info' in families:
            for room in info_rooms:
                l = []
                for b in actius:
                    if b.demand != 'info':
                        continue
                    if b.mover:
                        l.append(info_nou[b.id][room])
                        if info_vell[b.id][0] == room:
                            l.append(info_vell[b.id][1])
                    elif b.ses[0].aula == room:
                        l.append(m.NewFixedSizeIntervalVar(b.odia * 1440 + b.oini, b.dur, f'if{b.id}_{room}_{len(vistos)}'))
                if len(l) > 1 and any(isinstance(x, type(None)) is False for x in l):
                    m.AddNoOverlap(l)

    m.Minimize(sum(cost_terms))
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = temps
    s.parameters.num_workers = 8
    s.parameters.log_search_progress = False
    st = s.Solve(m)
    if verbose:
        print(f'  CP-SAT: {s.StatusName(st)} · cost {s.ObjectiveValue() if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) else "-"} '
              f'· {time.time() - t0:.0f}s')
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {'estat': s.StatusName(st)}
    res = {}
    es_queden = []
    for b in movers:
        tt, ops, k = var[b.id]
        if s.Value(actiu[b.id]):
            res[b.id] = ops[s.Value(k)]
        else:
            es_queden.append(b.id)
    res['_descartats'] = [b.id for b in descartats] + es_queden
    res['_sales'] = {bid: info_rooms[[s.Value(x) for x in sel].index(1)] for bid, sel in info_sel.items()
                     if s.Value(actiu[bid])}
    return res


def construeix_proposta(base, blocs, res):
    nous = {}
    sales = res.get('_sales', {})
    for b in blocs:
        if b.id in res and not isinstance(b.id, str) and b.id not in ('_descartats', '_sales'):
            d, st = res[b.id]
            for s in b.ses:
                nous[s.id] = (DIES[d], fmt(st), sales.get(b.id, s.aula))
    files = []
    for sid in base.ordre:
        s = base.sessions[sid]
        dia, h, aula = nous.get(sid, (s.dia, fmt(s.ini), s.aula))
        files.append((sid, dia, h, aula))
    return files


def escriu(path, files):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['id_sessio', 'dia', 'h_ini', 'aula', 'data'])
        for r in files:
            w.writerow([*r, ''])


def permesos_sessio(base, s, turn, durada):
    """(dia, inici) on una sessió pot anar pel calendari (festius, aturades), amb graella de 30 min."""
    lo, hi = MATI if turn == 'mati' else TARDA
    out = set()
    for d in range(5):
        for st in range(lo, hi - durada + 1, 30):
            data = s.data + dt.timedelta(days=d - s.data.weekday())
            if (data, st) == (s.data, s.ini):
                out.add((d, st))
                continue
            if data != s.data and data in base.dies_sense_classe:
                continue
            if any(st < y and st + durada > x for x, y in base.aturades.get(data, ())) and not (
                    data == s.data and any(s.ini < y and s.fi > x for x, y in base.aturades.get(s.data, ()))):
                continue
            out.add((d, st))
    return frozenset(out)


def divideix_per_calendari(base, blocs):
    """Una activitat amb sessions en setmanes especials (avaluació, aturades) es parteix en dos blocs:
    les setmanes normals (es poden moure de dia) i les especials (només d'hora)."""
    out = []
    for b in blocs:
        if not b.mover:
            out.append(b)
            continue
        turn = next(iter(b.torns))
        per_sig = collections.defaultdict(list)
        for s in b.ses:
            per_sig[permesos_sessio(base, s, turn, b.dur)].append(s)
        if len(per_sig) == 1:
            out.append(b)
            continue
        for l in per_sig.values():
            nb = Bloc(0, l)
            nb.mover = True
            out.append(nb)
    for i, b in enumerate(out):
        b.id = i
    return out


def prepara(paquet='paquet', semestre=2):
    base = carrega_base(Path(paquet), semestre=semestre)
    blocs = construeix_blocs(base)
    for b in blocs:
        b.mover = (not b.fixed) and len(b.torns) == 1 and any(
            (not torn_ok(s)) or not dins_finestra(s.ini, s.fi) for s in b.ses)
    return base, divideix_per_calendari(base, blocs)


def fes_proposta(paquet='paquet', semestre=2, temps=180, sortida='proposta-torns.csv', verbose=True):
    """Pas complet: horaris (CP-SAT) + aules. Retorna (base, blocs, res, files_finals, sense_aula)."""
    from agent.assigna_aules import assigna
    from agent.tancament import escriu_proposta
    base, blocs = prepara(paquet, semestre)
    if verbose:
        print(f'Blocs mòbils fora de torn: {sum(b.mover for b in blocs)} '
              f'({sum(b.n_ses() for b in blocs if b.mover)} sessions)')
    res = None
    for grid in ('tipic', 'fi'):
        if verbose:
            print(f'Cercant dia i hora (graella {grid})...')
        base, blocs = prepara(paquet, semestre)
        res = resol_horaris(base, blocs, grid, temps, verbose=verbose)
        if res and 'estat' not in res:
            break
        res = None
    if res is None:
        return None
    tmp = Path(sortida).with_suffix('.horaris.csv')
    escriu(tmp, construeix_proposta(base, blocs, res))
    if verbose:
        print('Assignant aules a les classes mogudes...')
    base2, files, sense, n = assigna(Path(paquet), tmp, semestre, refresca=True)
    escriu_proposta(Path(sortida), files)
    return base, blocs, res, files, sense


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m agent.torns')
    ap.add_argument('--paquet', default='paquet')
    ap.add_argument('--semestre', type=int, default=2)
    ap.add_argument('--sortida', default='proposta-torns.csv')
    ap.add_argument('--temps', type=int, default=180)
    a = ap.parse_args(argv)
    r = fes_proposta(a.paquet, a.semestre, a.temps, a.sortida)
    if r is None:
        print('No he trobat cap solució.')
        return 1
    base, blocs, res, files, sense = r
    print(f'Classes que es queden a la seva hora (no hi ha lloc): '
          f'{sum(len(blocs[i].ses) for i in res["_descartats"])} sessions · sessions sense aula: {len(sense)}')
    print(f'Escrit {a.sortida}. Ara: python -m horaris check {a.sortida} --semestre {a.semestre}')
    return 0


if __name__ == '__main__':
    sys.exit(main())