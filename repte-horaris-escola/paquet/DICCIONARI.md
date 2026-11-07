# Diccionari del paquet de dades — repte d'horaris i espais

Paquet generat el 05/11/2026 per `eines/preparar_paquet.py` a partir dels extractes de Sigma del pla
docent 2026-27 de l'Escola d'Enginyeria (UAB), vuit graus i tres màsters, amb els aclariments de l'Escola del
05/11 aplicats el 07/11/2026 (`eines/aclariments.py`). **Sense dades personals**: el professorat apareix només
com a identificador pseudònim estable (`Dnnn`; n'apareixen 413 diferents), el mateix a tots els fitxers.

Tots els fitxers són CSV en UTF-8, separats per comes, amb capçalera. Hores en format `HH:MM` (24 h),
dates en ISO (`AAAA-MM-DD`), dies `L M X J V`. Un camp amb diversos valors els separa amb `|`.

## Fitxers

| Fitxer | Files | Què és |
|---|---:|---|
| `sessions.csv` | 17.026 | **Una fila per sessió de classe datada** (la unitat que es planifica) |
| `aules.csv` | 56 | Inventari d'aules de l'Escola amb tipus i capacitat |
| `activitats.csv` | 1.930 | Agrupació informativa: sessions d'un mateix grup, dia i hora al llarg del semestre |
| `proposta_partida.csv` | 17.026 | L'horari actual escrit en el format de lliurament (plantilla i referència) |
| `plans.csv` | 11 | Plans d'estudis inclosos i data de l'extracte de cada un |
| `calendari.csv` | 32 | Festius, dies no lectius, aturades i setmana intrasemestral d'avaluació del curs 2026-27: `data, tipus (festiu, no_lectiu, aturada, avaluacio), h_ini, h_fi, motiu, font`. Fonts: calendari acadèmic de l'Escola d'Enginyeria 2026-27 (uab.cat/ca/enginyeria/doc/calendariacademic202627.pdf) i, per als festius, el calendari general de la UAB (orientatiu) |
| `cobertura.json` | — | Recomptes del paquet (sessions, sense aula, codis d'aula que casen…) |

## `sessions.csv`

| Camp | Significat |
|---|---|
| `id_sessio` | Identificador de la sessió (`S00001`…). És la clau de la proposta |
| `activitat_id` | Activitat setmanal a què pertany (vegeu `activitats.csv`) |
| `id_compartida` | Si no és buit: la sessió és **la mateixa classe física** que les altres amb el mateix valor (docència compartida entre plans o titulacions). Compta una sola vegada i s'ha de moure junta |
| `codi` | Codi de l'assignatura |
| `assignatura` | Nom de l'assignatura |
| `tipus` | Tipus d'activitat, del prefix del grup: `TE` teoria, `PAUL` problemes d'aula, `PLAB` laboratori, `SEM` seminari |
| `grup` | Grup de Sigma (`TE/81`, `PAUL/811`…). Els subgrups d'un grup de teoria comparteixen els primers dígits (TE/81 → PAUL/811, 812…) |
| `semestre` | `C/1` primer semestre, `C/2` segon, `A/0` anual (camp T/V de Sigma) |
| `data` | Data de la sessió a l'horari de partida |
| `setmana` | Setmana ISO (`2026-W37`). **Una proposta pot canviar el dia, però no la setmana** |
| `dia` | Dia de la setmana a l'horari de partida |
| `h_ini`, `h_fi` | Hora d'inici i de final a l'horari de partida |
| `durada_min` | Durada en minuts. **No es pot canviar** |
| `alumnes` | Alumnes del grup. A les teories, els matriculats (camp Alum). Els PAUL, PLAB i SEM no tenen matrícula pròpia i Sigma hi posa 0: s'hi posen els alumnes de la teoria repartits entre els grups (vegeu `alumnes_origen`) |
| `capacitat_grup` | Places previstes del grup (camp GrCp) |
| `aula_partida` | Aula on es fa avui (camp Recurs). **Buit en 5.914 sessions** (el 35 %) |
| `aules_addicionals_partida` | Altres aules que la sessió ocupa avui, si en té més d'una (13 sessions) |
| `plans` | Pla o plans d'estudis en què surt la sessió (vegeu `plans.csv`) |
| `titulacions_curs` | Cohorts d'alumnat que la cursen: `TITULACIÓ:curs` (`GED:1r`, `GEET:2n|GEST:2n`…). Als màsters el curs és `M` (`MRICSE:M`). `?` = curs desconegut |
| `dc` | Docència compartida a Sigma: `P` principal, `S` secundària, buit si no ho és |
| `torn_requerit` | Torn que li toca segons la restricció 1: `mati` o `tarda` (`conflicte` si les seves cohorts en demanessin de diferents: des del 07/11 no n'hi ha cap) |
| `fixada` | Buit si es pot moure. Si no, el motiu: `R1: GEI 1r` (grups de GEI i GEET+GEST de 1r i 2n, no es toquen) o `R7: PLAB` (laboratori amb horari fix) |
| `docents` | Identificadors pseudònims del professorat **assignat al grup** (no a cada sessió concreta) |
| `alumnes_origen` | D'on surt `alumnes`: `sigma` (camp Alum), `estimat` (alumnes de la teoria de l'assignatura dividits pel nombre de grups del mateix tipus; 184 sessions) o `sense_dada` (0 a Sigma i cap teoria amb alumnes: 636 sessions, l'aforament no s'hi pot comprovar) |
| `sense_espai` | `1` als grups de doble titulació (número que comença per 5: TE/51, PAUL/511…): docència alternativa per a l'alumnat de doble grau, sense espai propi. El verificador no els demana aula (1.169 sessions) |

## `aules.csv`

| Camp | Significat |
|---|---|
| `aula` | Codi de l'espai (`Q1/1011`: edifici Q1, planta 1, número 011) |
| `edifici` | Edifici |
| `tipus` | `Aules docents` (21), `Laboratoris docents` (25), `Seminaris` (8), `Aules informàtiques` (2) |
| `descripcio` | Descripció de l'inventari |
| `capacitat` | Capacitat de docència |
| `ordinaria` | 1 si és una aula ordinària (`Aules docents`), la que compta per a la restricció 8 |

Cinc codis d'aula de l'horari de partida no són a l'inventari (`B3/0021`, `J/012`, `J/102`, `J/124`,
`QC/1082`, 407 sessions): són espais d'altres centres. Les sessions de les aules J s'han de portar a l'aulari
(Escola, 04/11); a B3/0021 i QC/1082 s'hi poden quedar, però no s'hi pot portar cap sessió nova.

## `activitats.csv`

Una fila per (codi, grup, semestre, dia, hores): `activitat_id`, `assignatura`, `tipus`, `n_sessions`,
`setmana_primera`, `setmana_ultima`, `alumnes`, `aules_partida` (totes les que fa servir),
`sessions_sense_aula`, `titulacions_curs`, `torn_requerit`, `fixada`, `docents`. És una ajuda per
raonar per setmanes tipus; el verificador treballa per sessions.

## `plans.csv`

| `pla` | Titulació | Extracte |
|---|---|---|
| 1394 | Enginyeria de Dades (GED) | 30/10/2026 |
| 1461 | Enginyeria Química (GEQ) | 30/10/2026 |
| 1626 | Enginyeria Informàtica (GEI), pla nou, 1r i 2n | 03/11/2026 |
| 958 | Enginyeria Informàtica (GEI), pla antic, mencions i 4t | 03/11/2026 |
| 1640 | GEET + GEST, pla nou, 1r i 2n | 30/10/2026 |
| 1365 | GEET + GEST, pla antic, 3r i 4t | 30/10/2026 |
| 1667 | Gestió de Ciutats Intel·ligents i Sostenibles (GCIS) | 30/10/2026 |
| 1673 | Intel·ligència Artificial (GIA) | 03/11/2026 |
| 1530 | Màster RICSE (`MRICSE:M`) | 03/11/2026 |
| 1560 | Màster en Enginyeria Biològica i Ambiental (`MEBA:M`) | 03/11/2026 |
| 1646 | Màster en Enginyeria de Telecomunicació (`MET:M`) | 03/11/2026 |

## Com s'ha construït (perquè pugueu confiar-hi o discutir-ho)

- Una sessió és (codi, grup, data, hora d'inici, hora de final). Si surt a dos extractes
  (una assignatura compartida entre el pla vell i el nou) es compta una vegada.
- Dues sessions de codis diferents que són la mateixa classe (camp DC, mateixa data, hores i aula, o
  mateix grup quan no hi ha aula) reben el mateix `id_compartida` (964 grups, 2.004 sessions).
- El curs de cada assignatura surt del fitxer «codi d'assignatura → curs» de l'Escola i, si no hi és,
  del pla docent treballat de la titulació.
- Els exàmens (`EXAM`, 308 sessions) no formen part del repte.
- Aclariments de l'Escola (05/11/2026), aplicats al paquet: el curs de 102436 (GEQ 3r) i de 102710 (GEST 3r i
  GEI+GEST 4t); els grups de doble titulació, sense espai propi; i els alumnes dels PAUL, PLAB i SEM.

## Ús de les dades

Les dades són **pseudonimitzades, no anònimes**: combinant assignatura, grup i horari amb les guies
docents públiques es podria arribar a saber qui és un docent. No ho intenteu: les dades són per a la
hackató i no es poden reutilitzar ni publicar fora d'ella.

## Limitacions conegudes

- **Docents per grup, no per sessió.** Si un grup té dos docents, no sabem quin fa cada sessió: el
  verificador suposa que tots dos hi són. Per això els solapaments de docent que ja hi ha a l'horari
  de partida no compten (es diuen «heretats»); els nous, sí.
- **Alumnat per cohort.** Sabem la titulació i el curs de cada assignatura, no la matrícula de cada
  estudiant. Dos grups xoquen si són de la mateixa cohort i (un és la teoria de la línia de l'altre, o
  tenen el mateix número de subgrup). Les optatives fan que això sigui una aproximació.
- 81 grups (855 sessions) no tenen cap docent al llistat.
- `alumnes` = 0 en 636 sessions (`alumnes_origen = sense_dada`, sense comptar les dobles): per a aquestes
  l'aforament no es pot comprovar.
- Màster en Visió per Computador: no hi és (l'Escola no n'ha passat l'extracte en brut de Sigma).
- 4 assignatures (407 sessions) tenen el curs desconegut (`?`): 102764, 102767, 102771, 103806.
- GIA: l'extracte en brut inclou 15 dels 39 codis del pla treballat.
