#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
matieres.py — regroupement des libellés ProNote en familles de matières.

Les exports portent des dizaines de libellés hétérogènes (« MATHS,PHYSIQ.-CHIMIE », « TP CUI SEP »,
« AE REST LYCEE »…). Pour que « effort demandé à l'élève » et « aisance de l'AESH » se rencontrent,
il faut un vocabulaire commun : c'est le rôle des familles ci-dessous.

Le classement est fait par règles, dans l'ordre, première correspondance retenue. Ce qu'aucune règle
ne reconnaît est rangé dans NON_CLASSE et **signalé** à l'utilisateur, qui peut corriger le
rattachement depuis l'application — les corrections sont enregistrées avec le projet.
"""

import re
import unicodedata


def compacter(texte):
    texte = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode()
    texte = texte.upper().replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", texte)).strip()


NON_CLASSE = "Autre / à classer"

# Effort supposé quand rien n'est saisi, par famille. Ces matières demandent rarement un
# accompagnement soutenu ; les y placer par défaut évite d'y consommer des heures comptées.
# C'est une valeur de départ affichée et modifiable élève par élève, pas une règle.
EFFORTS_PAR_DEFAUT = {
    "Arts appliqués": 1,
    "EPS": 1,
    "Chef-d'œuvre / projet": 1,
}

FAMILLES = [
    "Français / Lettres",
    "Mathématiques",
    "Sciences",
    "Histoire-Géo / EMC",
    "Anglais",
    "Langues vivantes (hors anglais)",
    "Économie-gestion / droit",
    "Tourisme",
    "Techno & théorie professionnelle",
    "TP Cuisine / Pâtisserie",
    "TP Restaurant / Service",
    "TP Bar / Sommellerie",
    "Hébergement",
    "EPS",
    "Arts appliqués",
    "Accompagnement / orientation",
    "Chef-d'œuvre / projet",
]

REGLES_FAMILLE = [
    (r"CO INTERVENTION.*\bMATHS?\b", "Mathématiques"),
    (r"CO INTERVENTION", "Français / Lettres"),          # les autres co-interventions sont côté français
    (r"^ACCOMPAGNEMT PERSO|^CONS AC PER|^AT PROFESSIONNALIS"
     r"|^PREPA INSERTION|^ACTIVITES PROFESSION|^PARC PROFES", "Accompagnement / orientation"),
    (r"CHEF D OEUVRE|REALISATION PROJET|^PROJET", "Chef-d'œuvre / projet"),
    (r"^TP BAR|GESTION CAVE|MC BAR|CRU DES VINS|OENOLOGIE", "TP Bar / Sommellerie"),
    (r"^TP CUI|^AE CUI|^TP PAT|^TP BOUL", "TP Cuisine / Pâtisserie"),
    (r"^TP REST|^AE REST|ELEVES CLIENTS", "TP Restaurant / Service"),
    (r"^AE HEBERG", "Hébergement"),
    (r"ANGLAIS|ENS TECHNO EN LV1", "Anglais"),
    (r"ESPAGNOL|ITALIEN|ALLEMAND", "Langues vivantes (hors anglais)"),
    (r"^FRANCAIS HIST|^FRANCAIS|CULTURE GENE|PHILOSOPHIE", "Français / Lettres"),
    (r"MATHEMATIQUES|^MATHS", "Mathématiques"),
    (r"HIST GEO|HISTOIRE GEO|ENS MORAL", "Histoire-Géo / EMC"),
    (r"^SCIENCES$|ENS SCIENT|^SC AP ALI|PREVENT SANTE|ANALYSE SENSORIELLE", "Sciences"),
    (r"^INFO MCS|ECONO GEST|ECONOMIE GESTION|ENVIRONMT ECO", "Économie-gestion / droit"),
    (r"TOURIS", "Tourisme"),
    (r"ED PHYSIQUE|^EPS\b", "EPS"),
    (r"ARTS APPL", "Arts appliqués"),
    (r"TECHNO DE SPECIALITE|SC TECHN CULIN|CONNAISSANCE PRODUITS"
     r"|INGENIERIE|MEHMS|EPEH|^TRAVAUX PRATIQUES", "Techno & théorie professionnelle"),
]


def deviner_famille(libelle):
    """Famille d'un libellé ProNote, ou NON_CLASSE si aucune règle ne s'applique."""
    compact = compacter(libelle)
    for motif, famille in REGLES_FAMILLE:
        if re.search(motif, compact):
            return famille
    return NON_CLASSE


class Referentiel:
    """Classement des matières, avec les corrections manuelles enregistrées dans le projet."""

    def __init__(self, corrections=None):
        self.corrections = dict(corrections or {})

    def famille(self, libelle):
        return self.corrections.get(libelle) or deviner_famille(libelle)

    def inventaire(self, libelles):
        """[{libelle, famille, corrigee}] trié par famille puis libellé — c'est ce qu'affiche l'écran."""
        lignes = [{"libelle": l, "famille": self.famille(l), "corrigee": l in self.corrections}
                  for l in sorted(set(libelles))]
        rang = {f: i for i, f in enumerate(FAMILLES)}
        return sorted(lignes, key=lambda x: (rang.get(x["famille"], len(FAMILLES)), x["libelle"]))

    def non_classees(self, libelles):
        return [l for l in sorted(set(libelles)) if self.famille(l) == NON_CLASSE]
