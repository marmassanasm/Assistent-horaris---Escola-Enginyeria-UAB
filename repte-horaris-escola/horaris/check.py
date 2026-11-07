"""Verificador del repte d'horaris: restriccions dures (1-8) i objectius (9). Només biblioteca estàndard.

Una proposta és una fila per sessió (id_sessio, dia, h_ini, aula). La durada i la setmana no es llegeixen de
la proposta: es prenen de la base (restricció 5). La data nova és el dia triat dins la mateixa setmana ISO.
"""
from __future__ import annotations

import collections
import datetime as dt
import re
from dataclasses import dataclass, field

from horaris.model import DIES, MATI, TARDA, Base, Fila, Relaxacio, Sessio, a_traslladar, fmt, hm

HORA_RE = re.compile(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$')
# /challenge 07/11/2026: una aula tancada per l'escenari (sala reservada, avaria) no és una excepció de política, és
# l'imprevist mateix: relaxar-la buida el 5.3. R4-AULA sí que es pot declarar (dos grups PAUL a la mateixa aula amb
# dos professors és legítim: test_una_relaxacio_declarada_no_amaga_la_violacio_pero_canvia_el_veredicte).
NO_RELAXABLES = frozenset({'R0-FORMAT', 'R0-HORARI', 'R5-FALTA', 'R5-RECUPERACIO', 'R3-TANCADA'})
# franges d'una hora de 8.30 a 20.30 (restricció 8) i la de 20.30, que des del 04/11/2026 s'ocupa fins a les 21.00
FRANGES = [MATI[0] + 60 * i for i in range(13)]
RESERVA_MIN = 2

DESCRIPCIO = {
    'R0-FORMAT': 'Proposta mal formada (sessió desconeguda o repetida, dia o hora il·legibles)',
    'R0-HORARI': "Mode només aules: s'ha canviat el dia o l'hora d'una sessió",
    'R1-FIXADA': 'Sessió de GEI o GEET+GEST de 1r o 2n moguda (no es toca)',
    'R1-TORN': '1r i 2n al matí; 3r, 4t, 5è, dobles i màsters a la tarda',
    'R2-FINESTRA': 'Fora de les finestres 8.30-14.30 i 14.30-21.00 (o creuant-les)',
    'R2-CALENDARI': 'Sessió moguda a un festiu, dia no lectiu o aturada del calendari (o a un dia sense classes)',
    'R3-AULA': "Aula que no és a l'aulari (ni és la de partida, o és una J, que es porta a l'aulari)",
    'R3-AFORAMENT': "Més alumnes que la capacitat de l'aula",
    'R3-TIPUS': "Espai d'un tipus diferent del que demana la sessió",
    'R3-TANCADA': "Aula tancada per l'escenari (contingència) en aquella data i hora",
    'R4-AULA': 'Dues activitats a la mateixa aula alhora',
    'R4-DOCENT': 'Un mateix docent en dues activitats alhora',
    'R4-ALUMNAT': 'Un mateix grup d\'alumnes en dues activitats alhora',
    'R4-PLAB': "TE o PAUL alhora que un PLAB de la mateixa assignatura",
    'R4-COMPARTIDA': 'Una sessió compartida entre titulacions separada',
    'R5-FALTA': 'Sessió de la base que no surt a la proposta',
    'R5-SENSE-AULA': 'Sessió (no PLAB) sense aula assignada',
    'R5-RECUPERACIO': "Sessió cancel·lada per l'escenari sense recuperar dins el termini",
    'R7-PLAB': 'Laboratori PLAB mogut del seu horari o aula fixats',
    'R8-RESERVA': 'Menys de dues aules ordinàries lliures en una franja',
}


@dataclass
class Violacio:
    regla: str
    sessions: tuple[str, ...]
    detall: str = ''
    declarada: bool = False
    # '' = la proposta n'és responsable; 'fixada' = només hi intervenen sessions fixades sense moure;
    # 'partida' = solapament de docent o alumnat que ja hi era a l'horari de partida (model per grup)
    heretada: str = ''

    @property
    def compta(self) -> bool:
        return not self.declarada and not self.heretada


@dataclass
class Colocada:
    s: Sessio
    data: dt.date
    ini: int
    aula: str

    @property
    def fi(self) -> int:
        return self.ini + self.s.durada


@dataclass
class Informe:
    violacions: list[Violacio] = field(default_factory=list)
    objectius: dict = field(default_factory=dict)
    no_avaluables: collections.Counter = field(default_factory=collections.Counter)
    relaxacions: list[Relaxacio] = field(default_factory=list)

    @property
    def veredicte(self) -> str:
        if any(v.compta for v in self.violacions):
            return 'NO VALIDA'
        if any(v.declarada and not v.heretada for v in self.violacions):
            return 'VALIDA AMB RELAXACIONS DECLARADES'
        return 'VALIDA'

    def recompte(self) -> dict:
        c: dict = {}
        for v in self.violacions:
            e = c.setdefault(v.regla, {'total': 0, 'compten': 0, 'declarades': 0, 'heretades': 0})
            e['total'] += 1
            e['compten'] += v.compta
            e['declarades'] += v.declarada and not v.heretada
            e['heretades'] += bool(v.heretada)
        return dict(sorted(c.items()))


def _torn_ok(torn: str, ini: int, fi: int) -> bool | None:
    """El torn el marca l'hora d'inici; que la sessió hi càpiga sencera ho mira R2 (sense doble recompte)."""
    if torn not in ('mati', 'tarda'):
        return None
    return (ini < MATI[1]) == (torn == 'mati')


AULA_GENERAL = frozenset({'Aules docents', 'Seminaris'})
ESPAI_PRACTIQUES = frozenset({'Laboratoris docents', 'Aules informàtiques'})


def _tipus_permesos(base: Base, s: Sessio) -> frozenset[str]:
    """Definició adoptada (R3, pendent de l'Escola: l'aulari no diu l'equipament): una sessió va a un espai
    del mateix tipus que el de partida (aula docent i seminari compten com el mateix); si no en tenia, una
    TE/PAUL/SEM va a aula docent o seminari i un PLAB a laboratori o aula informàtica."""
    if s.aula in base.aules:
        t = base.aules[s.aula].tipus
        if t == 'Laboratoris docents' and s.tipus != 'PLAB':
            return AULA_GENERAL   # Fernando 03/11: els laboratoris són per als PLAB
        return AULA_GENERAL if t in AULA_GENERAL else frozenset({t})
    return ESPAI_PRACTIQUES if s.tipus == 'PLAB' else AULA_GENERAL


def _espai_ok(base: Base, s: Sessio, aula: str) -> bool:
    """Fernando (04/11/2026): hi ha grups (matrícula PAU, sense teoria) que ho fan tot als laboratoris integrats
    (12 PC) i a les aules d'informàtica, i els labs de Q5 i Q6 no hi entren (configuració específica de
    pràctiques). Totes les aules són accessibles i tenen PC i projector. Per tant un PAUL també pot anar a un
    laboratori integrat o a una aula d'informàtica; la teoria (TE), mai a un laboratori."""
    a = base.aules[aula]
    if s.tipus == 'PAUL' and (a.integrat or a.tipus == 'Aules informàtiques'):
        return True
    return a.tipus in _tipus_permesos(base, s)


def _dins_finestra(ini: int, fi: int) -> bool:
    return any(a <= ini and fi <= b for a, b in (MATI, TARDA))


def _alumnat_comparteix(a: Sessio, b: Sessio) -> bool:
    """Definició adoptada: mateixa cohort (titulació:curs) i (la teoria d'una línia bloqueja tots els seus
    subgrups; dos subgrups xoquen si tenen el mateix número)."""
    if not set(a.cohorts) & set(b.cohorts):
        return False
    if a.tipus == 'TE' or b.tipus == 'TE':
        # /challenge H2: TE/415 i PAUL/415 són el mateix alumnat encara que la «línia» no ho digui
        return a.linia == b.linia or a.num_grup == b.num_grup
    return a.num_grup == b.num_grup


def _col_loca(base: Base, files: list[Fila], inf: Informe) -> dict[str, Colocada]:
    vistes: dict[str, Colocada] = {}
    for f in files:
        s = base.sessions.get(f.id)
        if s is None:
            inf.violacions.append(Violacio('R0-FORMAT', (f.id,), f'línia {f.linia}: sessió desconeguda'))
            continue
        if f.id in vistes:
            inf.violacions.append(Violacio('R0-FORMAT', (f.id,), f'línia {f.linia}: sessió repetida'))
            continue
        if f.dia not in DIES or not HORA_RE.match(f.h_ini):
            inf.violacions.append(Violacio('R0-FORMAT', (f.id,), f'línia {f.linia}: dia «{f.dia}» o hora «{f.h_ini}»'))
            continue
        if f.id in base.cancellades:
            # sessió cancel·lada per l'escenari: es recupera en una altra data, fins al termini
            fins = base.cancellades[f.id]
            try:
                data = dt.date.fromisoformat(f.data)
            except ValueError:
                data = None
            # un dissabte o diumenge feia petar DIES[...] (IndexError, /challenge 07/11/2026): és una data no vàlida
            if data is None or not (s.data < data <= fins) or data.weekday() >= 5 or DIES[data.weekday()] != f.dia:
                inf.violacions.append(Violacio('R5-RECUPERACIO', (f.id,),
                                               f'cancel·lada el {s.data}: cal data nova entre {s.data} i {fins} '
                                               f'(i dia coherent); proposta «{f.data or "-"}» {f.dia}'))
                continue
            vistes[f.id] = Colocada(s, data, hm(f.h_ini), f.aula)
            continue
        data = s.data + dt.timedelta(days=DIES.index(f.dia) - s.data.weekday())
        vistes[f.id] = Colocada(s, data, hm(f.h_ini), f.aula)
    ja_dites = {v.sessions for v in inf.violacions if v.regla in ('R0-FORMAT', 'R5-RECUPERACIO')}
    for sid in base.ordre:
        if sid not in vistes and (sid,) not in ja_dites:
            inf.violacions.append(Violacio('R5-FALTA', (sid,)))
    return vistes


def _per_sessio(base: Base, col: dict[str, Colocada], inf: Informe, nomes_aules: bool = False) -> None:
    for sid in base.ordre:
        c = col.get(sid)
        if c is None:
            continue
        s = c.s
        recuperada = sid in base.cancellades
        # posar aula a una fixada que no en tenia no és moure-la (restricció 7: PLAB sense aula)
        # un PLAB no es toca gens, ni l'aula: els laboratoris els assignen els departaments i molts demanen
        # material específic (Albert/Fernando 03/11). A la resta de fixades sí que es pot posar aula si no en tenen.
        # treure una sessió d'una aula J (fora de l'aulari, Fernando 04/11) tampoc no és moure-la
        canviada = (c.data != s.data or c.ini != s.ini or c.aula != s.aula if s.tipus == 'PLAB'
                    else c.data != s.data or c.ini != s.ini or
                    (bool(s.aula) and not a_traslladar(s.aula) and not s.sense_espai and c.aula != s.aula))
        if s.fixada and canviada and not recuperada:
            regla = 'R7-PLAB' if s.fixada.startswith('R7') else 'R1-FIXADA'
            inf.violacions.append(Violacio(regla, (sid,), f'{s.dia} {fmt(s.ini)} {s.aula or "-"} -> '
                                                          f'{DIES[c.data.weekday()]} {fmt(c.ini)} {c.aula or "-"}'))
        if nomes_aules and not recuperada and (c.data, c.ini) != (s.data, s.ini):
            inf.violacions.append(Violacio('R0-HORARI', (sid,), f'{s.dia} {fmt(s.ini)} -> '
                                                                f'{DIES[c.data.weekday()]} {fmt(c.ini)}'))
        t = None if nomes_aules else _torn_ok(s.torn, c.ini, c.fi)
        if t is None:
            inf.no_avaluables['R1-TORN'] += 1
        elif not t:
            inf.violacions.append(Violacio('R1-TORN', (sid,), f'{s.torn}: {fmt(c.ini)}-{fmt(c.fi)}'))
        if nomes_aules:
            inf.no_avaluables['R2-FINESTRA'] += 1   # l'horari no es pot moure: la finestra no és cosa seva
        moguda = (c.data, c.ini) != (s.data, s.ini)
        if c.data != s.data and c.data in base.dies_sense_classe:
            inf.violacions.append(Violacio('R2-CALENDARI', (sid,), f'{c.data}: dia sense cap classe a la partida '
                                                                    f'(festiu o no lectiu)'))
        elif moguda and any(c.ini < b and c.fi > a for a, b in base.aturades.get(c.data, ())) and not (
                # /challenge 07/11/2026: una sessió que la partida ja posa en un dia aturat (setmana d'avaluació amb
                # classes) es pot canviar d'hora aquell mateix dia; el que no es pot és portar-n'hi una de fora
                c.data == s.data and any(s.ini < b and s.fi > a for a, b in base.aturades.get(s.data, ()))):
            # calendari oficial: festiu, no lectiu o aturada (Comunitària, Activitats Campus); només si s'hi mou
            inf.violacions.append(Violacio('R2-CALENDARI', (sid,), f'{c.data} {fmt(c.ini)}: calendari oficial '
                                                                    f'(festiu, no lectiu o aturada)'))
        if not nomes_aules and not _dins_finestra(c.ini, c.fi):
            inf.violacions.append(Violacio('R2-FINESTRA', (sid,), f'{fmt(c.ini)}-{fmt(c.fi)}'))
        if s.sense_espai:
            # doble titulació: no necessita espai (Nacho 05/11/2026); l'aula que porti no es mira
            inf.no_avaluables['ESPAI-DOBLE'] += 1
            continue
        if not c.aula:
            if s.tipus != 'PLAB':
                inf.violacions.append(Violacio('R5-SENSE-AULA', (sid,)))
        elif c.aula not in base.aules and (c.aula != s.aula or (a_traslladar(c.aula) and s.tipus != 'PLAB')):
            inf.violacions.append(Violacio('R3-AULA', (sid,), c.aula))
        elif c.aula in base.aules and (c.aula != s.aula or
                                       (s.tipus != 'PLAB' and base.aules[c.aula].tipus == 'Laboratoris docents')):
            permesos = _tipus_permesos(base, s)
            if not _espai_ok(base, s, c.aula):
                inf.violacions.append(Violacio('R3-TIPUS', (sid,), f'{c.aula} és «{base.aules[c.aula].tipus}»; '
                                                                    f'cal {" o ".join(sorted(permesos))}'))
        for t in base.tancaments:
            if c.aula == t.aula and t.data_ini <= c.data <= t.data_fi and c.ini < t.fi and c.fi > t.ini:
                inf.violacions.append(Violacio('R3-TANCADA', (sid,), f'{c.aula} tancada {t.data_ini}..{t.data_fi}'))
                break


def _compartides_i_aforament(base: Base, col: dict[str, Colocada], inf: Informe) -> None:
    grups: dict[str, list[Colocada]] = collections.defaultdict(list)
    for c in col.values():
        grups[c.s.unitat].append(c)
    for unitat, cs in grups.items():
        if len({(c.data, c.ini) for c in cs}) > 1:
            inf.violacions.append(Violacio('R4-COMPARTIDA', tuple(sorted(c.s.id for c in cs)), unitat))
        per_aula: dict[str, list[Colocada]] = collections.defaultdict(list)
        for c in cs:
            if c.aula in base.aules and not c.s.sense_espai:
                per_aula[c.aula].append(c)
        for aula, xs in per_aula.items():
            n = sum(c.s.alumnes for c in xs)
            if n > base.aules[aula].capacitat:
                inf.violacions.append(Violacio('R3-AFORAMENT', tuple(sorted(c.s.id for c in xs)),
                                               f'{n} alumnes a {aula} ({base.aules[aula].capacitat})'))


def _solapaments(base: Base, col: dict[str, Colocada], inf: Informe) -> None:
    per_data: dict[dt.date, list[Colocada]] = collections.defaultdict(list)
    for c in col.values():
        per_data[c.data].append(c)
    vist: set = set()
    for data in sorted(per_data):
        cs = sorted(per_data[data], key=lambda c: (c.ini, c.s.id))
        for i, a in enumerate(cs):
            for b in cs[i + 1:]:
                if b.ini >= a.fi:
                    break
                if a.s.unitat == b.s.unitat:
                    continue
                parell = tuple(sorted((a.s.unitat, b.s.unitat)))
                ids = tuple(sorted((a.s.id, b.s.id)))
                if (a.aula and a.aula == b.aula and not (a.s.sense_espai or b.s.sense_espai)
                        and ('A', parell, a.aula) not in vist):
                    vist.add(('A', parell, a.aula))
                    inf.violacions.append(Violacio('R4-AULA', ids, f'{a.aula} {data} {fmt(max(a.ini, b.ini))}'))
                for d in sorted(a.s.docents & b.s.docents):
                    if ('D', parell, d) not in vist:
                        vist.add(('D', parell, d))
                        inf.violacions.append(Violacio('R4-DOCENT', ids, d))
                if _alumnat_comparteix(a.s, b.s) and ('E', parell) not in vist:
                    vist.add(('E', parell))
                    inf.violacions.append(Violacio('R4-ALUMNAT', ids, '|'.join(sorted(set(a.s.cohorts) & set(b.s.cohorts)))))
                # Jordi González (30/10): un PLAB restringeix la TE i el PAUL de la mateixa assignatura
                tipus = {a.s.tipus, b.s.tipus}
                if (a.s.codi == b.s.codi and 'PLAB' in tipus and tipus & {'TE', 'PAUL'}
                        and ('P', parell) not in vist):
                    vist.add(('P', parell))
                    inf.violacions.append(Violacio('R4-PLAB', ids, f'{a.s.codi} {data} {fmt(max(a.ini, b.ini))}'))


def _reserva(base: Base, col: dict[str, Colocada], inf: Informe) -> None:
    ordinaries = {a for a, x in base.aules.items() if x.ordinaria}
    if len(ordinaries) < RESERVA_MIN:
        return
    ocup: dict[tuple, set] = collections.defaultdict(set)
    dates = set()
    for c in col.values():
        dates.add(c.data)
        if c.aula in ordinaries and not c.s.sense_espai:
            for f0 in FRANGES:
                if c.ini < f0 + 60 and c.fi > f0:
                    ocup[(c.data, f0)].add(c.aula)
    for data in sorted(dates):
        for f0 in FRANGES:
            lliures = len(ordinaries) - len(ocup.get((data, f0), ()))
            if lliures < RESERVA_MIN:
                inf.violacions.append(Violacio('R8-RESERVA', (), f'{data} {fmt(f0)}: {lliures} lliures'))


def _objectius(base: Base, col: dict[str, Colocada]) -> dict:
    canvis_franja = sum(1 for c in col.values() if (c.data, c.ini) != (c.s.data, c.s.ini))
    canvis_aula = sum(1 for c in col.values() if c.s.aula and not a_traslladar(c.s.aula) and not c.s.sense_espai
                      and c.aula != c.s.aula)
    # agenda d'un grup d'alumnes = (cohort, línia, data): sessions de teoria de la línia + subgrups
    agenda: dict[tuple, list[Colocada]] = collections.defaultdict(list)
    for c in col.values():
        for coh in c.s.cohorts:
            agenda[(coh, c.s.linia, c.data, c.s.num_grup if c.s.tipus != 'TE' else '*')].append(c)
    # reunim, per a cada subgrup, la seva teoria (*) i les seves pràctiques
    per_subgrup: dict[tuple, list[Colocada]] = collections.defaultdict(list)
    linies: dict[tuple, set] = collections.defaultdict(set)
    for (coh, lin, data, sg), cs in agenda.items():
        linies[(coh, lin, data)].add(sg)
    for (coh, lin, data), sgs in linies.items():
        teoria = agenda.get((coh, lin, data, '*'), [])
        reals = [x for x in sgs if x != '*'] or ['*']
        for sg in reals:
            per_subgrup[(coh, lin, data, sg)] = teoria + (agenda.get((coh, lin, data, sg), []) if sg != '*' else [])
    mortes = desplac = edifici = 0
    for cs in per_subgrup.values():
        cs = sorted({id(c): c for c in cs}.values(), key=lambda c: c.ini)
        for a, b in zip(cs, cs[1:]):
            gap = b.ini - a.fi
            mateix_torn = (a.fi <= MATI[1]) == (b.ini < MATI[1])
            if gap > 0 and mateix_torn:
                mortes += gap
            if a.aula and b.aula and a.aula != b.aula:
                desplac += 1
                ea, eb = base.aules.get(a.aula), base.aules.get(b.aula)
                if (ea.edifici if ea else a.aula.split('/')[0]) != (eb.edifici if eb else b.aula.split('/')[0]):
                    edifici += 1
    # R6 (indicador provisional, definició pendent de l'Escola): aula base de la teoria de cada grup
    # (cohort + línia) i canvis TE<->PAUL fora del «passadís» (aproximat com edifici/planta del codi).
    aules_te: dict[tuple, set] = collections.defaultdict(set)
    for c in col.values():
        if c.s.tipus == 'TE' and c.aula:
            for coh in c.s.cohorts:
                aules_te[(coh, c.s.linia)].add(c.aula)
    extra = sum(len(v) - 1 for v in aules_te.values())
    fora_passadis = 0
    for cs in per_subgrup.values():
        cs = sorted({id(c): c for c in cs}.values(), key=lambda c: c.ini)
        for a, b in zip(cs, cs[1:]):
            if {a.s.tipus, b.s.tipus} == {'TE', 'PAUL'} and a.aula and b.aula and passadis(a.aula) != passadis(b.aula):
                fora_passadis += 1
    return {'hores_mortes_min': mortes, 'desplacaments_aula': desplac, 'desplacaments_edifici': edifici,
            'canvis_franja': canvis_franja, 'canvis_aula': canvis_aula,
            'r6_aules_te_extra_per_grup': extra, 'r6_canvis_te_paul_fora_passadis': fora_passadis,
            'sessions_avaluades': len(col)}


def passadis(aula: str) -> str:
    """«Q1/1011» -> «Q1/1» (espina i planta). Nacho Beneite (05/11/2026): Q4/0xxx és planta baixa i Q4/1xxx
    primera planta, igual a totes les espines; si cal, l'Escola passa dades per espina. Segueix sent un
    indicador (R6), no una regla dura."""
    edif, _, num = aula.partition('/')
    return f'{edif}/{num[:1]}'


def _partida(base: Base) -> dict[str, Colocada]:
    return {sid: Colocada(s, s.data, s.ini, s.aula) for sid, s in base.sessions.items()}


def _solapaments_de_partida(base: Base) -> set:
    inf = Informe()
    _solapaments(base, _partida(base), inf)
    return {(v.regla, v.sessions) for v in inf.violacions if v.regla in ('R4-DOCENT', 'R4-ALUMNAT', 'R4-PLAB')}


def _marca_heretades(base: Base, col: dict[str, Colocada], inf: Informe) -> None:
    de_partida = _solapaments_de_partida(base)
    for v in inf.violacions:
        cs = [col.get(sid) for sid in v.sessions]
        # posar aula on no n'hi ha sí que és cosa de la proposta, també per a les fixades
        # una doble titulació no té espai propi: treure-li l'aula no la fa deixar de ser «sense moure» (07/11/2026)
        if v.regla not in ('R5-SENSE-AULA', 'R3-AULA', 'R3-TANCADA') and cs and all(
                c is not None and c.s.fixada and (c.data, c.ini) == (c.s.data, c.s.ini)
                and (c.s.sense_espai or c.aula == c.s.aula)
                for c in cs):  # /challenge H1: si la proposta hi ha posat l'aula, no és heretat
            v.heretada = 'fixada'
        elif v.regla in ('R4-DOCENT', 'R4-ALUMNAT', 'R4-PLAB') and (v.regla, v.sessions) in de_partida:
            v.heretada = 'partida'


def _vs_referencia(base: Base, col: dict[str, Colocada], referencia: list[Fila]) -> dict:
    """Pregunta 2 (contingència): quant canvia la proposta respecte d'una altra (la pròpia d'abans)."""
    ref = _col_loca(base, referencia, Informe())
    franja = sum(1 for sid, c in col.items() if sid in ref and (c.data, c.ini) != (ref[sid].data, ref[sid].ini))
    # una sessió cancel·lada i recuperada és un canvi, encara que la referència no la tingui (/challenge H5)
    franja += sum(1 for sid in col if sid not in ref and sid in base.cancellades)
    aula = sum(1 for sid, c in col.items() if sid in ref and c.aula != ref[sid].aula)
    return {'canvis_franja_vs_referencia': franja, 'canvis_aula_vs_referencia': aula}


def avalua(base: Base, files: list[Fila], relaxacions: list[Relaxacio] | None = None,
           referencia: list[Fila] | None = None, nomes_aules: bool = False) -> Informe:
    """`nomes_aules`: pregunta 1 de la variant B, es reparteixen aules amb l'horari d'avui (sense torns nous)."""
    inf = Informe(relaxacions=list(relaxacions or []))
    col = _col_loca(base, files, inf)
    _per_sessio(base, col, inf, nomes_aules)
    _compartides_i_aforament(base, col, inf)
    _solapaments(base, col, inf)
    _reserva(base, col, inf)
    _marca_heretades(base, col, inf)
    inf.objectius = _objectius(base, col)
    if referencia is not None:
        inf.objectius.update(_vs_referencia(base, col, referencia))
    for v in inf.violacions:
        for r in inf.relaxacions:
            # /challenge I1: «*» només per a R8 (per sessions cal citar-les), justificació obligatòria, i el que
            # buida la proposta (faltes, format, recuperacions) no es pot relaxar
            if v.regla in NO_RELAXABLES or not r.justificacio:
                continue
            cobreix = (bool(set(v.sessions) & r.sessions) if v.sessions
                       else '*' in r.sessions or any(v.detall.startswith(x) for x in r.sessions))
            if r.restriccio == v.regla and cobreix:
                v.declarada = True
                break
    return inf
