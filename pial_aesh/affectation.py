#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
affectation.py — calcul des affectations AESH ↔ élèves, par programmation par contraintes (CP-SAT).

Tout est compté **en demi-heures sur un cycle de deux semaines** (une semaine A + une semaine B) :
c'est la seule unité dans laquelle un cours hebdomadaire et un cours de quinzaine se comparent sans
approximation. Les affichages divisent par 2 pour revenir à des heures par semaine.

Le modèle distingue deux familles de règles, et l'interface les montre toutes :

  · **dures** — jamais violées : disponibilité, présence de l'élève, non-ubiquité, quotités,
    interdictions et obligations saisies par l'utilisateur ;
  · **souples** — pondérées, c'est là que se joue la qualité : couverture, affinité, équité du
    manque, continuité (peu d'AESH différents par élève), compacité, stabilité entre deux calculs.

Les poids sont tous exposés à l'utilisateur ; aucun n'est figé dans le code.
"""

from collections import defaultdict
from itertools import combinations

from .matieres import EFFORTS_PAR_DEFAUT

NOTE_NEUTRE = 3          # une case laissée vide vaut « neutre », ni bonus ni malus
DUREE_CRENEAU_MIN = 30

# Poids par défaut des objectifs souples. Modifiables depuis l'écran « Pondérations ».
# Ces valeurs sont un point de départ mesuré sur des données réelles, pas des constantes physiques :
# elles sont toutes réglables depuis l'écran « Pondérations ». L'ordre de grandeur compte plus que
# la valeur absolue — un créneau couvert vaut « couverture x effort », soit 300 pour un effort neutre,
# ce qui donne l'échelle à laquelle les pénalités doivent se comparer pour peser.
POIDS_DEFAUT = {
    "couverture": 100,      # couvrir des demi-heures, pondérées par l'effort demandé à l'élève
    "affinite": 30,         # aisance déclarée de l'AESH dans la matière du créneau
    "equite": 400,          # remonter le taux de couverture de l'élève le moins bien servi
    "continuite": 1500,     # pénalité par binôme AESH-élève supplémentaire : sans un poids de cet
                            # ordre, le calcul éparpille un même élève sur cinq accompagnants
    # Mesuré sur un établissement réel : 0 → 202 demi-heures de trou, 200 → 85, 600 → 79,
    # 1500 → 58, sans perdre un point de couverture. 600 prend l'essentiel du gain en restant
    # sous la continuité, qui doit garder la priorité.
    "compacite": 600,       # pénalité par bloc séparé dans la demi-journée d'un AESH
    "stabilite": 15,        # pénalité par écart avec l'affectation précédente (recalcul)
}

REGLES_DURES = [
    ("H1", "Un AESH n'est affecté que sur un créneau qu'il a déclaré disponible"),
    ("H2", "Un élève n'est accompagné que lorsqu'il a effectivement cours"),
    ("H3", "Un AESH ne peut pas être à deux endroits au même moment"),
    ("H4", "Mutualisation : plusieurs élèves sur un même créneau seulement s'ils sont dans le même cours"),
    ("H5", "Accompagnement exclusif : l'AESH est seul avec l'élève (aide individuelle, ou réglage « jamais mutualisé »)"),
    ("H5b", "Deux élèves déclarés incompatibles ne sont jamais accompagnés ensemble"),
    ("H6", "Le service d'un AESH ne dépasse pas sa quotité"),
    ("H7", "L'accompagnement d'un élève ne dépasse pas ses heures notifiées"),
    ("H8", "Les interdictions saisies (élève ✕ AESH) sont respectées"),
    ("H9", "Les affectations forcées saisies sont respectées"),
    ("H10", "Un élève n'est pas accompagné par plus d'AESH différents que le plafond fixé"),
    ("H11", "Chaque AESH garde une pause continue d'au moins une heure entre 11 h et 14 h"),
    ("H12", "Les cours confiés à la main depuis l'écran des résultats sont respectés"),
]

REGLES_SOUPLES = [
    ("S1", "couverture", "Couvrir le plus d'heures possible, en priorité là où l'effort demandé à l'élève est fort"),
    ("S2", "affinite", "Placer chaque AESH sur les matières où il se déclare le plus à l'aise"),
    ("S3", "equite", "Répartir le manque : remonter le taux de couverture de l'élève le moins bien servi"),
    ("S4", "continuite", "Limiter le nombre d'AESH différents auprès d'un même élève"),
    ("S5", "compacite", "Limiter les trous dans la journée d'un AESH : moins de blocs séparés"),
    ("S6", "stabilite", "Lors d'un recalcul, s'écarter le moins possible de l'affectation précédente"),
]


class Probleme:
    """
    Données d'entrée du calcul, déjà mises en forme.

      eleves   : [{id, nom_complet, type_aide, heures, creneaux}]  creneaux = {(parite, jour, s): cours}
      aesh     : [{id, nom_complet, quotite, dispo}]               dispo   = {(jour, s)}
      efforts  : {id_eleve: {famille: 1..5}}
      affinites: {id_aesh:  {famille: 1..5}}
      paires   : {(id_aesh, id_eleve): -2..2}   -2 interdit · -1 éviter · 0 neutre · 1 favoriser · 2 imposer
      famille  : fonction matiere → famille
    """

    def __init__(self, eleves, aesh, efforts, affinites, paires, famille_de,
                 poids=None, max_mutualise=2, precedent=None,
                 mutualisation=None, paires_eleves=None, max_aesh_par_eleve=0,
                 pause=None, cours_imposes=None, h_min=7):
        self.eleves = eleves
        self.aesh = aesh
        self.efforts = efforts or {}
        self.affinites = affinites or {}
        self.paires = paires or {}
        self.famille_de = famille_de
        self.poids = {**POIDS_DEFAUT, **(poids or {})}
        self.max_mutualise = max(1, int(max_mutualise))
        self.precedent = precedent or {}
        self.mutualisation = mutualisation or {}
        self.paires_eleves = paires_eleves or {}
        # 0 = pas de plafond. Un poids de continuité ne garantit rien ; un plafond, si.
        self.max_aesh_par_eleve = max(0, int(max_aesh_par_eleve or 0))
        # Pause méridienne : {"debut": 11, "fin": 14, "minutes": 60}. minutes = 0 → pas d'exigence.
        self.pause = {"debut": 11, "fin": 14, "minutes": 60, **(pause or {})}
        # Affectations imposées au cours près : {"<élève>|<parité>|<id_cours>": "<id AESH>"}
        self.cours_imposes = cours_imposes or {}
        self.h_min = h_min

    def exclusif(self, eleve):
        """
        Cet élève doit-il avoir l'AESH pour lui seul sur le créneau ?

        Par défaut l'aide individuelle est exclusive et l'aide mutualisée ne l'est pas, mais la
        coordination peut trancher élève par élève : certains élèves en aide mutualisée ne supportent
        pas le partage, et certains élèves en aide individuelle peuvent parfaitement être accompagnés
        avec un camarade lorsqu'ils sont dans le même cours.
        """
        mode = self.mutualisation.get(eleve["id"], "auto")
        if mode == "jamais":
            return True
        if mode == "possible":
            return False
        return eleve["type_aide"] == "I"

    def accord_eleves(self, id_a, id_b):
        """-1 si ces deux élèves ne doivent jamais être mutualisés, 1 s'il faut les regrouper."""
        return self.paires_eleves.get(f"{id_a}|{id_b}") or self.paires_eleves.get(f"{id_b}|{id_a}") or 0

    def note_effort(self, id_eleve, famille):
        saisie = self.efforts.get(id_eleve, {}).get(famille)
        return saisie if saisie else EFFORTS_PAR_DEFAUT.get(famille, NOTE_NEUTRE)

    def note_affinite(self, id_aesh, famille):
        return self.affinites.get(id_aesh, {}).get(famille, NOTE_NEUTRE)

    def ponderation(self, id_aesh, id_eleve):
        return self.paires.get(f"{id_aesh}|{id_eleve}", 0)


def resoudre(probleme, secondes=20, journal=None):
    """
    Retourne un dictionnaire de résultat : affectations, couverture par élève, service par AESH,
    créneaux non couverts avec leur cause, et l'état du solveur.

    **L'unité d'affectation est le cours entier, pas la demi-heure.** Un cours commencé est mené à
    son terme par la même personne : on n'accompagne pas un élève pendant deux heures d'un TP qui en
    dure cinq pour le laisser seul ensuite. Concrètement, une variable par (AESH, cours) au lieu
    d'une par (AESH, élève, demi-heure) — ce qui rend le modèle plus petit et le résultat tenable.
    """
    from ortools.sat.python import cp_model

    dire = journal or (lambda *_: None)
    modele = cp_model.CpModel()
    par_id_eleve = {e["id"]: e for e in probleme.eleves}
    par_id_aesh = {a["id"]: a for a in probleme.aesh}

    # ── Découpage en cours insécables : une clé par (élève, parité, cours ProNote)
    blocs, creneaux_eleve = {}, defaultdict(list)
    for eleve in probleme.eleves:
        for cle, cours in eleve["creneaux"].items():
            parite, jour, creneau = cle
            creneaux_eleve[eleve["id"]].append(cle)
            blocs.setdefault((eleve["id"], parite, cours["id_cours"]),
                             {"eleve": eleve["id"], "parite": parite, "cours": cours,
                              "cles": []})["cles"].append(cle)

    # ── Variables : une par (AESH, cours), créée seulement si l'AESH est libre sur TOUT le cours
    x, sans_aesh_dispo = {}, []
    for cle_bloc, bloc in blocs.items():
        creneaux = [(jour, creneau) for _, jour, creneau in bloc["cles"]]
        possible = False
        for aesh in probleme.aesh:
            if probleme.ponderation(aesh["id"], bloc["eleve"]) <= -2:        # H8 : interdiction
                continue
            if not all(c in aesh["dispo"] for c in creneaux):                # H1 sur le cours entier
                continue
            x[(aesh["id"], cle_bloc)] = modele.NewBoolVar(f"x_{aesh['id']}_{cle_bloc[0]}_{cle_bloc[1]}{cle_bloc[2]}")
            possible = True
        if not possible:
            sans_aesh_dispo.append(bloc)
    dire(f"{len(blocs)} cours à couvrir, {len(x)} affectations possibles")
    if not x:
        return {"statut": "AUCUNE_VARIABLE", "message":
                "Aucune affectation possible : aucun AESH n'est disponible sur la durée complète d'un "
                "cours. Élargissez les disponibilités ou desserrez les interdictions.",
                "affectations": [], "eleves": [], "aesh": [], "non_couverts": [], "synthese": {}}

    # ── Un cours n'est confié qu'à une seule personne (et donc jamais morcelé)
    par_bloc = defaultdict(list)
    for (id_a, cle_bloc), variable in x.items():
        par_bloc[cle_bloc].append(variable)
    for variables in par_bloc.values():
        if len(variables) > 1:
            modele.Add(sum(variables) <= 1)

    # ── Ce que chaque AESH fait à chaque demi-heure
    presence = defaultdict(list)       # (id_aesh, cle créneau) → [(id_eleve, id_cours, variable)]
    for (id_a, cle_bloc), variable in x.items():
        bloc = blocs[cle_bloc]
        for cle in bloc["cles"]:
            presence[(id_a, cle)].append((bloc["eleve"], bloc["cours"]["id_cours"], variable))

    occupe, regroupements = {}, []
    for (id_a, cle), membres in presence.items():
        variables = [m[2] for m in membres]
        indicateur = modele.NewBoolVar(f"occ_{id_a}_{cle[0]}{cle[1]}_{cle[2]}")
        occupe[(id_a, cle)] = indicateur
        modele.AddMaxEquality(indicateur, variables)
        if len(variables) == 1:
            continue
        # H4 : au plus N élèves en même temps, et seulement s'ils sont dans le même cours
        modele.Add(sum(variables) <= probleme.max_mutualise)
        groupes = defaultdict(list)
        for id_eleve, id_cours, variable in membres:
            groupes[id_cours].append(variable)
        if len(groupes) > 1:
            temoins = []
            for id_cours, variables_cours in groupes.items():
                temoin = modele.NewBoolVar(f"grp_{id_a}_{cle[0]}{cle[1]}_{cle[2]}_{id_cours}")
                modele.AddMaxEquality(temoin, variables_cours)
                temoins.append(temoin)
            modele.Add(sum(temoins) <= 1)
        # H5 : accompagnement exclusif, et H5b : élèves incompatibles
        par_eleve = defaultdict(list)
        for id_eleve, _, variable in membres:
            par_eleve[id_eleve].append(variable)
        for id_eleve, variables_eleve in par_eleve.items():
            if probleme.exclusif(par_id_eleve[id_eleve]):
                autres = [v for autre, vs in par_eleve.items() if autre != id_eleve for v in vs]
                if autres:
                    for variable in variables_eleve:
                        modele.Add(sum(autres) == 0).OnlyEnforceIf(variable)
        for id_1, id_2 in combinations(sorted(par_eleve), 2):
            accord = probleme.accord_eleves(id_1, id_2)
            if accord < 0:
                modele.Add(sum(par_eleve[id_1]) + sum(par_eleve[id_2]) <= 1)
            elif accord > 0:
                duo = modele.NewBoolVar(f"duo_{id_a}_{id_1}_{id_2}_{cle[0]}{cle[1]}_{cle[2]}")
                modele.AddMultiplicationEquality(duo, [sum(par_eleve[id_1]), sum(par_eleve[id_2])])
                regroupements.append(duo)

    # ── S5 : compacité. Un AESH dont la journée est hachée de trous attend sur place sans être
    # payé à attendre : on compte le nombre de **blocs séparés** dans chaque demi-journée et on le
    # pénalise. Moins de blocs, c'est mécaniquement moins de trous et des journées tenables.
    debuts_de_bloc = []
    for aesh in probleme.aesh:
        par_journee = defaultdict(set)
        for (id_a, cle) in occupe:
            if id_a == aesh["id"]:
                par_journee[(cle[0], cle[1])].add(cle[2])
        for (parite, jour), indices in par_journee.items():
            for indice in sorted(indices):
                courant = occupe[(aesh["id"], (parite, jour, indice))]
                precedent = occupe.get((aesh["id"], (parite, jour, indice - 1)))
                debut = modele.NewBoolVar(f"bloc_{aesh['id']}_{parite}{jour}_{indice}")
                if precedent is None:
                    modele.Add(debut == courant)
                else:
                    # debut ⟺ (occupé maintenant) ET (libre juste avant)
                    modele.AddBoolOr([debut.Not(), courant])
                    modele.AddBoolOr([debut.Not(), precedent.Not()])
                    modele.AddBoolOr([debut, courant.Not(), precedent])
                debuts_de_bloc.append(debut)

    # ── H11 : pause méridienne. Chaque AESH doit disposer, chaque jour travaillé, d'une plage
    # libre continue d'au moins une heure entre 11 h et 14 h. Un AESH qui ne travaille pas ce
    # jour-là satisfait la règle sans rien faire : toutes ses demi-heures sont libres.
    duree = probleme.pause.get("minutes") or 0
    if duree:
        largeur = duree // DUREE_CRENEAU_MIN
        premier = (probleme.pause["debut"] - probleme.h_min) * 60 // DUREE_CRENEAU_MIN
        dernier = (probleme.pause["fin"] - probleme.h_min) * 60 // DUREE_CRENEAU_MIN
        for aesh in probleme.aesh:
            journees = {(cle[0], cle[1]) for (id_a, cle) in occupe if id_a == aesh["id"]}
            for parite, jour in journees:
                creneaux_possibles = []
                for depart in range(premier, dernier - largeur + 1):
                    occupes = [occupe[(aesh["id"], (parite, jour, depart + k))]
                               for k in range(largeur)
                               if (aesh["id"], (parite, jour, depart + k)) in occupe]
                    if not occupes:
                        creneaux_possibles = None      # créneau déjà libre en toutes circonstances
                        break
                    libre = modele.NewBoolVar(f"pause_{aesh['id']}_{parite}{jour}_{depart}")
                    modele.AddBoolAnd([o.Not() for o in occupes]).OnlyEnforceIf(libre)
                    modele.AddBoolOr(occupes).OnlyEnforceIf(libre.Not())
                    creneaux_possibles.append(libre)
                if creneaux_possibles:
                    modele.AddBoolOr(creneaux_possibles)

    # ── H6 : quotité de service (demi-heures occupées sur deux semaines, mutualisation comprise)
    for aesh in probleme.aesh:
        creneaux_occupes = [v for (id_a, _), v in occupe.items() if id_a == aesh["id"]]
        plafond = int(round(aesh["quotite"] * 2 * 2))
        if creneaux_occupes and plafond >= 0:
            modele.Add(sum(creneaux_occupes) <= plafond)

    # ── H7 : heures notifiées de chaque élève, et couverture
    couverture, besoin, hors_equite = {}, {}, []
    for eleve in probleme.eleves:
        parts = [(len(blocs[cle_bloc]["cles"]), variable)
                 for (id_a, cle_bloc), variable in x.items() if cle_bloc[0] == eleve["id"]]
        plafond_notification = int(round(eleve["heures"] * 2 * 2))
        plafond_presence = len(creneaux_eleve[eleve["id"]])
        eligible = plafond_notification > 0 and plafond_presence > 0 and bool(parts)
        besoin[eleve["id"]] = max(1, min(plafond_notification, plafond_presence)) if eligible else 0
        if not parts:
            if plafond_notification > 0:
                hors_equite.append((eleve["id"], "aucun cours couvrable par un AESH disponible de bout en bout"))
            continue
        total_demi_heures = sum(taille * variable for taille, variable in parts)
        modele.Add(total_demi_heures <= plafond_notification)
        if eligible:
            total = modele.NewIntVar(0, besoin[eleve["id"]], f"couv_{eleve['id']}")
            modele.Add(total == total_demi_heures)
            couverture[eleve["id"]] = total
        else:
            hors_equite.append((eleve["id"], "aucune heure notifiée chiffrée"))

    # ── H9b : cours confiés à la main depuis l'écran des résultats. Ce n'est pas une suggestion :
    # le calcul doit s'y plier et réarranger le reste, ou déclarer que c'est impossible.
    for cle_cours, id_aesh in probleme.cours_imposes.items():
        try:
            id_eleve, parite, id_cours = cle_cours.split("|", 2)
        except ValueError:
            continue
        variable = x.get((id_aesh, (id_eleve, parite, id_cours)))
        if variable is not None:
            modele.Add(variable == 1)

    # ── H9 : affectations imposées
    for cle_paire, valeur in probleme.paires.items():
        if valeur < 2:
            continue
        id_a, id_e = cle_paire.split("|", 1)
        variables = [v for (a, cle_bloc), v in x.items() if a == id_a and cle_bloc[0] == id_e]
        if variables:
            modele.AddBoolOr(variables)

    # ── S4 : un indicateur par binôme (AESH, élève)
    ensemble = {}
    for aesh in probleme.aesh:
        for eleve in probleme.eleves:
            variables = [v for (a, cle_bloc), v in x.items()
                         if a == aesh["id"] and cle_bloc[0] == eleve["id"]]
            if not variables:
                continue
            z = modele.NewBoolVar(f"z_{aesh['id']}_{eleve['id']}")
            modele.AddMaxEquality(z, variables)
            ensemble[(aesh["id"], eleve["id"])] = z

    # ── H10 : plafond d'accompagnants différents par élève. C'est une règle dure, parce que
    # « pas plus de trois personnes autour de cet enfant » est une exigence, pas une préférence.
    if probleme.max_aesh_par_eleve:
        for eleve in probleme.eleves:
            indicateurs = [z for (_, id_e), z in ensemble.items() if id_e == eleve["id"]]
            if len(indicateurs) > probleme.max_aesh_par_eleve:
                modele.Add(sum(indicateurs) <= probleme.max_aesh_par_eleve)

    # ── S3 : équité — remonter le taux de l'élève le moins bien servi
    taux_minimal = modele.NewIntVar(0, 1000, "taux_min")
    for id_e, total in couverture.items():
        modele.Add(taux_minimal * besoin[id_e] <= total * 1000)

    # ── Objectif
    termes, poids = [], probleme.poids
    for (id_a, cle_bloc), variable in x.items():
        bloc = blocs[cle_bloc]
        famille = probleme.famille_de(bloc["cours"]["matiere"])
        effort = probleme.note_effort(bloc["eleve"], famille)
        affinite = probleme.note_affinite(id_a, famille)
        preference = probleme.ponderation(id_a, bloc["eleve"])
        taille = len(bloc["cles"])
        valeur = taille * (poids["couverture"] * effort
                           + poids["affinite"] * (affinite - NOTE_NEUTRE)
                           + poids["couverture"] * preference // 2)
        if probleme.precedent.get(f"{id_a}|{bloc['eleve']}|{cle_bloc[1]}|{cle_bloc[2]}"):
            valeur += poids["stabilite"] * taille
        termes.append(int(valeur) * variable)
    for z in ensemble.values():
        termes.append(-poids["continuite"] * z)
    for duo in regroupements:
        termes.append(poids["couverture"] * NOTE_NEUTRE * duo)
    for debut in debuts_de_bloc:
        termes.append(-poids["compacite"] * debut)
    termes.append(poids["equite"] * taux_minimal)
    modele.Maximize(sum(termes))

    solveur = cp_model.CpSolver()
    solveur.parameters.max_time_in_seconds = float(secondes)
    solveur.parameters.num_search_workers = 8
    statut = solveur.Solve(modele)
    nom_statut = solveur.StatusName(statut)
    dire(f"solveur : {nom_statut} en {solveur.WallTime():.1f} s")
    if statut not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"statut": nom_statut, "message":
                "Aucune solution ne respecte toutes les règles dures. Desserrez une interdiction, une "
                "affectation imposée ou le plafond d'AESH par élève, puis relancez.",
                "affectations": [], "eleves": [], "aesh": [], "non_couverts": [], "synthese": {}}

    affectations = []
    for (id_a, cle_bloc), variable in x.items():
        if not solveur.Value(variable):
            continue
        bloc = blocs[cle_bloc]
        cours = bloc["cours"]
        for parite, jour, creneau in bloc["cles"]:
            affectations.append({
                "aesh": id_a, "aesh_nom": par_id_aesh[id_a]["nom_complet"],
                "eleve": bloc["eleve"], "eleve_nom": par_id_eleve[bloc["eleve"]]["nom_complet"],
                "parite": parite, "jour": jour, "creneau": creneau,
                "matiere": cours["matiere"], "famille": probleme.famille_de(cours["matiere"]),
                "salle": cours.get("salle", ""), "classe": cours.get("classe", ""),
                "id_cours": cours["id_cours"],
            })
    return _resultat(probleme, affectations, besoin, hors_equite, nom_statut,
                     sans_aesh_dispo, creneaux_eleve, par_id_eleve, par_id_aesh)


def _resultat(probleme, affectations, besoin, hors_equite, nom_statut,
              sans_aesh_dispo, creneaux_eleve, par_id_eleve, par_id_aesh):
    pris = defaultdict(set)
    for a in affectations:
        pris[a["eleve"]].add((a["parite"], a["jour"], a["creneau"]))

    bilan_eleves = []
    for eleve in probleme.eleves:
        couvert = sum(1 for _ in pris[eleve["id"]])
        besoin_e = besoin.get(eleve["id"], 0)
        hors = dict(hors_equite).get(eleve["id"])
        accompagnants = sorted({a["aesh_nom"] for a in affectations if a["eleve"] == eleve["id"]})
        bilan_eleves.append({
            "id": eleve["id"], "nom": eleve["nom_complet"], "type_aide": eleve["type_aide"],
            "heures_notifiees": eleve["heures"],
            "heures_couvertes": round(couvert / 4, 2),           # demi-heures sur 2 semaines → h/semaine
            "heures_presence": round(len(creneaux_eleve[eleve["id"]]) / 4, 2),
            "taux": round(100 * couvert / besoin_e) if besoin_e else None,
            "hors_calcul": hors,
            "aesh": accompagnants, "nb_aesh": len(accompagnants),
        })

    bilan_aesh = []
    for aesh in probleme.aesh:
        creneaux = [a for a in affectations if a["aesh"] == aesh["id"]]
        eleves_suivis = sorted({a["eleve_nom"] for a in creneaux})
        # Service réel : nombre de créneaux occupés — deux élèves mutualisés sur un même créneau
        # ne comptent qu'une fois, sinon la quotité paraîtrait dépassée.
        occupes = len({(a["parite"], a["jour"], a["creneau"]) for a in creneaux})
        bilan_aesh.append({
            "id": aesh["id"], "nom": aesh["nom_complet"], "quotite": aesh["quotite"],
            "heures_affectees": round(occupes / 4, 2),
            "heures_eleves": round(len(creneaux) / 4, 2),
            "heures_disponibles": round(len(aesh["dispo"]) * 2 / 4, 2),
            "eleves": eleves_suivis, "nb_eleves": len(eleves_suivis),
        })

    non_couverts = defaultdict(lambda: {"demi_heures": 0, "causes": defaultdict(int)})
    for eleve in probleme.eleves:
        for cle in creneaux_eleve[eleve["id"]]:
            if cle in pris[eleve["id"]]:
                continue
            entree = non_couverts[eleve["id"]]
            entree["demi_heures"] += 1
            jour, s = cle[1], cle[2]
            if not any((jour, s) in a["dispo"] for a in probleme.aesh):
                entree["causes"]["aucun AESH disponible sur ce créneau"] += 1
            elif all(probleme.ponderation(a["id"], eleve["id"]) <= -2 for a in probleme.aesh):
                entree["causes"]["tous les AESH sont interdits pour cet élève"] += 1
            else:
                entree["causes"]["quotités épuisées ou créneau disputé"] += 1

    detail_non_couverts = [
        {"eleve": par_id_eleve[i]["nom_complet"],
         "heures": round(v["demi_heures"] / 4, 2),
         "causes": dict(sorted(v["causes"].items(), key=lambda kv: -kv[1]))}
        for i, v in sorted(non_couverts.items(), key=lambda kv: -kv[1]["demi_heures"])]

    total_notifie = sum(e["heures"] for e in probleme.eleves)
    total_couvert = sum(b["heures_couvertes"] for b in bilan_eleves)
    return {
        "statut": nom_statut,
        "message": "",
        "affectations": affectations,
        "eleves": sorted(bilan_eleves, key=lambda b: (b["taux"] is None, b["taux"] or 0)),
        "aesh": sorted(bilan_aesh, key=lambda b: -b["heures_affectees"]),
        "non_couverts": detail_non_couverts,
        "synthese": {
            "heures_notifiees": round(total_notifie, 1),
            "heures_couvertes": round(total_couvert, 1),
            "taux_global": round(100 * total_couvert / total_notifie) if total_notifie else 0,
            "taux_minimal": min((b["taux"] for b in bilan_eleves if b["taux"] is not None), default=0),
            "eleves_hors_calcul": [{"eleve": par_id_eleve[i]["nom_complet"], "raison": r} for i, r in hors_equite],
            "capacite_aesh": round(sum(a["quotite"] for a in probleme.aesh), 1),
            "creneaux_sans_aesh": len(sans_aesh_dispo),
        },
    }
