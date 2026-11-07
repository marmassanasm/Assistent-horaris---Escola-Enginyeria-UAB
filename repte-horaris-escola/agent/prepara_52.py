"""Preparació del nivell 5.2: resum de les activitats del semestre 2.

Executa des de la carpeta principal del repte:
    python -m agent.prepara_52

No modifica cap fitxer original. Crea:
    agent/activitats_semestre_2.csv
    agent/resum_52.txt
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from horaris.model import carrega_base, DIES, fmt

ARREL = Path(__file__).resolve().parents[1]
PAQUET = ARREL / "paquet"
SORTIDA = Path(__file__).resolve().parent


def escriu_csv(path: Path, files: list[dict], camps: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=camps)
        w.writeheader()
        w.writerows(files)


def main() -> None:
    base = carrega_base(PAQUET, semestre=2)
    per_activitat = defaultdict(list)
    for s in base.sessions.values():
        per_activitat[s.activitat or s.id].append(s)

    resultats = []
    incidencies = []
    for activitat, sessions in sorted(per_activitat.items()):
        s0 = sessions[0]
        combinacions = {(s.dia, s.ini, s.durada) for s in sessions}
        setmanes = {s.data.isocalendar().week for s in sessions}
        unitats_compartides = sorted({s.compartida for s in sessions if s.compartida})
        aules = sorted({s.aula for s in sessions if s.aula})
        resultats.append({
            "activitat_id": activitat,
            "assignatura": s0.codi,
            "grup": s0.grup,
            "tipus": s0.tipus,
            "sessions": len(sessions),
            "setmanes": len(setmanes),
            "dia_actual": s0.dia,
            "hora_actual": fmt(s0.ini),
            "durada_min": s0.durada,
            "alumnes_max": max(s.alumnes for s in sessions),
            "torn": s0.torn,
            "fixada": s0.fixada,
            "aules_actuals": " | ".join(aules),
            "id_compartida": " | ".join(unitats_compartides),
            "sense_espai": int(all(s.sense_espai for s in sessions)),
        })
        if len(combinacions) != 1:
            incidencies.append(
                f"{activitat}: té més d'un dia/hora/durada dins la mateixa activitat: {sorted(combinacions)}"
            )

    camps = list(resultats[0]) if resultats else []
    escriu_csv(SORTIDA / "activitats_semestre_2.csv", resultats, camps)

    compartides = defaultdict(set)
    for s in base.sessions.values():
        if s.compartida:
            compartides[s.compartida].add(s.activitat or s.id)
    compartides_dobles = {k: v for k, v in compartides.items() if len(v) > 1}

    tipus = defaultdict(int)
    fixades = defaultdict(int)
    for s in base.sessions.values():
        tipus[s.tipus] += 1
        if s.fixada:
            fixades[s.fixada] += 1

    lines = [
        "DIAGNÒSTIC DEL NIVELL 5.2 — SEMESTRE 2",
        "=" * 48,
        f"Sessions: {len(base.sessions)}",
        f"Activitats recurrents: {len(per_activitat)}",
        f"Aules disponibles: {len(base.aules)}",
        f"Activitats compartides entre més d'un grup: {len(compartides_dobles)}",
        "",
        "Sessions per tipus:",
        *[f"  {k}: {v}" for k, v in sorted(tipus.items())],
        "",
        "Sessions fixades:",
        *[f"  {k}: {v}" for k, v in sorted(fixades.items())],
        "",
        f"Activitats amb més d'un horari intern: {len(incidencies)}",
        *incidencies[:30],
        "",
        "Fitxer detallat: agent/activitats_semestre_2.csv",
        "Aquest diagnòstic no modifica l'horari ni declara cap proposta vàlida.",
    ]
    (SORTIDA / "resum_52.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Preparació completada.")
    print(f"Sessions: {len(base.sessions)}")
    print(f"Activitats: {len(per_activitat)}")
    print(f"Activitats compartides amb més d'un activitat_id: {len(compartides_dobles)}")
    print(f"Activitats amb horaris interns diferents: {len(incidencies)}")
    print("Fitxers creats:")
    print("  agent/activitats_semestre_2.csv")
    print("  agent/resum_52.txt")


if __name__ == "__main__":
    main()
