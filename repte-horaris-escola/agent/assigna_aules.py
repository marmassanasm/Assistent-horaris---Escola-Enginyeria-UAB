"""agent/assigna_aules.py: pas 5.1, aula per a cada sessió amb l'horari d'avui (sense moure dia ni hora).

    python -m agent.assigna_aules --proposta paquet/proposta_partida.csv --sortida proposta-aules.csv
    python -m horaris check proposta-aules.csv --semestre 2 --nomes-aules

Estratègia: per activitat (mateix grup, dia i hora tota la setmana) es tria UNA aula vàlida per a totes les
seves sessions (aula base estable). Ordre: les més grans primer; aula = la del grup si ja en té, després el
mateix passadís, després la més ajustada. Respecta aforament, tipus, solapaments i les 2 aules lliures (R8).
No es toquen: PLAB, dobles titulacions (sense espai) ni sessions fixades que ja tenen aula a l'aulari.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
from pathlib import Path

from agent.tancament import Estat, Incidencia, _a_files, escriu_proposta
from horaris.check import Informe, _col_loca, _espai_ok
from horaris.model import MATI, a_traslladar, carrega_base, llegeix_proposta

FRANGES = [MATI[0] + 60 * i for i in range(13)]


def necessita_aula(base, c) -> bool:
    s = c.s
    if s.sense_espai or s.tipus == 'PLAB':
        return False
    if s.fixada and s.aula and not a_traslladar(s.aula):
        return False
    if not c.aula:
        return True
    if c.aula not in base.aules:
        return a_traslladar(c.aula)          # J -> s'ha de portar a l'aulari; B3/QC es queden
    return not _espai_ok(base, s, c.aula)


def reserva_ok(est, grups, aula, ordinaries, ocup) -> bool:
    if aula not in ordinaries:
        return True
    for g in grups:
        c = est.col[g[0]]
        for f0 in FRANGES:
            if c.ini < f0 + 60 and c.fi > f0:
                oc = ocup[(c.data, f0)]
                if aula not in oc and len(oc) + 1 > len(ordinaries) - 2:
                    return False
    return True


def posa(est, grups, aula, ordinaries, ocup) -> None:
    for g in grups:
        c0 = est.col[g[0]]
        for sid in g:
            c = est.col[sid]
            est.mou([sid], c.data, c.ini, aula)
        if aula in ordinaries:
            for f0 in FRANGES:
                if c0.ini < f0 + 60 and c0.fi > f0:
                    ocup[(c0.data, f0)].add(aula)


def assigna(paquet: Path, proposta: Path, semestre: int | None = 2, refresca: bool = False, escenari: Path | None = None):
    base = carrega_base(paquet, semestre=semestre, escenari=escenari)
    files = [f for f in llegeix_proposta(proposta) if f.id in base.sessions]
    col = _col_loca(base, files, Informe())
    est = Estat(base, col, Incidencia('', dt.date.min, dt.date.min))
    ordinaries = {a for a, x in base.aules.items() if x.ordinaria}

    # 1. quines classes (unitats) cal assignar? es buiden i es tornen a col·locar
    pendents: dict[str, list[str]] = {}
    for unitat, sids in est.grups.items():
        cs = [est.col[s] for s in sids]
        cap_sobrat = False
        aules = {c.aula for c in cs if c.aula in base.aules and not c.s.sense_espai}
        if len(aules) == 1:
            a = next(iter(aules))
            cap_sobrat = sum(c.s.alumnes for c in cs if not c.s.sense_espai) > base.aules[a].capacitat
            if cap_sobrat and any(c.s.fixada and c.s.aula for c in cs):
                cap_sobrat = False                 # heretat: fixada amb aula, no es pot canviar
        moguda = (refresca and any((c.data, c.ini) != (c.s.data, c.s.ini) for c in cs) and not any(c.s.fixada for c in cs)
                  and not all(c.aula in base.aules and base.aules[c.aula].tipus == 'Aules informàtiques' for c in cs))
        if any(necessita_aula(base, c) for c in cs) or cap_sobrat or moguda:
            pendents[unitat] = list(sids)
    for sids in pendents.values():
        for sid in sids:
            c = est.col[sid]
            est.mou([sid], c.data, c.ini, '')

    ocup: dict[tuple, set] = collections.defaultdict(set)
    for c in est.col.values():
        if c.aula in ordinaries and not c.s.sense_espai:
            for f0 in FRANGES:
                if c.ini < f0 + 60 and c.fi > f0:
                    ocup[(c.data, f0)].add(c.aula)

    # 2. per activitat, la mes gran primer
    per_act: dict[str, list[str]] = collections.defaultdict(list)
    for unitat, sids in pendents.items():
        per_act[est.col[sids[0]].s.activitat or unitat].append(unitat)
    ordre = sorted(per_act, key=lambda a: -max(est.col[s].s.alumnes for u in per_act[a] for s in pendents[u]))

    sense: list[str] = []
    for act in ordre:
        grups = [pendents[u] for u in per_act[act]]
        triat = None
        for a in est.ordre_aules(grups[0]):
            if all(est.valida(g, est.col[g[0]].data, est.col[g[0]].ini, a, False) for g in grups) \
                    and reserva_ok(est, grups, a, ordinaries, ocup):
                triat = a
                break
        if triat:
            posa(est, grups, triat, ordinaries, ocup)
            continue
        for g in grups:                            # alternativa: una aula per sessio
            c0 = est.col[g[0]]
            for a in est.ordre_aules(g):
                if est.valida(g, c0.data, c0.ini, a, False) and reserva_ok(est, [g], a, ordinaries, ocup):
                    posa(est, [g], a, ordinaries, ocup)
                    break
            else:
                sense.extend(g)
    return base, _a_files(base, est.col), sense, len(pendents)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='python -m agent.assigna_aules')
    ap.add_argument('--proposta', default='paquet/proposta_partida.csv')
    ap.add_argument('--paquet', default='paquet')
    ap.add_argument('--semestre', type=int, default=2)
    ap.add_argument('--sortida', default='proposta-aules.csv')
    a = ap.parse_args(argv)
    base, files, sense, n = assigna(Path(a.paquet), Path(a.proposta), a.semestre)
    escriu_proposta(Path(a.sortida), files)
    print(f'Classes (unitats) reassignades: {n} · sessions que no he pogut col·locar: {len(sense)}')
    if sense:
        print('Primeres sense aula:', ', '.join(sense[:15]))
    print(f'Ara: python -m horaris check {a.sortida} --semestre {a.semestre} --nomes-aules')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())