"""Model del repte: sessions de base, aules i proposta. Només biblioteca estàndard."""
from __future__ import annotations

import csv
import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

DIES = ('L', 'M', 'X', 'J', 'V')
MATI = (8 * 60 + 30, 14 * 60 + 30)    # 8.30-14.30
# 14.30-21.00. La línia mestra 2 deia 20.30; Fernando (04/11/2026): «L'horari d'edifici és de les 8:30 fins les
# 21:00 que es tanca. Pots ampliar la franja de les 20:30 a les 21:00».
TARDA = (14 * 60 + 30, 21 * 60)
TIPUS_ORDINARIA = 'Aules docents'
# Aules fora de l'aulari: les J s'han de portar a l'aulari (Fernando 04/11/2026: «Las J se traen para aquí.
# El resto donde están»). B3/0021 i QC/1082 es poden quedar on són.
AULES_A_TRASLLADAR = ('J/',)


def a_traslladar(aula: str) -> bool:
    return bool(aula) and aula.startswith(AULES_A_TRASLLADAR)


def hm(s: str) -> int:
    h, m = s.strip().split(':')
    return int(h) * 60 + int(m)


def fmt(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


@dataclass(frozen=True)
class Aula:
    aula: str
    edifici: str
    tipus: str
    capacitat: int
    descripcio: str = ''

    @property
    def ordinaria(self) -> bool:
        return self.tipus == TIPUS_ORDINARIA

    @property
    def integrat(self) -> bool:
        """Laboratori integrat (Q2/0007-0019, Q3/0007): dotació especial de PC, no lab de pràctiques específic."""
        return 'integrat' in self.descripcio.lower()


@dataclass
class Sessio:
    id: str
    codi: str
    tipus: str
    grup: str
    data: dt.date
    dia: str
    ini: int
    durada: int
    alumnes: int
    aula: str
    cohorts: tuple[str, ...]          # ('GED:1r', ...)
    torn: str                          # mati | tarda | conflicte | desconegut
    fixada: str                        # '' si es pot moure; si no, el motiu (R1/R7)
    docents: frozenset[str]
    compartida: str = ''               # id_compartida ('' si no ho és)
    activitat: str = ''
    # grup de doble titulació (TE/51, PAUL/511…): «docència alternativa per a l'alumnat de doble grau, no grups
    # nous; el grup 51 no necessita espai» (Nacho Beneite, 05/11/2026). Fora de les regles d'espai.
    sense_espai: bool = False

    @property
    def fi(self) -> int:
        return self.ini + self.durada

    @property
    def unitat(self) -> str:
        """Una sessió compartida entre titulacions compta una sola vegada (restricció 4)."""
        return self.compartida or self.id

    @property
    def num_grup(self) -> str:
        return self.grup.split('/')[-1]

    @property
    def linia(self) -> str:
        """Línia del grup: TE/81 -> 81, PAUL/811 -> 81, TE/310 -> 31 (definició adoptada)."""
        n = self.num_grup
        if self.tipus == 'TE':
            return n[:-1] if len(n) >= 3 and n.endswith('0') else n
        return n[:-1] if len(n) >= 3 else n


@dataclass(frozen=True)
class Tancament:
    """Escenari de contingència: una aula que no es pot fer servir entre dues dates (i, si cal, hores)."""
    aula: str
    data_ini: dt.date
    data_fi: dt.date
    ini: int = 0
    fi: int = 24 * 60


@dataclass
class Base:
    sessions: dict[str, Sessio]
    aules: dict[str, Aula]
    ordre: list[str] = field(default_factory=list)
    tancaments: list[Tancament] = field(default_factory=list)
    escenari: str = ''
    cancellades: dict[str, dt.date] = field(default_factory=dict)  # id_sessio -> recuperar fins a
    # dies feiners del curs sense cap classe a la partida: festius o no lectius (aproximació, /challenge I3)
    dies_sense_classe: frozenset = frozenset()
    # calendari oficial (paquet/calendari.csv): data -> franges aturades [(ini, fi)]; tot el dia = (0, 1440)
    aturades: dict = field(default_factory=dict)


def semestre_de(data: dt.date) -> int:
    """Per data, no pel camp T/V: a Sigma hi ha sessions C/1 al febrer i C/2 al setembre (54)."""
    return 1 if data.month >= 9 or data.month == 1 else 2


def _read(path: Path) -> list[dict]:
    with open(path, encoding='utf-8-sig', newline='') as f:   # un CSV desat amb Excel porta BOM
        return list(csv.DictReader(f))


def carrega_base(paquet: Path, semestre: int | None = None, escenari: Path | None = None) -> Base:
    """El paquet, opcionalment reduït a un semestre i amb un escenari (sessions extra, aules tancades)."""
    paquet = Path(paquet)
    aules = {r['aula']: Aula(r['aula'], r['edifici'], r['tipus'].strip(), int(r['capacitat']),
                             (r.get('descripcio') or '').strip())
             for r in _read(paquet / 'aules.csv')}
    files = _read(paquet / 'sessions.csv')
    amb_classe = {dt.date.fromisoformat(r['data']) for r in files}
    lliures: set = set()
    if amb_classe:
        d, fi = min(amb_classe), max(amb_classe)
        while d <= fi:
            if d.weekday() < 5 and d not in amb_classe:
                lliures.add(d)
            d += dt.timedelta(days=1)
    tancaments: list[Tancament] = []
    nom = ''
    if escenari:
        escenari = Path(escenari)
        cfg = json.loads((escenari / 'escenari.json').read_text(encoding='utf-8'))
        nom = cfg.get('nom', escenari.name)
        if cfg.get('sessions_extra'):
            files = files + _read(escenari / cfg['sessions_extra'])
        for t in cfg.get('aules_tancades', []):
            tancaments.append(Tancament(t['aula'], dt.date.fromisoformat(t['data_ini']),
                                        dt.date.fromisoformat(t['data_fi']),
                                        hm(t['h_ini']) if t.get('h_ini') else 0,
                                        hm(t['h_fi']) if t.get('h_fi') else 24 * 60))
    ses: dict[str, Sessio] = {}
    ordre = []
    for r in files:
        if semestre and semestre_de(dt.date.fromisoformat(r['data'])) != semestre:
            continue
        s = Sessio(
            id=r['id_sessio'], codi=r['codi'], tipus=r['tipus'], grup=r['grup'],
            data=dt.date.fromisoformat(r['data']), dia=r['dia'], ini=hm(r['h_ini']),
            durada=int(r['durada_min']), alumnes=int(r['alumnes'] or 0), aula=r['aula_partida'],
            cohorts=tuple(x for x in r['titulacions_curs'].split('|') if x),
            torn=r['torn_requerit'], fixada=r['fixada'],
            docents=frozenset(x for x in r['docents'].split('|') if x),
            compartida=r.get('id_compartida', ''), activitat=r.get('activitat_id', ''),
            sense_espai=(r.get('sense_espai') or '').strip() == '1')
        if s.id in ses:
            raise ValueError(f'sessió repetida a la base: {s.id}')
        ses[s.id] = s
        ordre.append(s.id)
    cancellades: dict[str, dt.date] = {}
    if escenari:
        for g in cfg.get('alumnes', []):   # el grup creix (o es redueix): nova matrícula
            for s in ses.values():
                if s.codi == g['codi'] and s.grup == g['grup']:
                    s.alumnes = int(g['alumnes'])
        for c in cfg.get('cancellades', []):
            if c['id_sessio'] in ses:
                cancellades[c['id_sessio']] = dt.date.fromisoformat(c['recuperar_fins'])
    aturades: dict = {}
    if (paquet / 'calendari.csv').exists():
        for r in _read(paquet / 'calendari.csv'):
            d = dt.date.fromisoformat(r['data'])
            franja = (hm(r['h_ini']), hm(r['h_fi'])) if r.get('h_ini') else (0, 24 * 60)
            aturades.setdefault(d, []).append(franja)
    return Base(ses, aules, ordre, tancaments, nom, cancellades, frozenset(lliures), aturades)


@dataclass
class Fila:
    id: str
    dia: str
    h_ini: str
    aula: str
    linia: int
    data: str = ''   # només per a sessions cancel·lades d'un escenari: la data de recuperació


def llegeix_proposta(path: Path) -> list[Fila]:
    out = []
    with open(path, encoding='utf-8-sig', newline='') as f:
        rd = csv.DictReader(f)
        falten = {'id_sessio', 'dia', 'h_ini', 'aula'} - set(rd.fieldnames or [])
        if falten:
            raise ValueError(f"a la proposta li falten les columnes {sorted(falten)}")
        for i, r in enumerate(rd, start=2):
            out.append(Fila(r['id_sessio'].strip(), (r['dia'] or '').strip().upper(),
                            (r['h_ini'] or '').strip(), (r['aula'] or '').strip(), i,
                            (r.get('data') or '').strip()))
    return out


@dataclass(frozen=True)
class Relaxacio:
    restriccio: str
    sessions: frozenset[str]
    justificacio: str


def llegeix_relaxacions(path: Path | None) -> list[Relaxacio]:
    if not path:
        return []
    out = []
    for r in _read(Path(path)):
        out.append(Relaxacio(r['restriccio'].strip().upper(),
                             frozenset(x.strip() for x in r['sessions'].split('|') if x.strip()),
                             r.get('justificacio', '').strip()))
    return out
