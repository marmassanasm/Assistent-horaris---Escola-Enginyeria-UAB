# Repte de l'Escola: horaris i espais 2027-28 (UAB THE HACK! 2026)

Aquí teniu les dades i el verificador del repte. L'enunciat és el PDF de la carpeta `ENUNCIAT`.

## Què hi ha

- `paquet/`: les dades, en CSV i sense cap dada personal. Comenceu per `paquet/DICCIONARI.md`.
- `horaris/`: el verificador, el mateix que farà servir el jurat. Python 3.10 o més nou, sense instal·lar res.
- `validacio/` (opcional): l'ocupació real d'una setmana d'octubre, per contrastar el model. No és cap entrada del
  repte; llegiu-ne el `LLEGIU-ME.md`.

## Primera prova

Des d'aquesta carpeta:

```
python -m horaris check paquet/proposta_partida.csv
python -m horaris check paquet/proposta_partida.csv --semestre 2
python -m horaris check paquet/proposta_partida.csv --semestre 2 --nomes-aules
```

La primera ordre avalua l'horari d'avui i surt `NO VALIDA`: és el punt de partida. Totes les opcions:
`python -m horaris check --help`.

## Ús de les dades

Les dades són pseudonimitzades, no anònimes. Són només per a la hackató: no les publiqueu ni les reutilitzeu fora
d'ella, i no intenteu identificar ningú.
