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

ARREL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ARREL))   # perque trobi 'agent' i 'horaris'
os.chdir(ARREL)                  # perque trobi 'paquet/' i 'proposta-torns.csv' des de qualsevol lloc (p. ex. al nuvol)

import pandas as pd
import streamlit as st

from agent import api, estil, pdfs
from horaris.check import Informe, _col_loca
from horaris.model import carrega_base, fmt, llegeix_proposta

st.set_page_config(page_title="Assistent d'horaris EEBE", layout='wide')
estil.aplica()
st.title("Assistent d'horaris · EEBE")
st.caption("Verificador oficial com a font de veritat. Els avisos són esborranys: no s'envia res.")

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
    st.subheader('Imprevist: què ha passat?')
    st.caption("Marca els problemes que tens. L'aplicació els resol tots junts, canviant el mínim, "
               "i ho valida amb el verificador.")
    base2, col2 = dades(2)
    noms_c = pdfs.noms_assignatures(api.PAQUET)
    d_min, d_max = min(x.data for x in col2.values()), max(x.data for x in col2.values())
    aules_l = sorted(base2.aules)

    st.markdown('**1. Aules que no es poden fer servir** (reservades, avariades, en obres...)')
    usa_t = st.checkbox('Hi ha aules que no es poden fer servir', value=True, key='imp_usa_t')
    taula_t = pd.DataFrame(columns=['aula', 'des del', 'fins al'])
    if usa_t:
        taula_t = st.data_editor(
            pd.DataFrame({'aula': ['Q3/0013', 'Q1/1003'],
                          'des del': [dt.date(2027, 3, 15), dt.date(2027, 3, 10)],
                          'fins al': [dt.date(2027, 3, 19), dt.date(2027, 3, 10)]}),
            num_rows='dynamic', hide_index=True, key='imp_taula_t',
            column_config={'aula': st.column_config.SelectboxColumn('aula', options=aules_l),
                           'des del': st.column_config.DateColumn('des del', min_value=d_min, max_value=d_max),
                           'fins al': st.column_config.DateColumn('fins al', min_value=d_min, max_value=d_max)})

    st.markdown('**2. Un grup que ja no hi cap a la seva aula** (hi ha més alumnes)')
    grups = {}
    for x in base2.sessions.values():
        if x.tipus in ('TE', 'PAUL', 'SEM') and x.alumnes > 0 and not x.sense_espai:
            grups[(x.codi, x.grup)] = (x.alumnes, x.tipus)
    etiq_g = {f"{noms_c.get(c, c)} · {g} ({n} alumnes ara)": (c, g) for (c, g), (n, _) in sorted(grups.items(), key=lambda kv: (noms_c.get(kv[0][0], kv[0][0]), kv[0][1]))}
    usa_g = st.checkbox('Hi ha un grup que creix', value=True, key='imp_usa_g')
    grup_sel, nous = None, 0
    if usa_g:
        g1, g2 = st.columns([3, 1])
        defecte = next((k for k, v in etiq_g.items() if v == ('106047', 'TE/21')), list(etiq_g)[0])
        grup_sel = g1.selectbox('Assignatura i grup', list(etiq_g), index=list(etiq_g).index(defecte), key='imp_grup')
        nous = g2.number_input('Alumnes nous', min_value=1, max_value=400, value=130, key='imp_nous')

    st.markdown('**3. Una classe cancel·lada que cal recuperar**')
    usa_c = st.checkbox('Hi ha una classe cancel·lada', value=True, key='imp_usa_c')
    sid_c, fins_c = None, None
    if usa_c:
        c1, c2 = st.columns(2)
        dia_c = c1.date_input('Dia de la classe cancel·lada', dt.date(2027, 3, 8), min_value=d_min, max_value=d_max, key='imp_dia_c')
        fins_c = c2.date_input('Es pot recuperar fins al', dt.date(2027, 3, 19), min_value=d_min, max_value=d_max, key='imp_fins_c')
        del_dia = sorted((x for x in col2.values() if x.data == dia_c and es_real(x)), key=lambda x: (x.ini, x.s.id))
        etiq_c = {f"{fmt(x.ini)}-{fmt(x.fi)} · {noms_c.get(x.s.codi, x.s.codi)} · {x.s.tipus} {x.s.grup} · {x.aula or '(sense aula)'}": x.s.id for x in del_dia}
        if etiq_c:
            defecte_c = next((k for k, v in etiq_c.items() if v == 'S11527'), list(etiq_c)[0])
            sid_c = etiq_c[st.selectbox('Quina classe', list(etiq_c), index=list(etiq_c).index(defecte_c), key='imp_sel_c')]
        else:
            st.info('Aquest dia no hi ha cap classe. Tria un altre dia.')

    t_ok = taula_t.dropna().to_dict('records') if usa_t and len(taula_t) else []
    errors = [f"{r['aula']}: la data d'inici és posterior a la de fi" for r in t_ok if r['des del'] > r['fins al']]
    for e in errors:
        st.error(e)
    if usa_c and fins_c and dia_c >= fins_c:
        st.error('El termini per recuperar la classe ha de ser posterior al dia en què es cancel·la.')
        errors.append('termini')
    res_buit = not t_ok and not (usa_g and grup_sel) and not (usa_c and sid_c)
    if res_buit:
        st.info('Afegeix almenys un problema.')
    if st.button('Resol-ho tot', type='primary', disabled=bool(errors) or res_buit, key='imp_go'):
        with st.spinner('Buscant la solució i validant-la amb el verificador...'):
            try:
                r = api.resol_imprevist_complet(
                    [{'aula': x['aula'], 'data_ini': x['des del'].isoformat(), 'data_fi': x['fins al'].isoformat()} for x in t_ok],
                    [{'codi': etiq_g[grup_sel][0], 'grup': etiq_g[grup_sel][1], 'alumnes': nous}] if usa_g and grup_sel else [],
                    [{'id_sessio': sid_c, 'recuperar_fins': fins_c.isoformat()}] if usa_c and sid_c else [])
            except Exception as e:
                st.error(f'No he pogut resoldre-ho: {e}')
                st.stop()
        ok = r['veredicte'] != 'NO VALIDA' and not r['sense_solucio']
        (st.success if ok else st.error)(f"Veredicte del verificador: {r['veredicte']} · {len(r['registre'])} classes afectades")
        m1, m2, m3 = st.columns(3)
        m1.metric("Canvis d'aula", r['canvis_aula'])
        m2.metric("Canvis de dia o hora", r['canvis_franja'])
        m3.metric('Classes sense solució', len(r['sense_solucio']))
        if r['sense_solucio']:
            st.warning('Aquestes classes no han trobat lloc:')
            st.dataframe(pd.DataFrame(r['sense_solucio']), hide_index=True)
        regla_de = {}
        for r_ in r['relaxacions']:
            for i_ in str(r_['sessions']).split('|'):
                regla_de[i_] = r_['restriccio']
        n_exc = sum(1 for x in r['registre'] if x['id_sessio'] in regla_de)
        QUE2 = {'R1-FIXADA': "Sessió fixada (no s'hauria de moure) que canvia d'aula",
                'R7-PLAB': "Laboratori PLAB que canvia d'aula",
                'R1-TORN': 'Sessió fora del seu torn (matí/tarda), heretada del pas anterior'}
        exc_imp = [r_ for r_ in r['relaxacions'] if r_['restriccio'] != 'R1-TORN']
        if exc_imp:
            with st.expander(f"Excepcions a declarar per aquest imprevist ({sum(len(x['sessions'].split('|')) for x in exc_imp)} classes)"):
                st.caption("Són regles que normalment no es toquen però que aquí s'han hagut d'incomplir perquè l'aula no estava disponible.")
                st.dataframe(pd.DataFrame([{'regla': x['restriccio'], 'què vol dir': QUE2.get(x['restriccio'], ''),
                                            'classes': len(x['sessions'].split('|')), 'justificació': x['justificacio']} for x in exc_imp]), hide_index=True)
        filas = []
        for x in r['registre']:
            ss = base2.sessions[x['id_sessio']]
            d_, h_, a_ = x['de'].split(' ', 2)
            d2_, h2_, a2_ = x['a'].split(' ', 2)
            hm_ = lambda h: int(h[:2]) * 60 + int(h[3:])
            filas.append({'data': d_, 'assignatura': noms_c.get(ss.codi, ss.codi), 'tipus': ss.tipus, 'grup': ss.grup,
                          'motiu': x['motiu'], 'abans (hora)': f'{h_}-{fmt(hm_(h_) + ss.durada)}', 'abans (aula)': a_,
                          'ara (data)': d2_ if d2_ != d_ else '(la mateixa)', 'ara (hora)': f'{h2_}-{fmt(hm_(h2_) + ss.durada)}',
                          'ara (aula)': a2_, 'tipus de canvi': x['tipus_canvi'], 'docents': x['afecta_docents'],
                          'alumnat': x['afecta_alumnat'], 'avisar': x['avisar'], 'id_sessio': x['id_sessio']})
        st.markdown('**Registre de canvis i avisos (esborranys)**')
        st.dataframe(pd.DataFrame(filas).sort_values(['data', 'abans (hora)']).reset_index(drop=True), hide_index=True)

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