"""agent/api.py: API que fa servir l'agent de Copilot Studio (les 'eines').

    pip install fastapi uvicorn
    uvicorn agent.api:app --port 8000

Documentació interactiva (per provar-ho): http://localhost:8000/docs
El calcul el fa sempre el verificador / el solver; l'agent de Copilot Studio nomes explica el resultat.
"""
from __future__ import annotations

import datetime as dt
import os
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent.informe52 import relaxacions as relaxacions_torn
from agent.tancament import Incidencia, carrega, proposa_solucions, registre_canvis
from horaris.check import Informe, _col_loca, avalua
from horaris.model import DIES, Relaxacio, carrega_base, fmt, hm, llegeix_proposta

PAQUET = Path(os.environ.get('PAQUET', 'paquet'))
PROPOSTA = Path(os.environ.get('PROPOSTA', 'proposta-torns.csv'))
SEMESTRE = 2

app = FastAPI(title='Agent d\'horaris EEBE', version='1.0',
              description='Consulta l\'horari, busca aules lliures, valida propostes i resol imprevistos.',
              servers=[{'url': os.environ.get('URL_PUBLICA', 'http://localhost:8000')}])


@lru_cache(maxsize=1)
def _dades():
    base = carrega_base(PAQUET, semestre=SEMESTRE)
    files = [f for f in llegeix_proposta(PROPOSTA) if f.id in base.sessions]
    return base, files, _col_loca(base, files, Informe())


def _fila(c):
    s = c.s
    return {'id_sessio': s.id, 'data': c.data.isoformat(), 'dia': DIES[c.data.weekday()],
            'hora_inici': fmt(c.ini), 'hora_fi': fmt(c.fi), 'assignatura': f'{s.codi} {s.tipus} {s.grup}',
            'aula': c.aula or '(sense espai)', 'alumnes': s.alumnes, 'docents': sorted(s.docents),
            'titulacions': list(s.cohorts)}


@app.get('/horari', operation_id='consultaHorari', summary='Classes d\'una titulacio i curs (o d\'un grup)')
def horari(titulacio: str, curs: str = '', grup: str = '', dia: str = '', data: str = '', maxim: int = 60):
    """titulacio: GEI, GED, GEQ, GIA, GCIS, GEET+GEST, MRICSE, MEBA... · curs: 1r, 2n, 3r, 4t, M1... ·
    grup: p. ex. 81 (es busca dins del nom del grup) · dia: L/M/X/J/V · data: AAAA-MM-DD."""
    _, _, col = _dades()
    clau = f'{titulacio}:{curs}'.upper() if curs else titulacio.upper() + ':'
    out = []
    for c in sorted(col.values(), key=lambda c: (c.data, c.ini)):
        if not any(h.upper().startswith(clau) for h in c.s.cohorts):
            continue
        if grup and grup not in c.s.grup:
            continue
        if dia and DIES[c.data.weekday()] != dia.upper():
            continue
        if data and c.data.isoformat() != data:
            continue
        out.append(_fila(c))
    return {'total': len(out), 'mostrades': out[:maxim],
            'nota': 'Si total > mostrades, afegeix un filtre (data o dia).' if len(out) > maxim else ''}


@app.get('/aules-lliures', operation_id='aulesLliures', summary='Aules lliures en una data i franja')
def aules_lliures(data: str, hora_inici: str, hora_fi: str, places_minim: int = 0, ordinaries: bool = False):
    base, _, col = _dades()
    d, i, f = dt.date.fromisoformat(data), hm(hora_inici), hm(hora_fi)
    ocupades = {c.aula for c in col.values() if c.data == d and c.aula and c.ini < f and c.fi > i}
    tanc = {t.aula for t in base.tancaments if t.data_ini <= d <= t.data_fi and i < t.fi and f > t.ini}
    lliures = [a for a in base.aules.values() if a.aula not in ocupades | tanc and a.capacitat >= places_minim
               and (a.ordinaria or not ordinaries)]
    lliures.sort(key=lambda a: (a.capacitat, a.aula))
    return {'total': len(lliures), 'aules': [{'aula': a.aula, 'places': a.capacitat, 'tipus': a.tipus} for a in lliures[:40]]}


class ImprevistIn(BaseModel):
    aula: str
    data_ini: str
    data_fi: str = ''
    hora_ini: str = ''
    hora_fi: str = ''
    motiu: str = 'aula no disponible'


@app.post('/imprevist', operation_id='resolImprevist', summary='Aula no disponible: proposa la solucio validada')
def imprevist(inp: ImprevistIn):
    """Troba les classes afectades, proposa on i quan es fan, ho valida amb el verificador i redacta els avisos
    (NO n'envia cap)."""
    try:
        inc = Incidencia.from_dict({'aula': inp.aula, 'data_ini': inp.data_ini, 'data_fi': inp.data_fi or inp.data_ini,
                                    'h_ini': inp.hora_ini, 'h_fi': inp.hora_fi, 'motiu': inp.motiu})
    except Exception as e:
        raise HTTPException(400, f'dades no valides: {e}')
    base0, _, _ = _dades()
    if inp.aula not in base0.aules:
        raise HTTPException(404, f'l\'aula {inp.aula} no existeix a l\'aulari')
    sols = proposa_solucions(PAQUET, PROPOSTA, inc, SEMESTRE)
    best = sols[0]
    base, files0 = carrega(PAQUET, PROPOSTA, inc, SEMESTRE)
    # les excepcions de torn que ja s'havien declarat al 5.2 es mantenen
    torn = [Relaxacio(r['restriccio'], frozenset(r['sessions'].split('|')), r['justificacio'])
            for r in relaxacions_torn(base, best.files)]
    best.informe = avalua(base, best.files, best.relaxacions_obj() + torn, referencia=files0)
    return {'afectades': len(best.canvis) + len(best.sense_solucio), 'solucio': best.resum(),
            'avisos_i_registre': registre_canvis(base, best, inc),
            'altres_opcions': [{'nom': s.nom, 'veredicte': s.veredicte, 'canvis': len(s.canvis),
                                'sense_solucio': len(s.sense_solucio)} for s in sols[1:]],
            'nota': 'Proposta validada pel verificador. Els avisos son esborranys: cal que una persona els revisi i els enviï.'}


@app.get('/valida', operation_id='validaHorari', summary='Veredicte del verificador sobre l\'horari actual')
def valida():
    base, files, _ = _dades()
    rels = [Relaxacio(r['restriccio'], frozenset(r['sessions'].split('|')), r['justificacio'])
            for r in relaxacions_torn(base, files)]
    inf = avalua(base, files, rels)
    return {'veredicte': inf.veredicte,
            'recompte': {k: v for k, v in inf.recompte().items() if v['compten'] or v['declarades']},
            'objectius': inf.objectius}