"""agent/tancament.py: què fem quan una aula no es pot fer servir?

Ús (des de la carpeta repte-horaris-escola, amb la carpeta agent/ al costat de horaris/):

    python -m agent.tancament --proposta proposta-torns.csv --aula Q3/0013 \
        --des 2027-03-15 --fins 2027-03-19 --sortida sortida_tancament

Com treballa (tot és codi determinista; l'LLM només ha de passar-li la incidència i explicar el resultat):
  1. afectades(): sessions de la proposta que cauen a l'aula tancada (aula + data + franja).
  2. Per a cada classe afectada prova, per ordre de cost:
       a) una altra aula lliure (mateix tipus, aforament, mateix passadís que la seva aula base);
       b) si es permet, una altra franja de la mateixa setmana (+ aula).
  3. Cada solució es valida amb el verificador (avalua) amb l'aula tancada com a R3-TANCADA,
     i es compta el cost respecte de la proposta d'entrada.
  4. registre_canvis(): files per al registre de canvis (sessió, d'on a on, motiu, a qui afecta, data de l'avís).

Només biblioteca estàndard + el paquet horaris. Cap dada surt de la màquina.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

from horaris.check import (Colocada, Informe, _alumnat_comparteix, _col_loca, _dins_finestra,
                           _espai_ok, _torn_ok, avalua, passadis)
from horaris.model import DIES, MATI, Fila, Relaxacio, Tancament, carrega_base, fmt, hm, llegeix_proposta

PAS_MIN = 30  # resolució de les franges d'inici que es proven quan es mou d'hora


# ----------------------------------------------------------------------------------------------
# Dades
# ----------------------------------------------------------------------------------------------
@dataclass
class Incidencia:
    aula: str
    data_ini: dt.date
    data_fi: dt.date
    h_ini: int = 0
    h_fi: int = 24 * 60
    motiu: str = 'aula no disponible'

    @classmethod
    def from_dict(cls, d: dict) -> 'Incidencia':
        """Format que ha de produir l'LLM: {aula, data_ini, data_fi, h_ini?, h_fi?, motiu?}."""
        di = dt.date.fromisoformat(d['data_ini'])
        return cls(d['aula'].strip(), di, dt.date.fromisoformat(d.get('data_fi') or d['data_ini']),
                   hm(d['h_ini']) if d.get('h_ini') else 0, hm(d['h_fi']) if d.get('h_fi') else 24 * 60,
                   d.get('motiu') or 'aula no disponible')

    def toca(self, c: Colocada) -> bool:
        return (c.aula == self.aula and self.data_ini <= c.data <= self.data_fi
                and c.ini < self.h_fi and c.fi > self.h_ini and not c.s.sense_espai)

    def com_tancament(self) -> Tancament:
        return Tancament(self.aula, self.data_ini, self.data_fi, self.h_ini, self.h_fi)


@dataclass
class Canvi:
    sessions: tuple[str, ...]
    tipus: str                      # 'aula' | 'hora'
    de: tuple[dt.date, int, str]    # data, h_ini, aula
    a: tuple[dt.date, int, str]
    relaxa: tuple[str, ...] = ()    # sessions fixades amb aula: cal declarar R1-FIXADA

    def text(self) -> str:
        f = lambda t: f'{DIES[t[0].weekday()]} {t[0]} {fmt(t[1])} {t[2] or "-"}'
        return f'{"+".join(self.sessions)}: {f(self.de)} -> {f(self.a)}'


@dataclass
class Solucio:
    nom: str
    canvis: list[Canvi]
    sense_solucio: list[tuple[str, str]]     # (id_sessio, motiu)
    files: list[Fila]
    informe: Informe
    col: dict[str, Colocada] = field(repr=False, default_factory=dict)
    inc: object = None

    def relaxacions(self) -> list[dict]:
        out = []
        for c in self.canvis:
            if not c.relaxa:
                continue
            for regla, ids in (('R7-PLAB', [s for s in c.relaxa if self.col[s].s.tipus == 'PLAB']),
                               ('R1-FIXADA', [s for s in c.relaxa if self.col[s].s.tipus != 'PLAB'])):
                if ids:
                    out.append({'restriccio': regla, 'sessions': '|'.join(ids),
                                'justificacio': f'{self.inc.motiu}: {self.inc.aula} no disponible '
                                                f'{self.inc.data_ini}..{self.inc.data_fi}; la sessio fixada es fa a '
                                                f'{c.a[2]} (mateix dia i hora)'})
        return out

    def relaxacions_obj(self) -> list:
        return [Relaxacio(r['restriccio'], frozenset(r['sessions'].split('|')), r['justificacio'])
                for r in self.relaxacions()]

    @property
    def veredicte(self) -> str:
        return self.informe.veredicte

    def cost(self) -> dict:
        o = self.informe.objectius
        return {'canvis_franja': o.get('canvis_franja_vs_referencia'),
                'canvis_aula': o.get('canvis_aula_vs_referencia'),
                'hores_mortes_min': o.get('hores_mortes_min'),
                'desplacaments_aula': o.get('desplacaments_aula')}

    def resum(self) -> dict:
        """Dict serialitzable: és el que ha de rebre l'LLM (dades, no instruccions)."""
        rec = {k: v['compten'] for k, v in self.informe.recompte().items() if v['compten']}
        return {'solucio': self.nom, 'veredicte': self.veredicte, 'incompliments_que_compten': rec,
                'cost': self.cost(), 'relaxacions_a_declarar': self.relaxacions(), 'canvis': [c.text() for c in self.canvis],
                'sessions_sense_solucio': [{'id': i, 'motiu': m} for i, m in self.sense_solucio]}


# ----------------------------------------------------------------------------------------------
# Estat de l'horari i comprovació de restriccions en moure una classe
# ----------------------------------------------------------------------------------------------
class Estat:
    def __init__(self, base, col: dict[str, Colocada], inc: Incidencia):
        self.base, self.inc = base, inc
        self.col = dict(col)
        self.per_data: dict[dt.date, dict[str, Colocada]] = collections.defaultdict(dict)
        self.grups: dict[str, list[str]] = collections.defaultdict(list)   # unitat -> sessions
        for sid, c in self.col.items():
            self.per_data[c.data][sid] = c
            self.grups[c.s.unitat].append(sid)

    # -- moure -------------------------------------------------------------------------------
    def mou(self, sids, data: dt.date, ini: int, aula: str) -> None:
        for sid in sids:
            old = self.col[sid]
            self.per_data[old.data].pop(sid, None)
            nou = Colocada(old.s, data, ini, aula)
            self.col[sid] = nou
            self.per_data[data][sid] = nou

    # -- permisos ----------------------------------------------------------------------------
    def pot_canviar_aula(self, sids) -> str:
        for sid in sids:
            pass       # PLAB: nomes es pot canviar d'aula (mai d'hora) i cal declarar R7-PLAB
        return ''

    def fixades(self, sids) -> tuple[str, ...]:
        """Fixades (R1) que ja tenen aula: canviar-ne l'aula obliga a declarar R1-FIXADA com a relaxació.
        (R3-TANCADA no es pot relaxar: l'aula tancada no es pot fer servir.)"""
        return tuple(s for s in sids if self.col[s].s.fixada and self.col[s].s.aula)

    def pot_canviar_hora(self, sids) -> bool:
        return all(not self.col[s].s.fixada for s in sids)

    # -- validació d'una col·locació candidata ------------------------------------------------
    def valida(self, sids, data: dt.date, ini: int, aula: str, moguda: bool) -> bool:
        base = self.base
        members = [self.col[s].s for s in sids]
        fi = ini + members[0].durada
        if data.weekday() >= 5:
            return False
        if moguda:
            if data in base.dies_sense_classe:
                return False
            if any(ini < b and fi > a for a, b in base.aturades.get(data, ())):
                return False
            if not _dins_finestra(ini, fi):
                return False
            if any(_torn_ok(s.torn, ini, fi) is False for s in members):
                return False
        amb_espai = [s for s in members if not s.sense_espai]
        if amb_espai:
            if aula not in base.aules:
                return False
            if not all(_espai_ok(base, s, aula) for s in amb_espai):
                return False
            if sum(s.alumnes for s in amb_espai) > base.aules[aula].capacitat:
                return False
            for t in base.tancaments:
                if aula == t.aula and t.data_ini <= data <= t.data_fi and ini < t.fi and fi > t.ini:
                    return False
        ids = set(sids)
        unitat = members[0].unitat
        for c in self.per_data.get(data, {}).values():
            if c.s.id in ids or c.s.unitat == unitat:
                continue
            if not (ini < c.fi and fi > c.ini):
                continue
            if amb_espai and aula and c.aula == aula and not c.s.sense_espai:
                return False
            if not moguda:
                continue   # canviar només d'aula no crea ni arregla conflictes de docent/alumnat (els que hi ha són heretats)
            for s in members:
                if s.docents & c.s.docents:
                    return False
                if _alumnat_comparteix(s, c.s):
                    return False
                tip = {s.tipus, c.s.tipus}
                if s.codi == c.s.codi and 'PLAB' in tip and tip & {'TE', 'PAUL'}:
                    return False
        return True

    # -- candidats ---------------------------------------------------------------------------
    def aula_base(self, sids) -> str:
        s0 = self.col[sids[0]].s
        cnt = collections.Counter(
            c.aula for c in self.col.values()
            if c.s.codi == s0.codi and c.s.grup == s0.grup and c.aula and c.aula != self.inc.aula)
        return cnt.most_common(1)[0][0] if cnt else ''

    def ordre_aules(self, sids) -> list[str]:
        """Primer l'aula base del grup, després el mateix passadís (R6), després la més ajustada."""
        base_a = self.aula_base(sids)
        ref = passadis(base_a or self.inc.aula)
        return sorted(self.base.aules,
                      key=lambda a: (a != base_a, passadis(a) != ref, self.base.aules[a].capacitat, a))

    def aules_lliures(self, sids, data: dt.date, ini: int, moguda: bool = True) -> list[str]:
        return [a for a in self.ordre_aules(sids) if self.valida(sids, data, ini, a, moguda)]

    def franges(self, sids):
        """Altres (data, h_ini) de la mateixa setmana ISO: primer el mateix dia, per proximitat."""
        c0 = self.col[sids[0]]
        dur = c0.s.durada
        lundi = c0.data - dt.timedelta(days=c0.data.weekday())
        out = []
        for i in range(5):
            d = lundi + dt.timedelta(days=i)
            ini = MATI[0]
            while ini + dur <= 21 * 60:
                if (d, ini) != (c0.data, c0.ini):
                    out.append((d, ini))
                ini += PAS_MIN
        out.sort(key=lambda x: (x[0] != c0.data, abs((x[0] - c0.data).days), abs(x[1] - c0.ini)))
        return out

    # -- resoldre una classe -----------------------------------------------------------------
    def resol(self, sids, permet_hora: bool):
        motiu = self.pot_canviar_aula(sids)
        c0 = self.col[sids[0]]
        de = (c0.data, c0.ini, c0.aula)
        if not motiu:
            for a in self.ordre_aules(sids):
                if a != self.inc.aula and self.valida(sids, c0.data, c0.ini, a, moguda=False):
                    self.mou(sids, c0.data, c0.ini, a)
                    return Canvi(tuple(sids), 'aula', de, (c0.data, c0.ini, a), self.fixades(sids)), ''
        if not permet_hora:
            return None, motiu or 'cap aula lliure compatible a la mateixa franja'
        if not self.pot_canviar_hora(sids):
            return None, motiu or 'sessió fixada: no es pot moure d\'hora'
        for d, ini in self.franges(sids):
            for a in self.ordre_aules(sids):
                if self.valida(sids, d, ini, a, moguda=True):
                    self.mou(sids, d, ini, a)
                    return Canvi(tuple(sids), 'hora', de, (d, ini, a)), ''
        return None, 'cap aula ni franja lliure aquella setmana'


# ----------------------------------------------------------------------------------------------
# API pública
# ----------------------------------------------------------------------------------------------
def carrega(paquet: Path, proposta: Path, inc: Incidencia, semestre: int | None = 2,
            escenari: Path | None = None):
    """Base amb l'aula tancada afegida com a tancament + proposta (només les sessions de la base)."""
    base = carrega_base(Path(paquet), semestre=semestre, escenari=Path(escenari) if escenari else None)
    base.tancaments.append(inc.com_tancament())
    files = [f for f in llegeix_proposta(Path(proposta)) if f.id in base.sessions]
    return base, files


def afectades(base, files: list[Fila], inc: Incidencia) -> list[str]:
    """id_sessio de les classes de la proposta que cauen a l'aula tancada."""
    col = _col_loca(base, files, Informe())
    return [sid for sid in base.ordre if sid in col and inc.toca(col[sid])]


def aules_lliures(base, files: list[Fila], inc: Incidencia, id_sessio: str,
                  dia: str, h_ini: str) -> list[str]:
    """Eina per a l'agent: quines aules admeten aquesta sessió en aquest dia/hora (sense tocar la resta)."""
    col = _col_loca(base, files, Informe())
    est = Estat(base, col, inc)
    s = col[id_sessio].s
    data = s.data + dt.timedelta(days=DIES.index(dia.upper()) - s.data.weekday())
    sids = est.grups[s.unitat]
    return est.aules_lliures(sids, data, hm(h_ini), moguda=True)


def _a_files(base, col: dict[str, Colocada]) -> list[Fila]:
    out = []
    for i, sid in enumerate(base.ordre, start=2):
        c = col.get(sid)
        if c is None:
            continue
        out.append(Fila(sid, DIES[c.data.weekday()], fmt(c.ini), c.aula, i,
                        c.data.isoformat() if sid in base.cancellades else ''))
    return out


def soluciona(base, files: list[Fila], inc: Incidencia, permet_hora: bool = True,
              nom: str = '', nomes_aules: bool = False) -> Solucio:
    col0 = _col_loca(base, files, Informe())
    est = Estat(base, col0, inc)
    unitats, vist = [], set()
    for sid in base.ordre:
        if sid in col0 and inc.toca(col0[sid]) and col0[sid].s.unitat not in vist:
            vist.add(col0[sid].s.unitat)
            unitats.append(list(est.grups[col0[sid].s.unitat]))
    # primer les més difícils: poc marge (més alumnes) i amb docència compartida
    unitats.sort(key=lambda g: -sum(col0[s].s.alumnes for s in g))
    canvis, sense = [], []
    for sids in unitats:
        canvi, motiu = est.resol(sids, permet_hora)
        if canvi:
            canvis.append(canvi)
        else:
            sense.extend((s, motiu) for s in sids)
    nous = _a_files(base, est.col)
    sol = Solucio(nom or ('aula_i_hora' if permet_hora else 'nomes_aula'), canvis, sense, nous, None, est.col, inc)
    sol.informe = avalua(base, nous, sol.relaxacions_obj(), referencia=files, nomes_aules=nomes_aules)
    return sol


def proposa_solucions(paquet: Path, proposta: Path, inc: Incidencia, semestre: int | None = 2,
                      escenari: Path | None = None, nomes_aules: bool = False) -> list[Solucio]:
    """Dues estratègies: només canviar d'aula (mínim cost) i, si cal, també d'hora. Ordenades per qualitat."""
    base, files = carrega(paquet, proposta, inc, semestre, escenari)
    sols = [soluciona(base, files, inc, permet_hora=False, nomes_aules=nomes_aules)]
    if not nomes_aules and (sols[0].sense_solucio or sols[0].veredicte == 'NO VALIDA'):
        sols.append(soluciona(base, files, inc, permet_hora=True))
    sols.sort(key=lambda s: (s.veredicte == 'NO VALIDA', len(s.sense_solucio), len(s.relaxacions()),
                             sum(1 for _ in s.canvis if _.tipus == 'hora'), len(s.canvis)))
    return sols


def registre_canvis(base, sol: Solucio, inc: Incidencia, data_avis: dt.date | None = None) -> list[dict]:
    """Entrades del registre de canvis: sessió, d'on a on, motiu, a qui afecta i data de l'avís.
    Només es redacta: no s'envia res a ningú."""
    data_avis = data_avis or dt.date.today()
    out = []
    for c in sol.canvis:
        for sid in c.sessions:
            s = base.sessions[sid]
            out.append({
                'id_sessio': sid, 'assignatura': f'{s.codi} {s.grup}',
                'de': f'{c.de[0]} {fmt(c.de[1])} {c.de[2] or "-"}',
                'a': f'{c.a[0]} {fmt(c.a[1])} {c.a[2]}',
                'tipus_canvi': c.tipus,
                'motiu': f'{inc.motiu} ({inc.aula}, {inc.data_ini}..{inc.data_fi})',
                'afecta_docents': '|'.join(sorted(s.docents)) or '(sense docent al llistat)',
                'afecta_alumnat': '|'.join(s.cohorts),
                'avisar': 'docent, alumnat, Gestió Acadèmica',
                'data_avis': data_avis.isoformat()})
    return out


# ----------------------------------------------------------------------------------------------
# Sortida i línia d'ordres
# ----------------------------------------------------------------------------------------------
def escriu_proposta(path: Path, files: list[Fila]) -> None:
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['id_sessio', 'dia', 'h_ini', 'aula', 'data'])
        for r in files:
            w.writerow([r.id, r.dia, r.h_ini, r.aula, r.data])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='python -m agent.tancament')
    ap.add_argument('--proposta', required=True)
    ap.add_argument('--aula', required=True)
    ap.add_argument('--des', required=True, help='AAAA-MM-DD')
    ap.add_argument('--fins', help='AAAA-MM-DD (per defecte, el mateix dia)')
    ap.add_argument('--h-ini')
    ap.add_argument('--h-fi')
    ap.add_argument('--motiu', default='aula no disponible')
    ap.add_argument('--paquet', default='paquet')
    ap.add_argument('--semestre', type=int, default=2)
    ap.add_argument('--escenari')
    ap.add_argument('--sortida', default='sortida_tancament')
    ap.add_argument('--nomes-aules', action='store_true',
                    help="avalua en mode només aules (útil mentre no hi ha la proposta de torns del 5.2)")
    a = ap.parse_args(argv)

    inc = Incidencia.from_dict({'aula': a.aula, 'data_ini': a.des, 'data_fi': a.fins or a.des,
                                'h_ini': a.h_ini, 'h_fi': a.h_fi, 'motiu': a.motiu})
    sols = proposa_solucions(Path(a.paquet), Path(a.proposta), inc, a.semestre,
                             Path(a.escenari) if a.escenari else None, nomes_aules=a.nomes_aules)
    base, files = carrega(Path(a.paquet), Path(a.proposta), inc, a.semestre,
                          Path(a.escenari) if a.escenari else None)
    print(f'Sessions afectades a {inc.aula}: {len(afectades(base, files, inc))}')
    out = Path(a.sortida)
    out.mkdir(parents=True, exist_ok=True)
    for s in sols:
        r = s.resum()
        print(f'\n== {s.nom}: {r["veredicte"]} · canvis: {len(s.canvis)} · cost {r["cost"]} · relaxacions: {len(s.relaxacions())}')
        for c in s.canvis:
            print('  ', c.tipus, c.text())
        for i, m in s.sense_solucio:
            print('   SENSE SOLUCIÓ', i, m)
        escriu_proposta(out / f'proposta_{s.nom}.csv', s.files)
        rel = s.relaxacions()
        if rel:
            with open(out / f'relaxacions_{s.nom}.csv', 'w', encoding='utf-8', newline='') as f:
                w = csv.DictWriter(f, fieldnames=['restriccio', 'sessions', 'justificacio'])
                w.writeheader()
                w.writerows(rel)
        (out / f'informe_{s.nom}.json').write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding='utf-8')
        reg = registre_canvis(base, s, inc)
        if reg:
            with open(out / f'registre_{s.nom}.csv', 'w', encoding='utf-8', newline='') as f:
                w = csv.DictWriter(f, fieldnames=list(reg[0]))
                w.writeheader()
                w.writerows(reg)
    tanc = {'aula': inc.aula, 'data_ini': inc.data_ini.isoformat(), 'data_fi': inc.data_fi.isoformat()}
    if inc.h_ini:
        tanc['h_ini'] = fmt(inc.h_ini)
    if inc.h_fi != 24 * 60:
        tanc['h_fi'] = fmt(inc.h_fi)
    esc = out / 'escenari'
    esc.mkdir(exist_ok=True)
    (esc / 'escenari.json').write_text(json.dumps({'nom': 'incidencia', 'ficticia': True,
                                                   'aules_tancades': [tanc]}, indent=2), encoding='utf-8')
    n = sols[0].nom
    extra = ' --nomes-aules' if a.nomes_aules else ''
    rel = f' --relaxacions {out}/relaxacions_{n}.csv' if sols[0].relaxacions() else ''
    print(f'\nFitxers a {out}/ . Comprova la millor solucio amb el verificador oficial:')
    print(f'python -m horaris check {out}/proposta_{n}.csv --semestre {a.semestre} --escenari {esc}'
          f' --referencia {a.proposta}{rel}{extra}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())