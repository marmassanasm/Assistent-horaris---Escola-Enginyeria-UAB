# validacio/ — ocupació real d'una setmana (opcional)

`geres-ocupacio-setmana-2026-10-05.csv` és el llistat d'ocupació del GERES (Sigma) del **05 al 09/10/2026**, que
l'Escola ha passat el 05/11/2026: què hi havia realment a cada espai cada hora. **No és cap entrada del repte**: serveix
per contrastar el model amb una setmana real. Els equips poden ignorar-lo. Es regenera amb
`python eines/preparar_geres.py` (necessita el brut, que no es versiona).

Pseudonimitzat: cap nom ni DNI. `docents` porta els `Dnnn` de `paquet/sessions.csv` (`D?` = no identificat). Les
reserves que no són docència (`tipus_reserva = no_docent`) només porten espai, dia i hora.

## Camps

- `espai`, `data`, `dia`, `h_ini`, `h_fi`, `durada_min`: com a `paquet/`.
- `tipus_reserva`: `docent` o `no_docent`.
- `codi`, `grup_num`, `assignatura`: `grup_num` és el número (`211` = `TE/211`, `PAUL/211`…; el GERES no diu el tipus).
- `estudis`: codis d'estudi del GERES (no són els plans de Sigma), separats per `|`.
- `alumnes_matriculats`: buit si el GERES diu «sense grup de matrícula».
- `id_sessio_paquet`: la sessió de `paquet/sessions.csv` amb el mateix codi, grup, data i hora d'inici, si n'hi ha una de sola.

## Limitacions mesurades (744 files, 50 espais; 679 reserves docents, 65 no docents)

- **Docents**: 834 mencions, 741 (88,8 %) amb `Dnnn`. De 274 noms diferents se'n resolen 244; dels 30 restants, 9 no
  surten al brut de Sigma, 18 fan exactament els mateixos grups que un altre docent (el `Dnnn` no es pot distingir) i 3
  no fan cap grup amb sessions al paquet.
- **Cobertura**: de les 769 sessions del paquet d'aquella setmana, 649 surten al GERES; 30 reserves docents del GERES no
  tenen sessió al paquet (grups fora del repte o canvis posteriors a l'extracte).
- **Coherència**: 646 reserves s'enllacen amb una sola sessió; 645 són al mateix espai que l'horari de partida (quan en
  té) i en 603 de 603 comparables els docents del GERES són dins els del grup al paquet.
- Una sola setmana de classes normals: no diu res de la resta del semestre. L'ocupació real pot incloure canvis d'aula
  posteriors a l'extracte de Sigma.
