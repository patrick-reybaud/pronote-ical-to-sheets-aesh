#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
projet.py — état d'un projet d'affectation, et enchaînement des étapes.

Un projet = un dossier sur le poste, contenant `projet.json` (tout l'état) et les pièces importées.
Rien n'est stocké ailleurs : le travail est reprenable, copiable d'un poste à l'autre, et lisible.

L'enchaînement est toujours le même :
    importer le fichier PIAL  →  importer les exports ProNote  →  choisir l'établissement
    →  choisir les deux semaines types  →  renseigner efforts et affinités
    →  recueillir les disponibilités des AESH  →  pondérer  →  calculer  →  publier

Chaque étape est indépendante et rejouable : on peut revenir en arrière sans tout reprendre.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from itertools import combinations
from datetime import date, datetime, timedelta
from pathlib import Path

from . import pronote as P
from .affectation import POIDS_DEFAUT, SANS_ACCOMPAGNEMENT, Probleme, resoudre
from .matieres import FAMILLES, NON_CLASSE, Referentiel
from .pial import lire_pial

DOSSIER_PROJETS = Path.home() / "PIAL-AESH"
PLAGE_DEFAUT = (7, 18)   # les cours commencent à 7 h dans certains établissements


def maintenant():
    return datetime.now().isoformat(timespec="seconds")


def lignes_dispos(valeur):
    """
    Lignes d'une grille de disponibilités, quel que soit le format d'enregistrement.

    Le format courant note la plage en vigueur au moment de la saisie ({"h_min", "grille"}) ;
    les projets antérieurs stockaient la grille nue. Tout ce qui lit les disponibilités passe
    par ici, pour qu'aucun appelant n'ait à connaître les deux formes.
    """
    if isinstance(valeur, dict):
        return valeur.get("grille") or []
    return valeur or []


def cle_retouche(parite, id_cours):
    return f"{parite}|{id_cours}"


def appliquer_retouches(creneaux, retouches):
    """
    Emploi du temps d'un élève après ses corrections manuelles.

    ProNote a le dernier mot sur ce qui se passe réellement dans l'établissement, mais il n'a pas
    toujours raison au moment où on travaille : un élève change de groupe, un cours est déplacé, un
    créneau manque. Plutôt que de retoucher les exports — qu'un nouvel import écraserait — les
    corrections vivent à côté, dans le projet, et se réappliquent à chaque lecture.

    Une correction porte sur un cours entier, désigné par « <parité>|<identifiant ProNote> » :
      · {"supprime": true}                       le cours disparaît de l'emploi du temps
      · {"jour", "debut", "duree", "matiere", "salle"}   ce qui est fourni remplace l'original
      · {"ajout": true, …}                       un cours que ProNote ne connaît pas

    Retourne (créneaux corrigés, corrections devenues sans objet). Une correction qui viserait un
    cours disparu de l'export n'est pas une erreur : elle est signalée, jamais appliquée de force.
    """
    if not retouches:
        return creneaux, []

    # Un cours occupe plusieurs demi-heures consécutives : on le reconstitue avant de le corriger,
    # sinon « déplacer » n'aurait aucun sens à l'échelle d'un créneau isolé.
    cours = {}
    for (parite, jour, s), donnees in sorted(creneaux.items()):
        entree = cours.setdefault(cle_retouche(parite, donnees["id_cours"]),
                                  {"parite": parite, "jour": jour, "debut": s, "creneaux": [],
                                   "cours": donnees})
        entree["creneaux"].append(s)
        entree["debut"] = min(entree["debut"], s)

    orphelines = []
    for cle, retouche in (retouches or {}).items():
        if not isinstance(retouche, dict):
            continue
        if retouche.get("ajout"):
            parite = (cle.split("|", 1) + [""])[0]
            cours[cle] = {"parite": parite, "jour": int(retouche.get("jour", 0)),
                          "debut": int(retouche.get("debut", 0)),
                          "creneaux": list(range(int(retouche.get("debut", 0)),
                                                 int(retouche.get("debut", 0))
                                                 + max(1, int(retouche.get("duree", 1))))),
                          "cours": {"id_cours": cle.split("|", 1)[-1],
                                    "matiere": retouche.get("matiere") or "Cours ajouté",
                                    "salle": retouche.get("salle") or "", "ajoute": True}}
            continue
        existant = cours.get(cle)
        if not existant:
            orphelines.append(cle)
            continue
        if retouche.get("supprime"):
            cours.pop(cle)
            continue
        debut = int(retouche.get("debut", existant["debut"]))
        duree = max(1, int(retouche.get("duree", len(existant["creneaux"]))))
        existant["jour"] = int(retouche.get("jour", existant["jour"]))
        existant["debut"] = debut
        existant["creneaux"] = list(range(debut, debut + duree))
        modifie = dict(existant["cours"])
        for champ in ("matiere", "salle"):
            if retouche.get(champ) is not None:
                modifie[champ] = retouche[champ]
        modifie["retouche"] = True
        existant["cours"] = modifie

    corriges = {}
    for entree in cours.values():
        for s in entree["creneaux"]:
            corriges[(entree["parite"], entree["jour"], s)] = entree["cours"]
    return corriges, orphelines


def conflits_retouche(voisins, parite, jour, debut, duree):
    """
    Cours de l'élève qu'une correction viendrait chevaucher.

    Un élève n'est qu'à un endroit à la fois : poser un cours par-dessus un autre ne produit pas un
    emploi du temps discutable, il en produit un faux. On refuse donc avant d'enregistrer, en
    nommant ce qui gêne — plutôt que de laisser le calcul trancher au hasard plus tard.

    « voisins » est l'emploi du temps **privé du cours qu'on est en train de corriger** : c'est
    indispensable, car deux cours posés sur le même créneau s'écraseraient l'un l'autre dans la
    grille et le chevauchement deviendrait invisible.
    """
    gene = {}
    for s in range(debut, debut + duree):
        autre = voisins.get((parite, jour, s))
        if autre:
            gene[autre["id_cours"]] = autre.get("matiere") or autre["id_cours"]
    return sorted(gene.values())


class Projet:
    def __init__(self, dossier):
        self.dossier = Path(dossier)
        self.dossier.mkdir(parents=True, exist_ok=True)
        (self.dossier / "sources").mkdir(exist_ok=True)
        self.chemin = self.dossier / "projet.json"
        neuf = not self.chemin.exists()
        self.etat = self._charger()
        self._cache_ics = {}
        self._cache_sorties = {}
        if neuf:
            # Un projet créé mais jamais modifié n'existait que dans la mémoire du serveur : il
            # n'apparaissait pas dans la liste et ne pouvait pas être supprimé. On l'inscrit tout de suite.
            self.enregistrer()

    # ───────────────────────────── Persistance ─────────────────────────────

    def _charger(self):
        if self.chemin.exists():
            try:
                return json.loads(self.chemin.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                secours = self.chemin.with_suffix(f".corrompu-{datetime.now():%Y%m%d%H%M%S}.json")
                shutil.copy(self.chemin, secours)
                raise ValueError(f"Le fichier de projet est illisible ({e}). "
                                 f"Une copie a été conservée : {secours.name}")
        return {
            "version": 1, "nom": self.dossier.name, "cree_le": maintenant(), "modifie_le": maintenant(),
            "fichier_pial": None, "sources_ics": [], "etablissement": None,
            "semaines_types": [], "plage": list(PLAGE_DEFAUT), "max_mutualise": 2,
            "max_aesh_par_eleve": 3,
            "pause": {"debut": 11, "fin": 14, "minutes": 60},
            "cours_imposes": {},
            "retouches": {},         # corrections manuelles des emplois du temps, par élève
            "periodes": [],           # stages, journées d'intégration, CCF
            "resultats_periodes": {},  # affectation propre à chaque période
            "poids": dict(POIDS_DEFAUT), "efforts": {}, "affinites": {}, "paires": {},
            "corrections_matieres": {}, "aesh_desactives": [], "dispos": {}, "resultat": None,
            "heures_eleves": {},      # corrections manuelles des heures notifiées
            "appariements_forces": {},  # id_eleve → nom du fichier ICS imposé à la main
            "mutualisation": {},      # id_eleve → "auto" | "jamais" | "possible"
            "paires_eleves": {},      # "idA|idB" → -1 incompatibles · 1 à regrouper
            # Les libellés qu'aucune règle ne reconnaît ne sont pas des cours à accompagner
            # (« Réservation de salle », « Journée d'intégration »…) : écartés d'emblée,
            # et réaffectables à une vraie famille depuis l'écran Élèves.
            "matieres_exclues": [NON_CLASSE],
        }

    def enregistrer(self):
        self.etat["modifie_le"] = maintenant()
        self.chemin.write_text(json.dumps(self.etat, ensure_ascii=False, indent=2), encoding="utf-8")

    def deposer(self, nom_fichier, contenu):
        """Copie une pièce importée dans le projet, pour que celui-ci reste autonome."""
        cible = self.dossier / "sources" / Path(nom_fichier).name
        cible.write_bytes(contenu)
        return cible

    # ───────────────────────────── Import ─────────────────────────────

    def importer_pial(self, chemin):
        donnees = lire_pial(chemin)
        self.etat["fichier_pial"] = str(chemin)
        self.etat["resultat"] = None
        self.enregistrer()
        return donnees

    def donnees_pial(self):
        if not self.etat.get("fichier_pial"):
            return None
        return lire_pial(self.etat["fichier_pial"])

    def ajouter_sources_ics(self, chemins):
        existantes = set(self.etat["sources_ics"])
        for c in chemins:
            if str(c) not in existantes:
                self.etat["sources_ics"].append(str(c))
        self.etat["resultat"] = None
        self.enregistrer()
        return self.index_ics()

    def index_ics(self):
        return P.indexer_ics(self.etat["sources_ics"]) if self.etat["sources_ics"] else ([], [])

    def cours_de(self, chemin):
        if chemin not in self._cache_ics:
            cours, _, sorties = P.lire_ics(chemin)
            self._cache_ics[chemin] = cours
            self._cache_sorties[chemin] = sorties
        return self._cache_ics[chemin]

    def sorties_de(self, chemin):
        self.cours_de(chemin)
        return self._cache_sorties.get(chemin, [])

    # ───────────────────────────── Analyse ─────────────────────────────

    @property
    def referentiel(self):
        return Referentiel(self.etat.get("corrections_matieres"))

    def population(self):
        """
        Élèves et AESH de l'établissement retenu, enrichis de leur emploi du temps type.
        Retourne aussi le rapport d'appariement : c'est ce que l'écran « Élèves » montre.
        """
        donnees = self.donnees_pial()
        if not donnees:
            return {"eleves": [], "aesh": [], "appariement": [], "semaines": [], "matieres": []}
        etablissement = self.etat.get("etablissement")
        filtre = (lambda p: p["etablissement"] == etablissement) if etablissement else (lambda p: True)
        eleves = []
        for eleve in donnees["eleves"]:
            if not filtre(eleve):
                continue
            correction = self.etat.get("heures_eleves", {}).get(eleve["id"])
            if correction is not None:
                eleve = {**eleve, "heures": float(correction), "heures_corrigee": True}
            eleves.append(eleve)
        aesh = [a for a in donnees["aesh"] if filtre(a)]

        index, _ = self.index_ics()
        par_fichier = {Path(e["chemin"]).name: e for e in index}
        forces = self.etat.get("appariements_forces") or {}
        appariement, cours_par_eleve = [], {}
        for eleve in eleves:
            impose = forces.get(eleve["id"])
            if impose and impose in par_fichier:
                entree, score, explication = par_fichier[impose], 1.0, "association forcée à la main"
            elif impose:
                entree, score, explication = None, 0.0, (
                    f"association forcée vers « {impose} », mais ce fichier n'est plus dans les exports")
            else:
                entree, score, explication = P.apparier(eleve, index)
            if entree:
                cours_par_eleve[eleve["id"]] = self.cours_de(entree["chemin"])
            appariement.append({"eleve": eleve["id"], "nom": eleve["nom_complet"],
                                "dob": eleve.get("dob_texte") or "",
                                "classe": eleve.get("classe") or eleve.get("niveau") or "",
                                "trouve": bool(entree), "score": round(score, 2),
                                "explication": explication, "force": bool(impose),
                                "fichier": Path(entree["chemin"]).name if entree else ""})

        semaines = P.inventaire_semaines(cours_par_eleve)
        if not self.etat.get("semaines_types") and semaines:
            self.etat["semaines_types"] = P.proposer_semaines_types(semaines)
            self.etat["plage_a_ajuster"] = True     # la plage sera calée sur les cours au premier affichage
            self.enregistrer()

        matieres = sorted({c["matiere"] for cours in cours_par_eleve.values() for c in cours})
        return {"eleves": eleves, "aesh": aesh, "appariement": appariement,
                "semaines": semaines, "matieres": matieres, "cours": cours_par_eleve}

    def candidats_ics(self, eleve, recherche="", limite=20):
        """
        Fichiers ProNote les plus proches d'un élève, pour une association manuelle.

        Trie par ressemblance du nom et signale l'écart de date de naissance : c'est exactement ce
        qu'il faut voir pour trancher entre « ce n'est pas la bonne personne » et « la date est
        fausse dans l'un des deux fichiers ».
        """
        index, _ = self.index_ics()
        attendue = eleve.get("dob")
        attendue = date.fromisoformat(attendue) if isinstance(attendue, str) and attendue else attendue
        motif = P.compacter(recherche)
        resultats = []
        for entree in index:
            if motif and motif not in P.compacter(entree["libelle"]):
                continue
            resultats.append({
                "fichier": Path(entree["chemin"]).name,
                "libelle": entree["libelle"],
                "dob": entree["dob"].strftime("%d/%m/%Y") if entree["dob"] else "",
                "meme_date": bool(attendue and entree["dob"] == attendue),
                "score": round(P.similarite(eleve["nom_complet"], entree["libelle"]), 2),
            })
        resultats.sort(key=lambda r: (not r["meme_date"], -r["score"]))
        return resultats[:limite]

    def grilles_completes(self, population=None, avec_retouches=True):
        """
        Emploi du temps type de chaque élève, corrections manuelles comprises, sans aucun filtre.

        Un élève sans aucun cours ces deux semaines-là (stage, arrivée tardive) n'est pas abandonné :
        on retombe sur ses deux semaines les plus fournies, en gardant l'alternance A/B alignée sur
        celle de l'établissement. Le repli est signalé, jamais silencieux.

        Retourne (grilles, heures hors plage, replis, corrections sans objet). Tous les cours y
        figurent, y compris ceux qu'on a décidé de ne pas accompagner : c'est la vue de référence,
        celle qu'on montre à l'écran. Le tri revient à `grilles()`.
        """
        population = population or self.population()
        h_min, h_max = self.etat.get("plage") or PLAGE_DEFAUT
        semaines = self.etat.get("semaines_types") or []
        grilles, hors_plage, replis, sans_objet = {}, 0, [], {}
        if not semaines:
            return grilles, hors_plage, replis, sans_objet
        for eleve in population["eleves"]:
            cours = population["cours"].get(eleve["id"])
            if not cours:
                continue
            retenues = semaines
            grille, hors_grille, _ = P.grille_type(cours, retenues, h_min, h_max)
            if not grille:
                secours = P.semaines_de_repli(cours, semaines)
                if secours:
                    retenues = secours
                    grille, hors_grille, _ = P.grille_type(cours, retenues, h_min, h_max)
                    if grille:
                        replis.append({"eleve": eleve["id"], "nom": eleve["nom_complet"],
                                       "semaines": retenues})
            creneaux = {}
            for (jour, s), case in grille.items():
                for parite in ("A", "B"):
                    if case[parite]:
                        creneaux[(parite, jour, s)] = case[parite][0]
            # Les corrections manuelles s'appliquent avant tout le reste : elles font partie de
            # l'emploi du temps, au même titre que ce qui vient de ProNote.
            if avec_retouches:
                creneaux, orphelines = appliquer_retouches(
                    creneaux, (self.etat.get("retouches") or {}).get(eleve["id"]))
                if orphelines:
                    sans_objet[eleve["id"]] = orphelines
            grilles[eleve["id"]] = creneaux
            hors_plage += len(hors_grille)
        return grilles, hors_plage, replis, sans_objet

    def motif_non_accompagne(self, id_eleve, cours):
        """
        Pourquoi ce cours ne compte pas dans le besoin de l'élève — ou None s'il y compte.

        Trois raisons seulement, et toutes assumées ailleurs dans l'application : une dispense
        signalée par ProNote, une famille de matières retirée pour tout le monde, ou un effort mis à
        zéro pour cet élève-là. Les nommer permet à l'écran des emplois du temps de montrer ces
        cours en grisé avec leur motif, au lieu de les faire disparaître sans explication.
        """
        if cours.get("dispense"):
            return "dispense — présence facultative"
        famille = self.referentiel.famille(cours["matiere"])
        if famille in set(self.etat.get("matieres_exclues") or []):
            return "matière retirée de l'accompagnement"
        if (self.etat.get("efforts") or {}).get(id_eleve, {}).get(famille) == 0:
            return "effort mis à 0 pour cet élève"
        return None

    def grilles(self, population=None):
        """Emplois du temps ne retenant que les cours à accompagner — ce que voit le calcul."""
        population = population or self.population()
        brutes, hors_plage, replis, _ = self.grilles_completes(population)
        grilles = {id_eleve: {cle: cours for cle, cours in creneaux.items()
                              if not self.motif_non_accompagne(id_eleve, cours)}
                   for id_eleve, creneaux in brutes.items()}
        return grilles, hors_plage, replis

    def heures_retirees(self, population=None):
        """Heures écartées de l'accompagnement par famille — pour que le retrait reste visible."""
        population = population or self.population()
        exclues = set(self.etat.get("matieres_exclues") or [])
        efforts = self.etat.get("efforts") or {}
        referentiel = self.referentiel
        h_min, h_max = self.etat.get("plage") or PLAGE_DEFAUT
        semaines = self.etat.get("semaines_types") or []
        compte = Counter()
        if not semaines:
            return {}
        for eleve in population["eleves"]:
            cours = population["cours"].get(eleve["id"])
            if not cours:
                continue
            grille, _, _ = P.grille_type(cours, semaines, h_min, h_max)
            for case in grille.values():
                for parite in ("A", "B"):
                    if not case[parite]:
                        continue
                    famille = referentiel.famille(case[parite][0]["matiere"])
                    if famille in exclues or efforts.get(eleve["id"], {}).get(famille) == 0:
                        compte[famille] += 1
        return {famille: round(n / 4, 2) for famille, n in compte.most_common()}

    def opportunites_mutualisation(self, population=None, grilles=None):
        """
        Couples d'élèves qui suivent **exactement le même cours au même moment**, avec le volume
        concerné. C'est la matière première de la mutualisation : sans cours commun, deux élèves ne
        peuvent pas partager un accompagnant, quelle que soit la règle qu'on écrive.

        Le rapprochement se fait sur l'identifiant de cours ProNote, pas sur le libellé : deux
        classes différentes ayant « MATHEMATIQUES » à la même heure ne sont pas dans le même cours.
        """
        population = population or self.population()
        if grilles is None:
            grilles, _, _ = self.grilles(population)
        noms = {e["id"]: e["nom_complet"] for e in population["eleves"]}
        types = {e["id"]: e["type_aide"] for e in population["eleves"]}

        ensemble = defaultdict(list)
        for id_eleve, creneaux in grilles.items():
            for cle, cours in creneaux.items():
                ensemble[(cle, cours["id_cours"])].append((id_eleve, cours))
        volume, matieres = Counter(), defaultdict(set)
        for membres in ensemble.values():
            identifiants = sorted({m[0] for m in membres})
            libelle = membres[0][1]["matiere"]
            for a, b in combinations(identifiants, 2):
                volume[(a, b)] += 1
                matieres[(a, b)].add(libelle)

        reglages = self.etat.get("mutualisation", {})
        paires = self.etat.get("paires_eleves", {})
        resultat = []
        for (a, b), demi_heures in volume.most_common():
            resultat.append({
                "a": a, "b": b, "nom_a": noms.get(a, a), "nom_b": noms.get(b, b),
                "type_a": types.get(a, ""), "type_b": types.get(b, ""),
                "mode_a": reglages.get(a, "auto"), "mode_b": reglages.get(b, "auto"),
                "heures": round(demi_heures / 4, 2),
                "matieres": sorted(matieres[(a, b)])[:6],
                "reglage": paires.get(f"{a}|{b}") or paires.get(f"{b}|{a}") or 0,
            })
        return resultat

    # ───────────────────────────── Disponibilités des AESH ─────────────────────────────

    def disponibilites(self, id_aesh):
        """Créneaux déclarés d'un AESH : {(jour, indice)} dans la plage courante."""
        h_min, h_max = self.etat.get("plage") or PLAGE_DEFAUT
        grille = self.grille_disponibilites(id_aesh)
        nb = (h_max - h_min) * 60 // P.PAS_MINUTES
        return {(j, s) for j, ligne in enumerate(grille) for s in range(min(nb, len(ligne))) if ligne[s]}

    def grille_disponibilites(self, id_aesh):
        """
        Grille des disponibilités ramenée à la plage horaire courante.

        Les disponibilités sont enregistrées avec la plage en vigueur au moment de la saisie. Sans
        cela, élargir la plage de 8 h à 7 h décalerait toute la grille d'une heure sans prévenir :
        ce qui avait été coché pour 8 h se retrouverait à 7 h. On reconvertit donc par l'heure réelle.
        """
        h_min, h_max = self.etat.get("plage") or PLAGE_DEFAUT
        nb = (h_max - h_min) * 60 // P.PAS_MINUTES
        brut = (self.etat.get("dispos") or {}).get(id_aesh)
        if not brut:
            return [[False] * nb for _ in range(5)]
        origine = brut.get("h_min", h_min) if isinstance(brut, dict) else h_min
        lignes = lignes_dispos(brut)
        decalage = (origine - h_min) * 60 // P.PAS_MINUTES
        grille = []
        for j in range(5):
            source = lignes[j] if j < len(lignes) else []
            grille.append([bool(source[s - decalage]) if 0 <= s - decalage < len(source) else False
                           for s in range(nb)])
        return grille

    def definir_disponibilites(self, id_aesh, grille):
        h_min, _ = self.etat.get("plage") or PLAGE_DEFAUT
        self.etat.setdefault("dispos", {})[id_aesh] = {"h_min": h_min, "grille": grille}
        self.etat["resultat"] = None
        self.enregistrer()

    def changer_plage(self, nouvelle):
        """
        Change la plage horaire sans déplacer ce qui a déjà été coché.

        Les disponibilités enregistrées avant que ce format existe n'indiquent pas la plage qui avait
        cours au moment de la saisie : on la fige ici, **avant** d'écrire la nouvelle. Fait à la
        lecture, ce rattrapage serait toujours en retard d'un changement.
        """
        ancienne = (self.etat.get("plage") or PLAGE_DEFAUT)[0]
        dispos = self.etat.get("dispos") or {}
        for id_aesh, valeur in list(dispos.items()):
            if not isinstance(valeur, dict):
                dispos[id_aesh] = {"h_min": ancienne, "grille": valeur}
        self.etat["plage"] = [int(nouvelle[0]), int(nouvelle[1])]
        self.etat["resultat"] = None
        self.enregistrer()

    def amplitude_cours(self, population=None):
        """
        Amplitude réelle des cours des élèves notifiés, et plage conseillée.

        La plage conseillée couvre 99 % des demi-heures de cours : dans un lycée hôtelier, quelques
        services de restauration finissent à 23 h et étireraient la grille de six heures pour cinq
        créneaux, que personne n'ira accompagner.
        """
        population = population or self.population()
        semaines = self.etat.get("semaines_types") or []
        compte = Counter()
        for cours in population["cours"].values():
            for c in cours:
                if semaines and c["debut"].date().isocalendar()[1] not in semaines:
                    continue
                minute = c["debut"].hour * 60 + c["debut"].minute
                fin = c["fin"].hour * 60 + c["fin"].minute
                if fin <= minute:
                    fin = 24 * 60
                while minute < fin:
                    compte[minute // 60] += 1
                    minute += P.PAS_MINUTES
        if not compte:
            return None
        heures = sorted(compte)
        total = sum(compte.values())
        garde, cumul = [], 0
        for heure in heures:                     # on écarte les heures marginales par le haut
            cumul += compte[heure]
            garde.append(heure)
            if cumul >= 0.99 * total:
                break
        return {"min_reel": min(heures), "max_reel": max(heures) + 1,
                "propose_min": min(garde), "propose_max": max(garde) + 1,
                "hors_proposition": total - cumul,
                "par_heure": {str(h): compte[h] for h in heures}}

    def alternatives_affectation(self, population=None):
        """
        Chaque cours à accompagner, qui s'en charge, et qui pourrait s'en charger.

        Tous les cours y figurent, y compris ceux que personne n'accompagne : c'est précisément
        là qu'on a besoin de pouvoir désigner quelqu'un à la main. Un AESH n'est proposé que s'il
        est disponible sur **toute** la durée du cours, n'est pas interdit pour cet élève et ne
        refuse pas la matière — les trois mêmes conditions que le calcul, sans quoi on proposerait
        des affectations que le solveur déclarerait ensuite impossibles.

        « libre » distingue celui qui n'a rien à ce moment-là de celui qui est déjà pris : le second
        reste choisissable, mais le calcul devra déplacer son cours actuel, et il dira s'il n'y
        arrive pas. On ne tranche pas ici — seul le solveur sait si l'ensemble reste cohérent.
        """
        population = population or self.population()
        grilles, _, _ = self.grilles(population)
        if not grilles:
            return []
        resultat = self.etat.get("resultat") or {}
        desactives = set(self.etat.get("aesh_desactives", []))
        aesh = [a for a in population["aesh"] if a["id"] not in desactives]
        dispos = {a["id"]: self.disponibilites(a["id"]) for a in aesh}
        paires = self.etat.get("paires") or {}
        affinites = self.etat.get("affinites") or {}
        imposes = self.etat.get("cours_imposes") or {}
        noms_eleves = {e["id"]: e["nom_complet"] for e in population["eleves"]}

        # Ce que le calcul a retenu, et ce que chaque AESH fait à chaque demi-heure.
        affecte, occupation = {}, defaultdict(dict)
        for a in resultat.get("affectations") or []:
            affecte[(a["eleve"], a["parite"], a["id_cours"])] = (a["aesh"], a["aesh_nom"])
            occupation[a["aesh"]][(a["parite"], a["jour"], a["creneau"])] = a["eleve_nom"]

        # Les cours viennent des emplois du temps, pas du résultat : sinon les cours non couverts
        # — les seuls sur lesquels on ait vraiment envie d'intervenir — seraient absents.
        cours = {}
        for id_eleve, creneaux in grilles.items():
            for (parite, jour, creneau), donnees in creneaux.items():
                cle = (id_eleve, parite, donnees["id_cours"])
                entree = cours.setdefault(cle, {
                    "eleve": id_eleve, "eleve_nom": noms_eleves.get(id_eleve, id_eleve),
                    "parite": parite, "jour": jour, "matiere": donnees["matiere"],
                    "salle": donnees.get("salle", ""), "creneaux": [],
                    "retouche": bool(donnees.get("retouche") or donnees.get("ajoute"))})
                entree["creneaux"].append(creneau)

        sortie = []
        for cle, info in sorted(cours.items(), key=lambda kv: (kv[1]["eleve_nom"], kv[1]["jour"],
                                                              min(kv[1]["creneaux"]))):
            creneaux = sorted(info["creneaux"])
            requis = [(info["jour"], c) for c in creneaux]
            famille = self.referentiel.famille(info["matiere"])
            id_actuel, nom_actuel = affecte.get(cle, ("", ""))
            propositions = []
            for personne in aesh:
                if personne["id"] == id_actuel:
                    continue
                if (paires.get(f"{personne['id']}|{info['eleve']}") or 0) <= -2:
                    continue
                if affinites.get(personne["id"], {}).get(famille) == 0:
                    continue
                if not all(r in dispos[personne["id"]] for r in requis):
                    continue
                pris = {occupation[personne["id"]].get((info["parite"], info["jour"], c))
                        for c in creneaux}
                pris.discard(None)
                propositions.append({"id": personne["id"], "nom": personne["nom_complet"],
                                     "libre": not pris, "occupe_par": sorted(pris)})
            propositions.sort(key=lambda p: (not p["libre"], p["nom"]))
            texte = f"{cle[0]}|{cle[1]}|{cle[2]}"
            sortie.append({
                "cle": texte,
                **{k: v for k, v in info.items() if k != "creneaux"},
                "aesh": id_actuel, "aesh_nom": nom_actuel,
                "creneaux": creneaux,
                "debut": creneaux[0],
                "duree": round(len(creneaux) / 2, 1),
                "impose": imposes.get(texte),
                "alternatives": propositions,
            })
        return sortie

    # ───────────────────────────── Retouches d'emploi du temps ─────────────────────────────

    def perimer_resultat(self):
        """
        Note que le dernier calcul ne correspond plus à ce qui est demandé.

        Un verrou posé ou un cours déplacé ne change pas le résultat affiché : il change ce que le
        résultat devrait être. Sans ce repère, on lit un emploi du temps en croyant qu'il tient
        compte de la décision qu'on vient de prendre. L'avertissement survit au rechargement de la
        page parce qu'il est dans le projet, pas dans le navigateur.
        """
        if self.etat.get("resultat"):
            self.etat["resultat_perime"] = True
            self.enregistrer()

    def retouches_de(self, id_eleve):
        return dict((self.etat.get("retouches") or {}).get(id_eleve) or {})

    def _enregistrer_retouches(self, id_eleve, retouches):
        toutes = dict(self.etat.get("retouches") or {})
        if retouches:
            toutes[id_eleve] = retouches
        else:
            toutes.pop(id_eleve, None)
        self.etat["retouches"] = toutes
        self.enregistrer()

    def nb_creneaux(self):
        h_min, h_max = self.etat.get("plage") or PLAGE_DEFAUT
        return (h_max - h_min) * 60 // P.PAS_MINUTES

    def retoucher(self, id_eleve, cles, action, valeurs=None, parites=None, population=None):
        """
        Corrige l'emploi du temps d'un élève : déplacer, redimensionner, supprimer, ajouter un cours.

        La correction porte sur un cours entier et sur les semaines qu'on lui désigne — un cours
        hebdomadaire se corrige dans les deux d'un seul geste, un cours de quinzaine dans la sienne
        seulement. Rien n'est enregistré si le résultat placerait l'élève à deux endroits en même
        temps : on nomme alors le cours qui gêne, car un emploi du temps impossible ne se rattrape
        pas au calcul suivant.
        """
        valeurs = valeurs or {}
        # Emploi du temps d'origine : les corrections s'appliquent dessus, jamais l'une sur l'autre.
        brutes, _, _, _ = self.grilles_completes(population, avec_retouches=False)
        origine = brutes.get(id_eleve) or {}
        retouches = self.retouches_de(id_eleve)
        limite = self.nb_creneaux()

        if action == "annuler":
            for cle in cles:
                retouches.pop(cle, None)
            self._enregistrer_retouches(id_eleve, retouches)
            return {"retouches": retouches}

        if action == "supprimer":
            for cle in cles:
                if cle.split("|", 1)[-1].startswith("ajout-"):
                    retouches.pop(cle, None)      # un cours ajouté se retire, il ne se masque pas
                else:
                    retouches[cle] = {"supprime": True}
            self._enregistrer_retouches(id_eleve, retouches)
            return {"retouches": retouches}

        # Un cours ajouté porte un intitulé que ProNote ne connaît pas : sans famille de matières,
        # il retombe dans « à classer », famille écartée d'office, et disparaît du calcul sans que
        # personne ne comprenne pourquoi. La famille est donc demandée et enregistrée dans le même
        # référentiel que les corrections de l'écran « Élèves » — le solveur, les efforts, les
        # affinités et les exports la voient tous.
        famille = (valeurs.get("famille") or "").strip()
        libelle = (valeurs.get("matiere") or "").strip()
        if (famille and libelle and famille in FAMILLES
                and self.referentiel.famille(libelle) != famille):
            # Seulement si cela change quelque chose : réenregistrer une famille déjà déduite
            # ferait apparaître la matière comme « corrigée à la main » dans l'écran « Élèves ».
            corrections = dict(self.etat.get("corrections_matieres") or {})
            corrections[libelle] = famille
            self.etat["corrections_matieres"] = corrections

        jour = int(valeurs.get("jour", 0))
        debut = int(valeurs.get("debut", 0))
        duree = max(1, int(valeurs.get("duree", 1)))
        if not 0 <= jour < len(P.JOURS[:5]):
            raise ValueError("Jour hors de la semaine.")
        if debut < 0 or debut + duree > limite:
            h_min = (self.etat.get("plage") or PLAGE_DEFAUT)[0]
            raise ValueError(f"Ce cours sortirait de la plage horaire du projet "
                             f"({h_min} h – {(self.etat.get('plage') or PLAGE_DEFAUT)[1]} h). "
                             f"Élargissez la plage dans « Établissement » ou raccourcissez le cours.")

        if action == "ajouter":
            parites = parites or ["A", "B"]
            numero = 1 + max([int(c.rsplit("-", 1)[-1]) for c in retouches
                              if c.split("|", 1)[-1].startswith("ajout-")
                              and c.rsplit("-", 1)[-1].isdigit()] or [0])
            cles = [cle_retouche(parite, f"ajout-{numero}") for parite in parites]
            for cle in cles:
                retouches[cle] = {"ajout": True, "jour": jour, "debut": debut, "duree": duree,
                                  "matiere": valeurs.get("matiere") or "Cours ajouté",
                                  "salle": valeurs.get("salle") or ""}
        elif action == "modifier":
            for cle in cles:
                base = dict(retouches.get(cle) or {})
                base.update({"jour": jour, "debut": debut, "duree": duree})
                base.pop("supprime", None)
                for champ in ("matiere", "salle"):
                    if valeurs.get(champ) is not None:
                        base[champ] = valeurs[champ]
                retouches[cle] = base
        else:
            raise ValueError(f"Action inconnue : {action}")

        # On vérifie contre l'emploi du temps tel qu'il sera, le cours corrigé mis de côté.
        voisins, _ = appliquer_retouches(
            {k: v for k, v in origine.items()
             if cle_retouche(k[0], v["id_cours"]) not in cles},
            {k: v for k, v in retouches.items() if k not in cles})
        for cle in cles:
            parite = cle.split("|", 1)[0]
            gene = conflits_retouche(voisins, parite, jour, debut, duree)
            if gene:
                raise ValueError(f"En semaine {parite}, ce créneau est déjà occupé par : "
                                 f"{', '.join(gene)}. Déplacez ou supprimez d'abord ce cours-là.")
        self._enregistrer_retouches(id_eleve, retouches)
        return {"retouches": retouches}

    # ───────────────────────────── Périodes particulières ─────────────────────────────
    #
    # Ni les stages, ni les journées d'intégration, ni les CCF ne figurent dans l'export ProNote :
    # les catégories exportées se limitent aux cours, aux vacances et aux jours fériés. Ces périodes
    # sont donc déclarées par la coordination, qui seule les connaît.
    #
    #   · stage / intégration : les élèves concernés ne sont pas accompagnés ; leurs AESH sont
    #     redistribués sur les autres élèves, ce qui donne une affectation propre à la période ;
    #   · CCF : les élèves concernés doivent être accompagnés sur toute la durée de l'épreuve.

    TYPES_PERIODE = {"stage": "Stage / PFMP", "integration": "Journée d'intégration",
                     "ccf": "CCF — accompagnement obligatoire", "autre": "Autre absence"}

    def periodes_detectees(self, population=None):
        """
        Périodes candidates, déduites de ce que ProNote exporte réellement.

        Trois signatures exploitables, vérifiées sur les données :
          · **journée d'intégration** — libellé « JOURNEE D'INTEGRATION », catégorie « Cours - Exceptionnel » ;
          · **sortie pédagogique** — catégorie « Sorties Pédagogiques », ignorée ailleurs dans l'application ;
          · **absence longue** — l'élève n'a aucun cours pendant une ou plusieurs semaines entières
            alors que la majorité de l'établissement en a. C'est la seule trace qu'un stage laisse :
            ni « stage », ni « PFMP », ni « CCF » n'apparaissent nulle part dans un export ProNote.

        Rien n'est appliqué d'office : ce sont des propositions, à confirmer et à nommer.
        """
        population = population or self.population()
        index, _ = self.index_ics()
        par_fichier = {Path(e["chemin"]).name: e for e in index}
        forces = self.etat.get("appariements_forces") or {}

        integrations, sorties = defaultdict(set), defaultdict(set)
        semaines_eleve, toutes_semaines = {}, Counter()
        for eleve in population["eleves"]:
            cours = population["cours"].get(eleve["id"])
            if not cours:
                continue
            semaines = {c["debut"].date().isocalendar()[1] for c in cours}
            semaines_eleve[eleve["id"]] = semaines
            for s in semaines:
                toutes_semaines[s] += 1
            for c in cours:
                if c.get("integration"):
                    integrations[c["debut"].date()].add(eleve["id"])
            impose = forces.get(eleve["id"])
            entree = par_fichier.get(impose) if impose else None
            if entree is None:
                entree, _, _ = P.apparier(eleve, index)
            if entree:
                for sortie in self.sorties_de(entree["chemin"]):
                    sorties[sortie["debut"].date()].add(eleve["id"])

        propositions = []
        for jour, eleves in sorted(integrations.items()):
            propositions.append({"type": "integration", "nom": f"Journée d'intégration du {jour:%d/%m}",
                                 "debut": jour.isoformat(), "fin": jour.isoformat(),
                                 "eleves": sorted(eleves), "origine": "libellé ProNote"})
        for jour, eleves in sorted(sorties.items()):
            propositions.append({"type": "autre", "nom": f"Sortie pédagogique du {jour:%d/%m}",
                                 "debut": jour.isoformat(), "fin": jour.isoformat(),
                                 "eleves": sorted(eleves), "origine": "catégorie « Sorties Pédagogiques »"})

        # Absences longues : signature d'un stage, faute de mieux.
        scolaires = sorted(s for s, n in toutes_semaines.items() if n >= 0.6 * max(1, len(semaines_eleve)))
        lundis = {}
        for eleve in population["eleves"]:
            for c in population["cours"].get(eleve["id"]) or []:
                lundis.setdefault(c["debut"].date().isocalendar()[1], P.lundi_de(c["debut"].date()))
        for id_eleve, semaines in semaines_eleve.items():
            absentes = [s for s in scolaires if s not in semaines]
            blocs, debut, precedent = [], None, None
            for s in absentes:
                if precedent is None or scolaires.index(s) != scolaires.index(precedent) + 1:
                    if debut is not None:
                        blocs.append((debut, precedent))
                    debut = s
                precedent = s
            if debut is not None:
                blocs.append((debut, precedent))
            nom_eleve = next(e["nom_complet"] for e in population["eleves"] if e["id"] == id_eleve)
            for a, b in blocs:
                if a not in lundis or b not in lundis:
                    continue
                propositions.append({
                    "type": "stage", "nom": f"Absence de {nom_eleve} (S{a}" + (f"–S{b})" if a != b else ")"),
                    "debut": lundis[a].isoformat(),
                    "fin": (lundis[b] + timedelta(days=4)).isoformat(),
                    "eleves": [id_eleve],
                    "origine": "aucun cours ces semaines-là — stage probable, à confirmer"})
        return propositions

    def periodes(self):
        return list(self.etat.get("periodes") or [])

    def periode(self, identifiant):
        return next((p for p in self.periodes() if p["id"] == identifiant), None)

    def semaines_de(self, periode):
        """Numéros de semaines ISO couverts par une période déclarée."""
        try:
            debut = date.fromisoformat(periode["debut"])
            fin = date.fromisoformat(periode["fin"])
        except (KeyError, ValueError):
            return []
        semaines, jour = [], debut
        while jour <= fin:
            numero = jour.isocalendar()[1]
            if numero not in semaines:
                semaines.append(numero)
            jour += timedelta(days=7)
        fin_numero = fin.isocalendar()[1]
        if fin_numero not in semaines:
            semaines.append(fin_numero)
        return semaines

    def grilles_periode(self, periode, population=None):
        """
        Emplois du temps des élèves **pendant** une période donnée, et non sur les semaines types.

        Une période a son propre calendrier : c'est lui qui fait foi. On reprend au plus deux de ses
        semaines pour garder la lecture « sem. A / sem. B », l'alternance restant alignée sur celle
        de l'établissement par la parité du numéro de semaine.
        """
        population = population or self.population()
        semaines = self.semaines_de(periode)
        if not semaines:
            return {}, [], []
        reference = self.etat.get("semaines_types") or semaines[:1]
        parite_a = reference[0] % 2
        retenues = sorted(semaines, key=lambda s: (s % 2 != parite_a, s))[:2] or semaines[:1]
        retenues = sorted(retenues, key=lambda s: s % 2 != parite_a)

        h_min, h_max = self.etat.get("plage") or PLAGE_DEFAUT
        absents = set(periode.get("eleves") or []) if periode.get("type") in ("stage", "integration", "autre") else set()
        grilles, sans_cours = {}, []
        for eleve in population["eleves"]:
            if eleve["id"] in absents:
                continue
            cours = population["cours"].get(eleve["id"])
            if not cours:
                continue
            grille, _, _ = P.grille_type(cours, retenues, h_min, h_max)
            creneaux = {}
            for (jour, s), case in grille.items():
                for parite in ("A", "B"):
                    if case[parite]:
                        creneaux[(parite, jour, s)] = case[parite][0]
            # Une correction d'emploi du temps vaut aussi pendant un stage ou un CCF : elle décrit
            # la réalité de l'élève, pas une préférence de calcul. Elle porte sur l'identifiant du
            # cours, stable d'une semaine à l'autre, donc elle s'applique ici sans rien changer.
            creneaux, _ = appliquer_retouches(
                creneaux, (self.etat.get("retouches") or {}).get(eleve["id"]))
            creneaux = {cle: donnees for cle, donnees in creneaux.items()
                        if not self.motif_non_accompagne(eleve["id"], donnees)}
            if creneaux:
                grilles[eleve["id"]] = creneaux
            else:
                sans_cours.append(eleve["nom_complet"])
        return grilles, retenues, sans_cours

    def cours_obligatoires(self, periode=None, grilles=None):
        """Cours à couvrir impérativement : ceux des élèves en CCF pendant la période concernée."""
        if not periode or periode.get("type") != "ccf":
            return set()
        concernes = set(periode.get("eleves") or [])
        obligatoires = set()
        for id_eleve, creneaux in (grilles or {}).items():
            if id_eleve not in concernes:
                continue
            for (parite, _, _), cours in creneaux.items():
                obligatoires.add(f"{id_eleve}|{parite}|{cours['id_cours']}")
        return obligatoires

    def calculer_periode(self, identifiant, exigence="standard", journal=None):
        """Affectation propre à une période : redistribution des AESH libérés, CCF garantis."""
        periode = self.periode(identifiant)
        if not periode:
            raise ValueError("Période inconnue.")
        population = self.population()
        grilles, semaines, sans_cours = self.grilles_periode(periode, population)
        if not grilles:
            return {"statut": "SANS_DONNEES",
                    "message": "Aucun élève n'a cours pendant cette période — rien à affecter.",
                    "affectations": [], "eleves": [], "aesh": [], "non_couverts": [], "synthese": {}}

        desactives = set(self.etat.get("aesh_desactives", []))
        eleves = [{**e, "creneaux": grilles[e["id"]]} for e in population["eleves"] if e["id"] in grilles]
        aesh = [{**a, "dispo": self.disponibilites(a["id"])} for a in population["aesh"]
                if a["id"] not in desactives and self.disponibilites(a["id"])]
        if not aesh:
            return {"statut": "SANS_DISPONIBILITES",
                    "message": "Aucun AESH n'a de disponibilité déclarée.",
                    "affectations": [], "eleves": [], "aesh": [], "non_couverts": [], "synthese": {}}

        resultat = resoudre(Probleme(
            eleves, aesh, self.etat.get("efforts"), self.etat.get("affinites"),
            self.etat.get("paires"), self.referentiel.famille,
            poids=self.etat.get("poids"), max_mutualise=self.etat.get("max_mutualise", 2),
            mutualisation=self.etat.get("mutualisation"),
            paires_eleves=self.etat.get("paires_eleves"),
            max_aesh_par_eleve=self.etat.get("max_aesh_par_eleve", 3),
            pause=self.etat.get("pause"), h_min=(self.etat.get("plage") or PLAGE_DEFAUT)[0],
            cours_obligatoires=self.cours_obligatoires(periode, grilles)),
            exigence=exigence, journal=journal)
        resultat["calcule_le"] = maintenant()
        resultat["periode"] = {
            **periode, "semaines": semaines,
            "absents": [e["nom_complet"] for e in population["eleves"]
                        if e["id"] in set(periode.get("eleves") or [])
                        and periode.get("type") != "ccf"],
            # Un élève peut n'avoir aucun cours sur ces semaines simplement parce que son export
            # ProNote ne les couvre pas : il faut le distinguer d'une absence réelle.
            "sans_emploi_du_temps": sans_cours}
        self.etat.setdefault("resultats_periodes", {})[identifiant] = resultat
        self.enregistrer()
        return resultat

    # ───────────────────────────── Calcul ─────────────────────────────

    def calculer(self, exigence="standard", journal=None):
        population = self.population()
        grilles, _, _ = self.grilles(population)
        if not grilles:
            return {"statut": "SANS_DONNEES",
                    "message": "Aucun emploi du temps exploitable : importez les exports ProNote "
                               "et choisissez les deux semaines types.",
                    "affectations": [], "eleves": [], "aesh": [], "non_couverts": []}

        desactives = set(self.etat.get("aesh_desactives", []))
        eleves = [{**e, "creneaux": grilles[e["id"]]} for e in population["eleves"] if e["id"] in grilles]
        aesh = []
        for a in population["aesh"]:
            if a["id"] in desactives:
                continue
            dispo = self.disponibilites(a["id"])
            if dispo:
                aesh.append({**a, "dispo": dispo})
        if not aesh:
            return {"statut": "SANS_DISPONIBILITES",
                    "message": "Aucun AESH n'a de disponibilité déclarée : renseignez-les dans "
                               "l'onglet « AESH », ou importez le classeur de recueil rempli.",
                    "affectations": [], "eleves": [], "aesh": [], "non_couverts": []}

        precedent = {}
        for a in (self.etat.get("resultat") or {}).get("affectations", []):
            precedent[f"{a['aesh']}|{a['eleve']}|{a['parite']}|{a['jour']}|{a['creneau']}"] = True

        resultat = resoudre(Probleme(
            eleves, aesh, self.etat.get("efforts"), self.etat.get("affinites"),
            self.etat.get("paires"), self.referentiel.famille,
            poids=self.etat.get("poids"), max_mutualise=self.etat.get("max_mutualise", 2),
            precedent=precedent, mutualisation=self.etat.get("mutualisation"),
            paires_eleves=self.etat.get("paires_eleves"),
            max_aesh_par_eleve=self.etat.get("max_aesh_par_eleve", 3),
            pause=self.etat.get("pause"), cours_imposes=self.etat.get("cours_imposes"),
            h_min=(self.etat.get("plage") or PLAGE_DEFAUT)[0],
            cours_obligatoires=self.cours_obligatoires()), exigence=exigence, journal=journal)
        resultat["calcule_le"] = maintenant()
        self.etat["resultat"] = resultat
        self.etat["resultat_perime"] = False
        self.enregistrer()
        return resultat


# ───────────────────────────── Gestion des projets ─────────────────────────────

def lister_projets():
    DOSSIER_PROJETS.mkdir(parents=True, exist_ok=True)
    projets = []
    for dossier in sorted(DOSSIER_PROJETS.iterdir()):
        fichier = dossier / "projet.json"
        if not fichier.is_dir() and fichier.exists():
            try:
                etat = json.loads(fichier.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                etat = {"nom": dossier.name, "modifie_le": "?"}
            projets.append({"nom": dossier.name, "dossier": str(dossier),
                            "modifie_le": etat.get("modifie_le", ""),
                            **resume_projet(dossier.name)})
    return sorted(projets, key=lambda p: p["modifie_le"], reverse=True)


# Le fichier de projet, seul, contient tout le travail : établissement, semaines types, efforts,
# affinités, disponibilités, règles, pondérations, appariements forcés et dernier résultat. Les
# exports ProNote ne sont que de la matière première réimportable, d'où les deux modes ci-dessous.
EXTENSIONS_REGLAGES = {".json", ".ods", ".xlsx", ".xlsm"}


def nom_de_dossier(nom):
    """
    Nom de dossier sûr pour un projet.

    Un seul endroit décide de cette transformation : l'import et l'ouverture doivent aboutir au
    même dossier, faute de quoi un projet importé sous un nom contenant une parenthèse s'ouvre
    dans un dossier vide créé à côté.
    """
    propre = "".join(c for c in (nom or "").strip() if c.isalnum() or c in " -_")
    return re.sub(r"\s+", " ", propre).strip() or "Projet"


def nom_disponible(nom):
    """Variante libre du nom demandé : « Projet », « Projet 2 », « Projet 3 »…"""
    base = nom_de_dossier(nom)
    candidat, n = base, 2
    while (DOSSIER_PROJETS / candidat / "projet.json").exists():
        candidat, n = nom_de_dossier(f"{base} {n}"), n + 1
    return candidat


def exporter_projet(nom, complet=False):
    """
    Archive .zip d'un projet, écrite dans son dossier « sorties ».

    Par défaut on n'emporte que les réglages et le fichier PIAL — moins d'un mégaoctet, ce qui
    circule par courriel. « complet » ajoute les exports ProNote importés, soit plusieurs centaines
    de mégaoctets : utile pour rejouer le projet à l'identique sur un autre poste, inutile si les
    exports sont disponibles par ailleurs.
    """
    dossier = (DOSSIER_PROJETS / nom).resolve()
    if dossier.parent != DOSSIER_PROJETS.resolve() or not (dossier / "projet.json").exists():
        raise ValueError(f"Projet introuvable : {nom}")
    sorties = dossier / "sorties"
    sorties.mkdir(exist_ok=True)
    suffixe = "complet" if complet else "reglages"
    archive = sorties / f"Projet_{re.sub(r'[^A-Za-z0-9_-]+', '_', nom)}_{suffixe}_" \
                        f"{datetime.now():%Y%m%d_%H%M%S}.zip"

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zip_:
        for fichier in sorted(dossier.rglob("*")):
            if not fichier.is_file() or fichier == archive:
                continue
            relatif = fichier.relative_to(dossier)
            if relatif.parts[0] == "sorties":
                continue                                  # les sorties se régénèrent
            if not complet and fichier.suffix.lower() not in EXTENSIONS_REGLAGES:
                continue
            zip_.write(fichier, relatif)
        zip_.writestr("LISEZ-MOI.txt",
                      f"Projet « {nom} » — archive {suffixe}\n"
                      f"exportée le {datetime.now():%d/%m/%Y à %H:%M}\n\n"
                      + ("Contient les réglages ET les exports ProNote : le projet se rouvre tel quel.\n"
                         if complet else
                         "Contient les réglages et le fichier PIAL, mais PAS les exports ProNote (.ics),\n"
                         "trop volumineux. Après import, redéposez-les à l'étape « Import » : les\n"
                         "appariements et tout le travail sont conservés.\n")
                      + "\nPour réimporter : écran « Projet » de l'application, zone « Importer un projet ».\n")
    return archive


def chemin_sur(relatif):
    """
    Chemin relatif nettoyé, ou None s'il cherche à sortir du dossier de destination.

    Une archive ou un dossier déposé vient de l'extérieur : on n'écrit jamais un chemin absolu
    ni un « .. » venus de là.
    """
    morceaux = [m for m in Path(str(relatif).replace("\\", "/")).parts
                if m not in ("", ".", "/") and not m.endswith(":")]
    if any(m == ".." for m in morceaux) or not morceaux:
        return None
    return Path(*morceaux)


def _deballer_archive(chemin_zip, destination):
    """Extrait une archive de projet. Retourne le contenu de projet.json."""
    with zipfile.ZipFile(chemin_zip) as zip_:
        interne = {chemin_sur(n): n for n in zip_.namelist() if chemin_sur(n)}
        racine = next((sur for sur in interne if sur.name == "projet.json"), None)
        if racine is None:
            raise ValueError("Cette archive ne contient pas de fichier « projet.json » : "
                             "ce n'est pas un projet exporté par l'application.")
        # L'archive peut avoir été recompressée avec un dossier englobant : on s'aligne dessus.
        prefixe = racine.parent
        etat = json.loads(zip_.read(interne[racine]).decode("utf-8"))
        for sur, brut in interne.items():
            if brut.endswith("/"):
                continue
            try:
                relatif = sur.relative_to(prefixe)
            except ValueError:
                continue
            cible = destination / relatif
            cible.parent.mkdir(parents=True, exist_ok=True)
            cible.write_bytes(zip_.read(brut))
    return etat


def importer_projet(source, nom=None, fichiers=None):
    """
    Recrée un projet, à partir d'une archive .zip **ou** d'un dossier de projet déposé tel quel.

    Les navigateurs décompressent parfois les archives au téléchargement : l'utilisateur se retrouve
    avec un dossier et non un .zip. Refuser ce dossier serait lui reprocher un réglage de son
    navigateur, on l'accepte donc aussi. « fichiers » est alors une liste (chemin relatif, contenu).
    """
    destination = None
    try:
        if fichiers is not None:
            entrees = [(chemin_sur(c), contenu) for c, contenu in fichiers]
            entrees = [(c, contenu) for c, contenu in entrees if c]
            racine = next((c for c, _ in entrees if c.name == "projet.json"), None)
            if racine is None:
                raise ValueError("Le dossier déposé ne contient pas de fichier « projet.json » : "
                                 "ce n'est pas un projet exporté par l'application.")
            prefixe = racine.parent
            etat = json.loads(next(contenu for c, contenu in entrees if c == racine).decode("utf-8"))
            nom = nom_disponible(nom or etat.get("nom") or (prefixe.name if prefixe.parts else "Projet"))
            destination = DOSSIER_PROJETS / nom
            destination.mkdir(parents=True)
            for chemin, contenu in entrees:
                try:
                    relatif = chemin.relative_to(prefixe)
                except ValueError:
                    continue
                cible = destination / relatif
                cible.parent.mkdir(parents=True, exist_ok=True)
                cible.write_bytes(contenu)
        else:
            with zipfile.ZipFile(source) as zip_:
                racine = next((chemin_sur(n) for n in zip_.namelist()
                               if chemin_sur(n) and chemin_sur(n).name == "projet.json"), None)
                if racine is None:
                    raise ValueError("Cette archive ne contient pas de fichier « projet.json » : "
                                     "ce n'est pas un projet exporté par l'application.")
                etat = json.loads(zip_.read(
                    next(n for n in zip_.namelist()
                         if chemin_sur(n) and chemin_sur(n).name == "projet.json")).decode("utf-8"))
            nom = nom_disponible(nom or etat.get("nom") or Path(source).stem)
            destination = DOSSIER_PROJETS / nom
            destination.mkdir(parents=True)
            _deballer_archive(source, destination)
    except Exception:
        if destination and destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        raise

    projet = Projet(destination)
    projet.etat["nom"] = nom
    pial, ics = recaler_chemins(projet)
    return nom, pial, ics


def recaler_chemins(projet):
    """
    Refait pointer le projet sur ses propres fichiers.

    Les chemins enregistrés désignent le poste d'origine ; après un import ils ne veulent plus rien
    dire. On les reconstruit à partir du contenu réellement présent — ce qui permet aussi d'appeler
    cette fonction quand les fichiers arrivent après la création du projet.
    """
    ancien = projet.etat.get("fichier_pial")
    candidat = projet.dossier / "sources" / Path(ancien).name if ancien else None
    if candidat is None or not candidat.exists():
        classeurs = sorted((projet.dossier / "sources").glob("*.ods")) \
                    + sorted((projet.dossier / "sources").glob("*.xlsx"))
        candidat = classeurs[0] if classeurs else None
    projet.etat["fichier_pial"] = str(candidat) if candidat else None
    dossier_ics = projet.dossier / "sources" / "ics"
    ics = len(list(dossier_ics.glob("*.ics"))) if dossier_ics.is_dir() else 0
    projet.etat["sources_ics"] = [str(dossier_ics)] if ics else []
    projet.enregistrer()
    return bool(projet.etat["fichier_pial"]), ics


def ouvrir_dans_explorateur(nom=None):
    """Ouvre le dossier des projets (ou celui d'un projet) dans l'explorateur de fichiers du poste."""
    cible = DOSSIER_PROJETS if not nom else (DOSSIER_PROJETS / nom_de_dossier(nom))
    cible.mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("win"):
        os.startfile(cible)                                     # noqa: S606 — chemin construit par nous
    elif sys.platform == "darwin":
        subprocess.run(["open", str(cible)], check=False)
    else:
        subprocess.run(["xdg-open", str(cible)], check=False)
    return cible


CORBEILLE = ".corbeille"


def supprimer_projet(nom):
    """
    Retire un projet de la liste, en le déplaçant dans une corbeille au lieu de l'effacer.

    Un projet représente des heures de travail et des fichiers qu'on n'a pas toujours ailleurs.
    Une suppression définitive et immédiate est une mauvaise idée : le dossier part dans
    « .corbeille », horodaté, d'où il peut être ressorti à la main. Retourne l'emplacement.

    On n'accepte qu'un nom de projet existant, résolu sous DOSSIER_PROJETS : impossible de faire
    sortir la suppression de ce dossier, même avec un nom fabriqué.
    """
    cible = (DOSSIER_PROJETS / nom_de_dossier(nom)).resolve()
    if cible.parent != DOSSIER_PROJETS.resolve() or not (cible / "projet.json").exists():
        raise ValueError(f"Projet introuvable : {nom}")
    corbeille = DOSSIER_PROJETS / CORBEILLE
    corbeille.mkdir(parents=True, exist_ok=True)
    destination = corbeille / f"{cible.name}_{datetime.now():%Y%m%d_%H%M%S}"
    shutil.move(str(cible), str(destination))
    return destination


def resume_projet(nom):
    """Quelques chiffres sur un projet, pour que la liste dise à quoi on a affaire."""
    fichier = DOSSIER_PROJETS / nom / "projet.json"
    try:
        etat = json.loads(fichier.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    dossier_ics = DOSSIER_PROJETS / nom / "sources" / "ics"
    dispos = sum(1 for g in (etat.get("dispos") or {}).values()
                 if any(any(ligne) for ligne in lignes_dispos(g)))
    resultat = etat.get("resultat") or {}
    return {
        "etablissement": etat.get("etablissement"),
        "pial": Path(etat["fichier_pial"]).name if etat.get("fichier_pial") else None,
        "ics": len(list(dossier_ics.glob("*.ics"))) if dossier_ics.is_dir() else 0,
        "semaines": etat.get("semaines_types") or [],
        "plage": etat.get("plage"),
        "aesh_renseignes": dispos,
        "calcule": bool(resultat.get("affectations")),
        "taux": (resultat.get("synthese") or {}).get("taux_global"),
        "cree_le": etat.get("cree_le", ""),
    }


def ouvrir_projet(nom):
    return Projet(DOSSIER_PROJETS / nom_de_dossier(nom))
