"""agent/pdfs.py: PDF amb l'horari setmanal de cada titulacio i curs (graus, dobles graus i masters).

    python -m agent.pdfs --sortida horaris-pdf                    # una setmana tipica per curs
    python -m agent.pdfs --sortida horaris-pdf --setmana 2027-W10 # una setmana concreta
    python -m agent.pdfs --sortida horaris-pdf --curs GEI:1r      # nomes un curs

Es dibuixa la graella (dilluns a divendres, 8.30-21.00) amb l'assignatura, el grup i l'aula. Les classes que
coincideixen a la mateixa hora (grups diferents del mateix curs) es posen una al costat de l'altra.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from horaris.model import DIES, fmt

INI, FI = 8 * 60 + 30, 21 * 60
NOMS_DIA = ['Dilluns', 'Dimarts', 'Dimecres', 'Dijous', 'Divendres']


def noms_assignatures(paquet: Path) -> dict:
    with open(Path(paquet) / 'sessions.csv', encoding='utf-8-sig', newline='') as f:
        return {r['codi']: r['assignatura'] for r in csv.DictReader(f)}


def setmana_tipica(sessions) -> tuple:
    """La setmana ISO amb mes classes de tot l'horari (una setmana 'normal', sense festius)."""
    n = collections.Counter(getattr(s, 'data').isocalendar()[:2] for s in sessions)
    return n.most_common(1)[0][0]


def _color(codi: str):
    h = int(hashlib.md5(codi.encode()).hexdigest()[:6], 16)
    r, g, b = (h >> 16) & 255, (h >> 8) & 255, h & 255
    return colors.Color(0.62 + 0.36 * r / 255, 0.62 + 0.36 * g / 255, 0.62 + 0.36 * b / 255)


def _llegeix_setmana(text: str):
    a, w = text.upper().split('-W')
    return int(a), int(w)


def _text_en_caixa(c, text, x, y_top, w, h, font='Helvetica', mida=6):
    c.setFont(font, mida)
    paraules, linies, cur = text.split(), [], ''
    for p in paraules:
        prova = (cur + ' ' + p).strip()
        if stringWidth(prova, font, mida) <= w - 3:
            cur = prova
        else:
            if cur:
                linies.append(cur)
            cur = p
    if cur:
        linies.append(cur)
    y = y_top - mida - 1
    for l in linies:
        if y < y_top - h + 1:
            break
        c.drawString(x + 1.5, y, l)
        y -= mida + 0.5


def pagina(c, cohort, files, noms, setmana, semestre_txt='2n semestre 2026-27'):
    """files: sessions col·locades (Colocada) d'aquest curs a la setmana."""
    W, H = landscape(A4)
    esq, dre, sup, inf = 48, 20, 58, 24
    col_w = (W - esq - dre) / 5
    alt = H - sup - inf
    pix_min = alt / (FI - INI)

    def y_de(m):
        return H - sup - (m - INI) * pix_min

    c.setFont('Helvetica-Bold', 14)
    c.drawString(esq, H - 28, f'Horari {cohort.replace(":", " ")}')
    lundi = dt.date.fromisocalendar(setmana[0], setmana[1], 1)
    c.setFont('Helvetica', 9)
    c.drawString(esq, H - 42, f'Setmana del {lundi:%d/%m/%Y} ({semestre_txt}, proposta de treball) · EEBE UAB')
    for i, nom in enumerate(NOMS_DIA):
        x = esq + i * col_w
        c.setFont('Helvetica-Bold', 9)
        c.drawCentredString(x + col_w / 2, H - sup + 4, f'{nom} {(lundi + dt.timedelta(days=i)):%d/%m}')
    c.setStrokeColor(colors.lightgrey)
    for m in range(INI, FI + 1, 30):
        y = y_de(m)
        c.setLineWidth(0.6 if m % 60 == 30 else 0.25)
        c.line(esq, y, W - dre, y)
        if m % 60 == 30:
            c.setFont('Helvetica', 6.5)
            c.setFillColor(colors.black)
            c.drawRightString(esq - 3, y - 2, fmt(m))
    for i in range(6):
        c.line(esq + i * col_w, y_de(INI), esq + i * col_w, y_de(FI))
    for d in range(5):
        dia = [f for f in files if f.data.weekday() == d]
        dia.sort(key=lambda f: (f.ini, f.fi))
        lanes: list[list] = []
        asign = {}
        for f in dia:                                     # carrils per a les que coincideixen
            for k, fin in enumerate(lanes):
                if fin[-1].fi <= f.ini:
                    fin.append(f)
                    asign[id(f)] = k
                    break
            else:
                lanes.append([f])
                asign[id(f)] = len(lanes) - 1
        # nombre de carrils simultanis per a cada classe
        for f in dia:
            veines = [g for g in dia if g.ini < f.fi and g.fi > f.ini]
            n = max(asign[id(g)] for g in veines) + 1
            w = col_w / n
            x = esq + d * col_w + asign[id(f)] * w
            y1, y2 = y_de(f.ini), y_de(f.fi)
            c.setFillColor(_color(f.s.codi))
            c.setStrokeColor(colors.Color(0.35, 0.35, 0.35))
            c.setLineWidth(0.5)
            c.rect(x + 0.5, y2 + 0.5, w - 1, y1 - y2 - 1, fill=1, stroke=1)
            c.setFillColor(colors.black)
            nom = noms.get(f.s.codi, f.s.codi)
            _text_en_caixa(c, f'{nom} · {f.s.tipus} {f.s.grup} · {f.aula or "sense aula"} · {fmt(f.ini)}-{fmt(f.fi)}',
                           x, y1, w, y1 - y2, mida=5.5 if n > 2 else 6.5)
    c.setFillColor(colors.black)
    c.setFont('Helvetica-Oblique', 6)
    c.drawString(esq, 12, 'Generat automàticament a partir de la proposta validada pel verificador. '
                          '«Sense aula»: laboratoris PLAB o docència alternativa de doble titulació (no necessiten aula).')
    c.showPage()


def _sessions(col, cohort, setmana, nomes_dobles=False):
    return [x for x in col.values() if cohort in x.s.cohorts and x.data.isocalendar()[:2] == tuple(setmana)
            and x.s.alumnes > 0 and not any(h.endswith(':?') for h in x.s.cohorts)   # sense sessions fantasma
            and (not nomes_dobles or x.s.sense_espai)]


def genera_multi(col, noms, cohorts, setmana, path, semestre_txt='2n semestre 2026-27', nomes_dobles=False):
    """Un PDF amb una pagina per curs i setmana. `setmana` pot ser una setmana (any, num) o una llista de setmanes.
    Les setmanes sense classes per a un curs (festius) s'ometen. Retorna el nombre de classes dibuixades."""
    setmanes = [setmana] if isinstance(setmana, tuple) else list(setmana)
    c = canvas.Canvas(str(path), pagesize=landscape(A4))
    c.setTitle('Horaris EEBE')
    n = 0
    for h in cohorts:
        for sm in setmanes:
            files = _sessions(col, h, sm, nomes_dobles)
            if not files and len(setmanes) > 1:
                continue
            n += len(files)
            titol = h + (' · doble titulació' if nomes_dobles else '')
            pagina(c, titol, files, noms, sm, semestre_txt)
    if n == 0 and not c.getPageNumber() > 1:
        pagina(c, ' '.join(cohorts), [], noms, setmanes[0], semestre_txt)
    c.save()
    return n


def genera(col, noms, cohort, setmana, path, semestre_txt='2n semestre 2026-27', nomes_dobles=False):
    """Un PDF d'un curs."""
    return genera_multi(col, noms, [cohort], setmana, path, semestre_txt, nomes_dobles)


def genera_tots(col, noms, carpeta, setmana=None, cursos=None, semestre_txt='2n semestre 2026-27'):
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    tots = sorted({h for x in col.values() for h in x.s.cohorts if '?' not in h})
    setmana = setmana or setmana_tipica(list(col.values()) and [x for x in col.values()])
    out = []
    for h in tots:
        if cursos and h not in cursos:
            continue
        sess = [x for x in col.values() if h in x.s.cohorts]
        sm = setmana
        p = carpeta / f'horari_{h.replace(":", "_")}.pdf'
        n = genera(col, noms, h, sm, p, semestre_txt)
        out.append((h, p, n, sm))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m agent.pdfs')
    ap.add_argument('--paquet', default='paquet')
    ap.add_argument('--proposta', default='proposta-torns.csv')
    ap.add_argument('--sortida', default='horaris-pdf')
    ap.add_argument('--setmana', default='', help='per exemple 2027-W10 (per defecte una setmana tipica)')
    ap.add_argument('--semestre', type=int, default=2, help='1 o 2 (el master MET nomes te classes al 1r)')
    ap.add_argument('--curs', action='append', help='per exemple GEI:1r (es pot repetir)')
    a = ap.parse_args(argv)
    from horaris.check import Informe, _col_loca
    from horaris.model import carrega_base, llegeix_proposta
    base = carrega_base(Path(a.paquet), semestre=a.semestre)
    files = [f for f in llegeix_proposta(Path(a.proposta)) if f.id in base.sessions]
    col = _col_loca(base, files, Informe())
    noms = noms_assignatures(Path(a.paquet))
    sm = _llegeix_setmana(a.setmana) if a.setmana else None
    out = genera_tots(col, noms, a.sortida, sm, a.curs, '1r quadrimestre 2026-27' if a.semestre == 1 else '2n semestre 2026-27')
    for h, p, n, s in out:
        print(f'{h:10s} {n:4d} classes · setmana {s[0]}-W{s[1]:02d} · {p}')
    print(f'\n{len(out)} PDF a {a.sortida}/')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())