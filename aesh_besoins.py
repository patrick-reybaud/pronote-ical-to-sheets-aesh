#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aesh_besoins.py — classeur de saisie des difficultés des élèves par famille de matières (étape 2).

Un seul onglet : une ligne par élève notifié, une colonne par famille de matières, une note de 1 à 5
(vide = neutre, 5 = accompagnement indispensable). C'est le pendant des affinités saisies par les AESH :
le calcul d'affectation croise « difficulté de l'élève » et « aisance de l'AESH » sur la même famille.

⚠️ Classeur SÉPARÉ de celui des AESH, et volontairement : il porte des informations liées au handicap
et ne doit être partagé qu'avec la coordination, jamais avec l'ensemble des accompagnants.

Les colonnes d'identité et la colonne « Besoins (fichier de notifications) » sont verrouillées : elles
servent de repère pour remplir, et de trace de ce qu'on a compris du texte libre d'origine.

Module appelé par `python aesh.py besoins` — pas d'exécution directe.
"""

import re

from noyau import NB_LIGNES_ENTETE, SEP_FORMULE, compacter

NOTE_MIN, NOTE_MAX = 1, 5
NOTE_PREREMPLIE = 4          # note proposée quand le texte libre cite explicitement une matière
LARGEUR_COL_FAMILLE = 46
HAUTEUR_LIGNE = 21

# Colonnes d'identité, en lecture seule (en-tête, largeur)
COLONNES_ELEVE = [("Élève", 200), ("Classe", 80), ("Aide", 50), ("Heures", 60),
                  ("Besoins (fichier de notifications)", 300)]

# Rapprochement du texte libre de la colonne « Besoins » avec les familles de matières.
# Volontairement prudent : on ne pré-remplit que ce qui est cité sans ambiguïté, le reste
# reste vide et c'est à la coordination de compléter.
MOTS_BESOINS = [
    (r"\bFR\b|FRANCAIS|LECTURE|ECRITURE", "Français / Lettres"),
    (r"\bHG\b|HIST|GEO", "Histoire-Géo / EMC"),
    (r"\bMATH", "Mathématiques"),
    (r"SCIENCE", "Sciences"),
    (r"GESTION|ECONOMIE|\bECO\b", "Économie-gestion / droit"),
    (r"\bLV\b|ANGLAIS", "Anglais"),
    (r"ESPAGNOL|ITALIEN|ALLEMAND", "Langues vivantes (hors anglais)"),
    (r"CUISINE|PATISSERIE", "TP Cuisine / Pâtisserie"),
    (r"RESTAURANT|SERVICE|\bREST\b", "TP Restaurant / Service"),
    (r"\bEPS\b|SPORT", "EPS"),
    (r"TOURISME", "Tourisme"),
]


def familles_citees(texte, familles):
    """Familles explicitement citées dans le texte libre des besoins."""
    compact = compacter(texte)
    trouvees = []
    for motif, famille in MOTS_BESOINS:
        if famille in familles and famille not in trouvees and re.search(motif, compact):
            trouvees.append(famille)
    return trouvees


def construire_onglet_difficultes(eleves, familles, annee):
    """Modèle de l'onglet « Difficultés » : élèves en lignes, familles de matières en colonnes."""
    nb_id = len(COLONNES_ELEVE)
    nb_cols = nb_id + len(familles)
    lignes, fusions, styles, valeurs = [], [], {}, {}

    def ajouter(textes=None):
        r = len(lignes)
        lignes.append(list(textes) + [""] * (nb_cols - len(textes)) if textes else [""] * nb_cols)
        return r

    r = ajouter([f"Difficultés des élèves par matière — {annee}"])
    fusions.append((r, r + 1, 0, nb_cols))
    styles[(r, 0)] = "titre"
    r = ajouter([f"Notez de {NOTE_MIN} à {NOTE_MAX} le besoin d'accompagnement dans chaque famille de matières "
                 f"({NOTE_MAX} = accompagnement indispensable). Laissez vide si le besoin est ordinaire : "
                 "une case vide est neutre, elle ne dit pas « pas de besoin ». Les cases jaunes pré-remplies "
                 "viennent d'une lecture automatique de la colonne « Besoins » et sont à vérifier."])
    fusions.append((r, r + 1, 0, nb_cols))
    styles[(r, 0)] = "sous_titre"

    r_entete = ajouter([c[0] for c in COLONNES_ELEVE] + list(familles))
    for c in range(nb_id):
        styles[(r_entete, c)] = "entete"
    for c in range(nb_id, nb_cols):
        styles[(r_entete, c)] = "entete_incline"

    premiere = len(lignes)
    preremplies = 0
    for e in eleves:
        r = ajouter([e["nom_complet"], e.get("classe", ""), e.get("type_aide", ""), e.get("heures", ""),
                     e.get("besoins", "")])
        for c in range(nb_id):
            styles[(r, c)] = "libelle"
        citees = familles_citees(e.get("besoins", ""), familles)
        for i, famille in enumerate(familles):
            c = nb_id + i
            styles[(r, c)] = "saisie"
            if famille in citees:
                valeurs[(r, c)] = {"numberValue": NOTE_PREREMPLIE}
                lignes[r][c] = str(NOTE_PREREMPLIE)
                preremplies += 1
    derniere = len(lignes) - 1

    r_total = ajouter(["Nombre d'élèves notés dans cette matière"])
    fusions.append((r_total, r_total + 1, 0, nb_id))
    styles[(r_total, 0)] = "total_libelle"
    for i in range(len(familles)):
        c = nb_id + i
        lettre = chr(65 + c) if c < 26 else chr(64 + c // 26) + chr(65 + c % 26)
        lignes[r_total][c] = "—"
        valeurs[(r_total, c)] = {"formulaValue":
                                 f"=COUNT({lettre}{premiere + 1}:{lettre}{derniere + 1})"}
        styles[(r_total, c)] = "total"

    notes = {"startRowIndex": premiere, "endRowIndex": derniere + 1,
             "startColumnIndex": nb_id, "endColumnIndex": nb_cols}
    return {
        "titre": "Difficultés",
        "lignes": lignes, "fusions": fusions, "styles": styles, "valeurs": valeurs, "nb_cols": nb_cols,
        "largeurs": [(i, i + 1, c[1]) for i, c in enumerate(COLONNES_ELEVE)]
                    + [(nb_id, nb_cols, LARGEUR_COL_FAMILLE)],
        "figees": r_entete + 1,
        "bordures": r_entete,
        "hauteur_ligne": HAUTEUR_LIGNE,
        "validations": [{"plage": notes, "regle": {
            "condition": {"type": "ONE_OF_LIST",
                          "values": [{"userEnteredValue": str(n)} for n in range(NOTE_MIN, NOTE_MAX + 1)]},
            "showCustomUi": True, "strict": True,
            "inputMessage": f"Vide = neutre, sinon {NOTE_MIN} à {NOTE_MAX}"}}],
        "protections": [{"description": "Difficultés élèves — identité verrouillée", "ouvertes": [notes]}],
        "reperes": {"notes": notes, "familles": list(familles),
                    "eleves": [e["nom_complet"] for e in eleves],
                    "premiere_colonne_famille": nb_id},
        "preremplies": preremplies,
    }
