"""agent/app.py: interficie web per a Gestio Academica.

    pip install streamlit reportlab
    streamlit run agent/app.py

Pestanyes: Imprevist · Horari · PDF · Aules lliures. Tot el calcul el fa el verificador.
"""
from __future__ import annotations

import datetime as dt
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # perque trobi 'agent' i 'horaris'

import pandas as pd
import streamlit as st

from agent import api, estil, pdfs
from horaris.check import Informe, _col_loca
from horaris.model import carrega_base, fmt, llegeix_proposta

st.set_page_config(page_title="Assistent d'horaris EEBE", layout='wide')
estil.aplica()
st.title("Assistent d'horaris - Escola d'Enginyeria UAB")
st.caption("Hackathon 2026 - Mar Massanas")

# ---------------------------------------------------------------- dades i llistes
TITULACIONS = {
    'GEI · Enginyeria Informàtica': ['GEI'],
    'GED · Enginyeria de Dades': ['GED'],
    'GEQ · Enginyeria Química': ['GEQ'],
    'GIA · Intel·ligència Artificial': ['GIA'],
    'GCIS · Gestió de Ciutats Intel·ligents i Sostenibles': ['GCIS'],
    'GEET · Enginyeria Elèctrica i Telecomunicació': ['GEET'],
    'GEST · Gestió (pla GEET+GEST)': ['GEST'],
    'GEET+GEST · Doble grau': ['GEET', 'GEST'],
    'MEBA · Màster en Enginyeria Biològica i Ambiental': ['MEBA'],
    'MET · Màster en Enginyeria de Telecomunicació': ['MET'],
    'MRICSE · Màster RICSE': ['MRICSE'],
}
ORDRE_CURS = {'1r': 1, '2n': 2, '3r': 3, '4t': 4, 'M': 5, '?': 9}
NOM_CURS = {'1r': 'Curs 1r', '2n': 'Curs 2n', '3r': 'Curs 3r', '4t': 'Curs 4t', 'M': 'Màster', '?': 'Sense curs assignat'}


@st.cache_resource(show_spinner='Carregant l\'horari...')
def dades(semestre: int):
    if semestre == 2:
        base, _, col = api._dades()
    else:
        base = carrega_base(api.PAQUET, semestre=1)
        files = [f for f in llegeix_proposta(api.PAQUET / 'proposta_partida.csv') if f.id in base.sessions]
        col = _col_loca(base, files, Informe())
    return base, col


def cohorts_de(col, prefixos):
    return sorted({h for x in col.values() for h in x.s.cohorts if h.split(':')[0] in prefixos and not h.endswith(':?')},
                  key=lambda h: (h.split(':')[0], ORDRE_CURS.get(h.split(':')[1], 9)))


def titulacions_disponibles(col):
    return [t for t, p in TITULACIONS.items() if cohorts_de(col, p)]


def ctx(tit: str):
    """El MET només té classes al 1r quadrimestre (horari de partida); la resta, el 2n semestre (proposta 5.2)."""
    sem = 1 if TITULACIONS[tit] == ['MET'] else 2
    base, col = dades(sem)
    return col, ('1r quadrimestre 2026-27 (horari actual)' if sem == 1 else '2n semestre 2026-27 (proposta 5.2)')


def es_real(x):
    """Descarta sessions fantasma: 0 alumnes o curs desconegut (TITULACIO:?)."""
    return x.s.alumnes > 0 and not any(h.endswith(':?') for h in x.s.cohorts)


TOTES = [t for t in TITULACIONS if cohorts_de(ctx(t)[0], TITULACIONS[t])]

t_imp, t_hor, t_pdf, t_aul, t_bus = st.tabs(['Imprevist', 'Horari', 'PDF', 'Aules lliures', 'Buscador'])

# ---------------------------------------------------------------- imprevist (sempre sobre la proposta del 2n semestre)
with t_imp:
    st.subheader('Una aula no es pot fer servir')
    base2, col2 = dades(2)
    d_min, d_max = min(x.data for x in col2.values()), max(x.data for x in col2.values())
    c1, c2, c3 = st.columns(3)
    aules_l = sorted(base2.aules)
    aula = c1.selectbox('Aula', aules_l, index=aules_l.index('Q3/0013') if 'Q3/0013' in aules_l else 0)
    d1 = c2.date_input('Des del', dt.date(2027, 3, 15), min_value=d_min, max_value=d_max, key='imp_d1')
    d2 = c3.date_input('Fins al', max(dt.date(2027, 3, 19), d1), min_value=d_min, max_value=d_max, key='imp_d2')
    dates_ok = d1 <= d2
    if not dates_ok:
        st.error("La data d'inici ha de ser anterior o igual a la de fi. Canvia-la per poder continuar.")
    motiu = st.text_input('Motiu', 'aula no disponible')
    if st.button('Proposa solució', type='primary', disabled=not dates_ok):
        with st.spinner('Buscant solució i validant-la amb el verificador...'):
            r = api.imprevist(api.ImprevistIn(aula=aula, data_ini=d1.isoformat(), data_fi=d2.isoformat(), motiu=motiu))
        s = r['solucio']
        ok = s['veredicte'] != 'NO VALIDA' and not s['sessions_sense_solucio']
        (st.success if ok else st.error)(f"Veredicte del verificador: {s['veredicte']} · classes afectades: {r['afectades']}")
        st.write(f"Canvis d'aula: {s['cost']['canvis_aula']} · canvis d'hora: {s['cost']['canvis_franja']}")
        if s['sessions_sense_solucio']:
            st.warning('Sessions sense solució:')
            st.dataframe(pd.DataFrame(s['sessions_sense_solucio']))
        noms_i = pdfs.noms_assignatures(api.PAQUET)
        QUE = {'R1-FIXADA': "Sessió fixada (no s'hauria de moure) que canvia d'aula",
               'R7-PLAB': "Laboratori PLAB que canvia d'aula",
               'R1-TORN': 'Sessió fora del seu torn (matí/tarda) respecte de la norma'}
        if s['relaxacions_a_declarar']:
            with st.expander(f"Excepcions a declarar ({len(s['relaxacions_a_declarar'])}) · són {len(s['relaxacions_a_declarar'])} de les {len(r['avisos_i_registre'])} classes del registre"):
                st.caption("Són les regles que la solució incompleix a propòsit perquè no hi havia alternativa millor. "
                           "S'han d'explicar a l'organització perquè el verificador les accepti.")
                ex = []
                for r_ in s['relaxacions_a_declarar']:
                    ids = str(r_['sessions']).split('|')
                    ss = base2.sessions.get(ids[0])
                    ex.append({'regla': r_['restriccio'], 'què vol dir': QUE.get(r_['restriccio'], ''),
                               'assignatura': noms_i.get(ss.codi, ss.codi) if ss else '',
                               'grup': f'{ss.tipus} {ss.grup}' if ss else '', 'id_sessio': r_['sessions'],
                               'justificació': r_['justificacio']})
                st.dataframe(pd.DataFrame(ex), hide_index=True)
        regla_de = {}
        for r_ in s['relaxacions_a_declarar']:
            for i_ in str(r_['sessions']).split('|'):
                regla_de[i_] = r_['restriccio']
        df0 = pd.DataFrame(r['avisos_i_registre'])
        df = df0
        if len(df0):
            def _ini_aula(txt):
                d_, h_, a_ = txt.split(' ', 2)
                return d_, h_, a_
            files_v = []
            for x in df0.itertuples():
                ss = base2.sessions[x.id_sessio]
                d1_, h1_, a1_ = _ini_aula(x.de)
                d2_, h2_, a2_ = _ini_aula(x.a)
                dur = ss.durada
                hm_ = lambda h: int(h[:2]) * 60 + int(h[3:])
                files_v.append({
                    'data': d1_, 'assignatura': noms_i.get(ss.codi, ss.codi), 'tipus': ss.tipus, 'grup': ss.grup,
                    'abans (hora)': f'{h1_}-{fmt(hm_(h1_) + dur)}', 'abans (aula)': a1_,
                    'ara (data)': d2_ if d2_ != d1_ else '(la mateixa)',
                    'ara (hora)': f'{h2_}-{fmt(hm_(h2_) + dur)}', 'ara (aula)': a2_,
                    'tipus de canvi': x.tipus_canvi, 'excepció a declarar': regla_de.get(x.id_sessio, ''), 'docents': x.afecta_docents, 'alumnat': x.afecta_alumnat,
                    'avisar': x.avisar, 'id_sessio': x.id_sessio})
            df = pd.DataFrame(files_v).sort_values(['data', 'abans (hora)']).reset_index(drop=True)
        st.markdown('**Registre de canvis i avisos (esborranys)**')
        st.dataframe(df, hide_index=True)

# ---------------------------------------------------------------- horari
with t_hor:
    st.subheader("Horari d'una o més titulacions i cursos")
    st.caption("Deixa un filtre buit per veure-ho tot. Pots triar-ne més d'un a cada filtre.")
    noms_h = pdfs.noms_assignatures(api.PAQUET)
    c1, c2, c3 = st.columns(3)
    tits_h = c1.multiselect('Titulació', TOTES, default=[TOTES[0]], key='h_tit', placeholder='Totes')
    tits_h = tits_h or TOTES
    # cursos possibles = els de les titulacions triades
    cursos_poss = sorted({h.split(':')[1] for t_ in tits_h for h in cohorts_de(ctx(t_)[0], TITULACIONS[t_])},
                         key=lambda c: ORDRE_CURS.get(c, 9))
    etiquetes = [NOM_CURS.get(c, c) for c in cursos_poss]
    cursos_h = c2.multiselect('Curs', etiquetes, key='h_curs', placeholder='Tots')
    dies_h = c3.multiselect('Dia', ['L', 'M', 'X', 'J', 'V'], key='h_dia', placeholder='Tots')
    rows = {}
    periodes = set()
    for t_ in tits_h:
        col_t, txt = ctx(t_)
        periodes.add(txt)
        triats = [h for h in cohorts_de(col_t, TITULACIONS[t_])
                  if not cursos_h or NOM_CURS.get(h.split(':')[1], h) in cursos_h]
        for x in col_t.values():
            if not any(h in triats for h in x.s.cohorts):
                continue
            if dies_h and 'LMXJV'[x.data.weekday()] not in dies_h:
                continue
            if not es_real(x):
                continue
            rows.setdefault((x.s.id, x.data, x.ini), {'id_sessio': x.s.id, 'data': x.data, 'dia': 'LMXJV'[x.data.weekday()], 'hora_inici': fmt(x.ini), 'hora_fi': fmt(x.fi),
                         'assignatura': noms_h.get(x.s.codi, x.s.codi), 'tipus': x.s.tipus, 'grup': x.s.grup,
                         'aula': x.aula or '(sense aula)', 'alumnes': x.s.alumnes,
                         'docents': ', '.join(sorted(x.s.docents)), 'titulacions': ', '.join(x.s.cohorts)})
    rows = list(rows.values())
    st.caption(' · '.join(sorted(periodes)))
    df_h = pd.DataFrame(rows)
    if len(df_h):
        df_h = df_h.sort_values(['data', 'hora_inici', 'assignatura']).reset_index(drop=True)
    st.write(f'{len(df_h)} sessions')
    st.dataframe(df_h, hide_index=True)

# ---------------------------------------------------------------- PDF
with t_pdf:
    st.subheader('PDF amb els horaris')
    noms = pdfs.noms_assignatures(api.PAQUET)
    c1, c2 = st.columns(2)
    tit_p = c1.selectbox('Titulació', TOTES, key='p_tit')
    col_p, SEM_TXT = ctx(tit_p)
    st.caption(SEM_TXT)
    setmanes = sorted({x.data.isocalendar()[:2] for x in col_p.values()})
    sm_def = pdfs.setmana_tipica(list(col_p.values()))
    cohs_p = cohorts_de(col_p, TITULACIONS[tit_p])
    cursos_p = sorted({h.split(':')[1] for h in cohs_p}, key=lambda c: ORDRE_CURS.get(c, 9))
    etiq_p = [NOM_CURS.get(c, c) for c in cursos_p]
    curs_p = c2.multiselect('Cursos', etiq_p, key='p_curs', placeholder='Tots els cursos')
    fmt_sm = lambda s: f'{s[0]}-W{s[1]:02d} (del {dt.date.fromisocalendar(s[0], s[1], 1):%d/%m/%Y})'
    totes_sm = st.checkbox('Totes les setmanes del semestre (una pàgina per curs i setmana)', key='p_totes')
    if totes_sm:
        sm_p = setmanes
    else:
        sm_p = st.multiselect('Setmanes', setmanes, default=[sm_def], key='p_sm', format_func=fmt_sm,
                              placeholder='Tria una o més setmanes') or [sm_def]
    st.caption("Les setmanes no són totes iguals: el PLAB va per rotacions i hi ha festius, "
               "així que cada setmana pot tenir classes diferents.")
    triats_p = [h for h in cohs_p if not curs_p or NOM_CURS.get(h.split(':')[1], h.split(':')[1]) in curs_p]
    if st.button('Genera el PDF'):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'h.pdf'
            n = pdfs.genera_multi(col_p, noms, triats_p, sm_p, p, SEM_TXT)
            nom = f"horari_{tit_p.split(' ')[0].replace('+', '_')}_{'tots' if not curs_p else '-'.join(h.split(':')[1] for h in triats_p)}.pdf"
            st.session_state['pdf_un'] = (p.read_bytes(), nom, n, len(triats_p) * len(sm_p))
    if 'pdf_un' in st.session_state:
        b, nom, n, nc = st.session_state['pdf_un']
        st.download_button(f'Descarrega {nom} ({n} classes)', b, nom, 'application/pdf')
    st.divider()
    st.markdown('**Tots els cursos, graus i màsters** (un PDF per curs; el MET és del 1r quadrimestre)')
    if st.button('Genera tots els PDF (ZIP)'):
        with st.spinner('Generant els PDF...'), tempfile.TemporaryDirectory() as d:
            out = pdfs.genera_tots(dades(2)[1], noms, d, None, None, '2n semestre 2026-27')
            col1 = dades(1)[1]
            out += pdfs.genera_tots(col1, noms, d, None, [h for h in {y for x in col1.values() for y in x.s.cohorts}
                                                         if h.startswith('MET')], '1r quadrimestre 2026-27')
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
                for h, p, n, s in out:
                    z.write(p, p.name)
            st.session_state['pdf_zip'] = (buf.getvalue(), len(out))
    if 'pdf_zip' in st.session_state:
        b, n = st.session_state['pdf_zip']
        st.download_button(f'Descarrega el ZIP ({n} PDF)', b, 'horaris.zip', 'application/zip')

# ---------------------------------------------------------------- aules lliures (2n semestre)
with t_aul:
    st.subheader('Quines aules estan lliures?')
    base2, col2 = dades(2)
    HORES = [fmt(m) for m in range(8 * 60 + 30, 21 * 60 + 1, 30)]
    c1, c2, c3, c4 = st.columns(4)
    d = c1.date_input('Data', dt.date(2027, 3, 10), min_value=min(x.data for x in col2.values()),
                      max_value=max(x.data for x in col2.values()), key='al_d')
    h1 = c2.selectbox('Des de', HORES[:-1], index=HORES.index('10:00'), key='al_h1')
    fins = [h for h in HORES if h > h1]
    h2 = c3.selectbox('Fins a', fins, index=min(1, len(fins) - 1) if h1 == '10:00' else 0, key='al_h2')
    pl = c4.number_input('Places mínimes', 0, 300, 60, key='al_pl')
    r = api.aules_lliures(d.isoformat(), h1, h2, int(pl))
    st.write(f"{r['total']} aules lliures")
    st.dataframe(pd.DataFrame(r['aules']))

# ---------------------------------------------------------------- buscador: què hi ha en una aula i franja
with t_bus:
    st.subheader("Quina classe hi ha en una aula?")
    noms_b = pdfs.noms_assignatures(api.PAQUET)
    base_b, col_b2 = dades(2)
    _, col_b1 = dades(1)
    aules_b = sorted(base_b.aules)
    HB = [fmt(m) for m in range(8 * 60 + 30, 21 * 60 + 1, 30)]
    c1, c2, c3, c4 = st.columns(4)
    a_b = c1.selectbox('Aula', aules_b, key='b_aula')
    d_b = c2.date_input('Data', dt.date(2027, 3, 10), min_value=dt.date(2026, 9, 1), max_value=dt.date(2027, 6, 30), key='b_d')
    h1b = c3.selectbox('Des de', HB[:-1], index=HB.index('10:00'), key='b_h1')
    fb = [h for h in HB if h > h1b]
    h2b = c4.selectbox('Fins a', fb, index=min(1, len(fb) - 1) if h1b == '10:00' else 0, key='b_h2')
    col_b = col_b2 if d_b.month in (2, 3, 4, 5, 6) else col_b1
    i0, f0 = (int(h[:2]) * 60 + int(h[3:]) for h in (h1b, h2b))
    hits = sorted((x for x in col_b.values() if es_real(x) and x.aula == a_b and x.data == d_b and x.ini < f0 and i0 < x.fi),
                  key=lambda x: x.ini)
    if d_b.weekday() > 4:
        st.info('Cap dissabte ni diumenge hi ha classes.')
    elif not hits:
        st.success(f'L\'aula {a_b} està lliure el {d_b:%d/%m/%Y} de {h1b} a {h2b}.')
    else:
        st.write(f'{len(hits)} classe(s) a {a_b} el {d_b:%d/%m/%Y} entre {h1b} i {h2b}')
        st.dataframe(pd.DataFrame([{'hora_inici': fmt(x.ini), 'hora_fi': fmt(x.fi),
                                    'assignatura': noms_b.get(x.s.codi, x.s.codi), 'tipus': x.s.tipus, 'grup': x.s.grup,
                                    'alumnes': x.s.alumnes, 'docents': ', '.join(sorted(x.s.docents)),
                                    'titulacions': ', '.join(x.s.cohorts), 'id_sessio': x.s.id} for x in hits]),
                     hide_index=True)