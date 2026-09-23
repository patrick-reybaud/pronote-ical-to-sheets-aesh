#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tableau.py — emplois du temps tels que l'écran les affiche et les rend cliquables.

L'application montrait les emplois du temps en les exportant : il fallait produire un fichier,
l'ouvrir ailleurs, revenir corriger, réexporter. Ce module donne la même grille directement à
l'écran, et surtout il l'accroche à ce qu'elle représente — chaque case sait de quel cours elle
parle, qui l'accompagne et si cette affectation est verrouillée. C'est ce qui permet d'agir dessus.

La fusion des créneaux et des semaines A/B n'est pas refaite ici : elle vient de `export`, pour que
ce qu'on voit à l'écran soit exactement ce qu'on retrouvera dans le classeur ou à l'impression.
"""

from .export import blocs_jour, couleurs_aesh, couleurs_eleves
from .pronote import JOURS, PAS_MINUTES

JOURS_SEMAINE = JOURS[:5]
GRIS_LIBRE = "E8EAED"        # cours à accompagner que personne ne prend
GRIS_HORS = "F4F5F6"         # cours qu'on a décidé de ne pas accompagner


def _entetes(projet):
    h_min, h_max = projet.etat.get("plage") or (7, 18)
    return {
        "h_min": h_min, "h_max": h_max, "pas_minutes": PAS_MINUTES,
        "nb_creneaux": (h_max - h_min) * 60 // PAS_MINUTES,
        "jours": JOURS_SEMAINE,
        "semaines_types": projet.etat.get("semaines_types") or [],
    }


def _couleurs_par_id(resultat, champ_id, champ_nom, couleurs_par_nom):
    """La couleur suit la personne, pas la ligne : celle de l'écran est celle des exports."""
    par_id = {}
    for a in (resultat or {}).get("affectations") or []:
        par_id[a[champ_id]] = couleurs_par_nom.get(a[champ_nom], GRIS_LIBRE)
    return par_id


def tableau_eleves(projet, resultat=None):
    """
    Emploi du temps de chaque élève, chaque case portant l'accompagnement qui s'y rattache.

    Tous les cours de la semaine type y figurent, y compris ceux qu'on a retirés de
    l'accompagnement : les masquer donnait une grille trouée que personne ne savait relire, et
    empêchait de revenir sur la décision. Ils sont simplement grisés, avec leur motif.
    """
    resultat = resultat or {}
    population = projet.population()
    brutes, _, replis, sans_objet = projet.grilles_completes(population)
    couleurs_nom = couleurs_aesh(resultat) if resultat.get("affectations") else {}
    couleurs = _couleurs_par_id(resultat, "aesh", "aesh_nom", couleurs_nom)
    verrous = projet.etat.get("cours_imposes") or {}
    bilans = {b["id"]: b for b in resultat.get("eleves") or []}
    en_repli = {r["eleve"] for r in replis}

    accompagnement = {}
    for a in resultat.get("affectations") or []:
        accompagnement.setdefault(a["eleve"], {})[(a["parite"], a["jour"], a["creneau"])] = a

    entetes = _entetes(projet)
    sortie = []
    for eleve in population["eleves"]:
        creneaux = brutes.get(eleve["id"])
        if creneaux is None:
            continue
        pris = accompagnement.get(eleve["id"], {})

        # Grille au format attendu par la fusion de blocs. La signature de fusion repose sur
        # « eleve » et « id_cours » : on y met l'accompagnant et un identifiant de cours distinct
        # selon qu'il est couvert ou non, pour qu'un cours accompagné ne fusionne jamais avec son
        # voisin qui ne l'est pas.
        grille, infos = {}, {}
        for cle, cours in creneaux.items():
            parite, jour, creneau = cle
            motif = projet.motif_non_accompagne(eleve["id"], cours)
            a = pris.get(cle)
            marque = "" if a else ("~hors" if motif else "~libre")
            grille.setdefault(cle, []).append({
                "eleve": a["aesh"] if a else marque,
                "eleve_nom": a["aesh_nom"] if a else "",
                "matiere": cours["matiere"], "salle": cours.get("salle", ""),
                "id_cours": cours["id_cours"] + marque})
            infos[cle] = (cours, a, motif)

        blocs = []
        for jour in range(len(JOURS_SEMAINE)):
            for premier, hauteur, largeur, colonne, _, _ in blocs_jour(
                    grille, jour, entetes["nb_creneaux"]):
                parites = ["A", "B"] if largeur == 2 else ["A" if colonne == 0 else "B"]
                cours, a, motif = infos[(parites[0], jour, premier)]
                cle_cours = cours["id_cours"]
                cles = [f"{eleve['id']}|{parite}|{cle_cours}" for parite in parites]
                verrou = next((verrous[c] for c in cles if c in verrous), None)
                blocs.append({
                    "jour": jour, "colonne": colonne, "largeur": largeur,
                    "debut": premier, "hauteur": hauteur,
                    "matiere": cours["matiere"], "salle": cours.get("salle", ""),
                    "id_cours": cle_cours, "parites": parites, "cles": cles,
                    "cles_retouche": [f"{parite}|{cle_cours}" for parite in parites],
                    "aesh": a["aesh"] if a else "", "aesh_nom": a["aesh_nom"] if a else "",
                    "couleur": couleurs.get(a["aesh"], GRIS_LIBRE) if a
                               else (GRIS_HORS if motif else GRIS_LIBRE),
                    "famille": projet.referentiel.famille(cours["matiere"]),
                    "accompagne": bool(a), "motif": motif or "",
                    "verrou": verrou,
                    "retouche": bool(cours.get("retouche")), "ajoute": bool(cours.get("ajoute")),
                })

        bilan = bilans.get(eleve["id"]) or {}
        sortie.append({
            "id": eleve["id"], "nom": eleve["nom_complet"],
            "classe": eleve.get("classe") or eleve.get("niveau") or "",
            "type_aide": eleve.get("type_aide", ""),
            "heures_notifiees": bilan.get("heures_notifiees", eleve.get("heures")),
            "heures_couvertes": bilan.get("heures_couvertes"),
            "taux": bilan.get("taux"),
            "repli": eleve["id"] in en_repli,
            "retouches": projet.retouches_de(eleve["id"]),
            "retouches_sans_objet": sans_objet.get(eleve["id"], []),
            "blocs": blocs,
        })
    sortie.sort(key=lambda e: e["nom"])
    return {**entetes, "eleves": sortie,
            "legende": [{"id": id_aesh, "couleur": couleur} for id_aesh, couleur in couleurs.items()],
            "couleurs": couleurs}


def tableau_aesh(projet, resultat=None):
    """
    Emploi du temps de chaque AESH, coloré selon l'élève accompagné.

    Vue en lecture seule, et volontairement : on n'affecte pas un élève depuis la grille de son
    accompagnant sans voir le reste de la journée de l'élève. Les modifications se font du côté
    élève, où l'on a sous les yeux ce qu'on déplace.
    """
    resultat = resultat or {}
    population = projet.population()
    couleurs_nom = couleurs_eleves(resultat) if resultat.get("affectations") else {}
    couleurs = _couleurs_par_id(resultat, "eleve", "eleve_nom", couleurs_nom)
    desactives = set(projet.etat.get("aesh_desactives", []))
    bilans = {b["id"]: b for b in resultat.get("aesh") or []}

    par_aesh = {}
    for a in resultat.get("affectations") or []:
        par_aesh.setdefault(a["aesh"], {}).setdefault(
            (a["parite"], a["jour"], a["creneau"]), []).append(a)

    entetes = _entetes(projet)
    sortie = []
    for personne in population["aesh"]:
        if personne["id"] in desactives:
            continue
        grille = par_aesh.get(personne["id"], {})
        blocs = []
        for jour in range(len(JOURS_SEMAINE)):
            for premier, hauteur, largeur, colonne, _, _ in blocs_jour(
                    grille, jour, entetes["nb_creneaux"]):
                parite = "A" if colonne == 0 else "B"
                membres = grille[(parite, jour, premier)]
                blocs.append({
                    "jour": jour, "colonne": colonne, "largeur": largeur,
                    "debut": premier, "hauteur": hauteur,
                    "eleves": [{"id": m["eleve"], "nom": m["eleve_nom"],
                                "matiere": m["matiere"], "salle": m.get("salle", ""),
                                "couleur": couleurs.get(m["eleve"], GRIS_LIBRE)}
                               for m in sorted(membres, key=lambda m: m["eleve_nom"])],
                })
        bilan = bilans.get(personne["id"]) or {}
        # Mêmes grandeurs que l'écran des résultats — toutes ramenées à la semaine, comme partout
        # ailleurs dans l'application : une demi-heure occupée sur les deux semaines types vaut une
        # demi-heure par semaine, pas deux.
        disponibilites = projet.disponibilites(personne["id"])
        sortie.append({
            "id": personne["id"], "nom": personne["nom_complet"],
            "quotite": bilan.get("quotite", personne.get("quotite")),
            "heures_affectees": bilan.get("heures_affectees", 0),
            "heures_disponibles": bilan.get("heures_disponibles",
                                            round(len(disponibilites) / 2, 2)),
            "eleves": bilan.get("eleves", []),
            "dispo": sorted(f"{jour}-{creneau}" for jour, creneau in disponibilites),
            "blocs": blocs,
        })
    sortie.sort(key=lambda a: a["nom"])
    return {**entetes, "aesh": sortie, "couleurs": couleurs}
