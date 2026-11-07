"""agent/xat.py: xat amb un LLM compatible amb l'API d'OpenAI (el de l'esdeveniment, servidors del DCC).

El model nomes decideix quina eina cridar i explica el resultat; les dades i la validacio venen sempre del verificador.
"""
from __future__ import annotations

import json

from agent import api

SISTEMA = ("Ets l'assistent d'horaris de l'EEBE (UAB) per a Gestió Acadèmica. Respon sempre en català, breu i clar. "
           "Mai t'inventis dades: fes servir les eines. Cita sempre els id_sessio, dia, hora i aula. "
           "Dóna una solució per bona només si el veredicte és VALIDA o VALIDA AMB RELAXACIONS DECLARADES. "
           "Si hi ha sessions sense solució, digues-ho. No envies avisos: només els redactes. "
           "Dates AAAA-MM-DD; el semestre és de febrer a juny de 2027.")


def _f(nom, desc, props, req=()):
    return {'type': 'function', 'function': {'name': nom, 'description': desc,
            'parameters': {'type': 'object', 'properties': props, 'required': list(req)}}}


S = {'type': 'string'}
EINES = [
    _f('consultaHorari', "Classes d'una titulació i curs. titulacio: GEI, GED, GEQ, GIA, GCIS, GEET, GEST, MRICSE, MEBA; "
       "curs: 1r, 2n, 3r, 4t, M; dia L/M/X/J/V; data AAAA-MM-DD.",
       {'titulacio': S, 'curs': S, 'grup': S, 'dia': S, 'data': S}, ['titulacio']),
    _f('aulesLliures', 'Aules lliures en una data i franja.',
       {'data': S, 'hora_inici': S, 'hora_fi': S, 'places_minim': {'type': 'integer'}}, ['data', 'hora_inici', 'hora_fi']),
    _f('resolImprevist', 'Una aula no es pot fer servir: proposa la solució validada pel verificador i redacta els avisos.',
       {'aula': S, 'data_ini': S, 'data_fi': S, 'motiu': S}, ['aula', 'data_ini']),
    _f('validaHorari', "Veredicte del verificador sobre l'horari actual.", {}),
]


def crida(nom, a):
    if nom == 'consultaHorari':
        return api.horari(a['titulacio'], a.get('curs', ''), a.get('grup', ''), a.get('dia', ''), a.get('data', ''), 40)
    if nom == 'aulesLliures':
        return api.aules_lliures(a['data'], a['hora_inici'], a['hora_fi'], int(a.get('places_minim', 0) or 0))
    if nom == 'resolImprevist':
        r = api.imprevist(api.ImprevistIn(aula=a['aula'], data_ini=a['data_ini'], data_fi=a.get('data_fi', ''),
                                          motiu=a.get('motiu', 'aula no disponible')))
        r['avisos_i_registre'] = r['avisos_i_registre'][:30]
        return r
    if nom == 'validaHorari':
        return api.valida()
    return {'error': f'eina desconeguda: {nom}'}


def respon(client, model, historial, max_voltes=6):
    """historial: llista de {'role','content'} (usuari/assistent). Retorna el text final."""
    ms = [{'role': 'system', 'content': SISTEMA}] + list(historial)
    for _ in range(max_voltes):
        r = client.chat.completions.create(model=model, messages=ms, tools=EINES, temperature=0.2)
        m = r.choices[0].message
        if not getattr(m, 'tool_calls', None):
            return m.content or ''
        ms.append({'role': 'assistant', 'content': m.content or '',
                   'tool_calls': [{'id': t.id, 'type': 'function',
                                   'function': {'name': t.function.name, 'arguments': t.function.arguments}}
                                  for t in m.tool_calls]})
        for t in m.tool_calls:
            try:
                out = json.dumps(crida(t.function.name, json.loads(t.function.arguments or '{}')),
                                 ensure_ascii=False, default=str)
            except Exception as e:
                out = f'error: {e}'
            ms.append({'role': 'tool', 'tool_call_id': t.id, 'content': out[:50000]})
    return "No he pogut acabar la resposta. Prova de reformular la pregunta."