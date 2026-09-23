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
import shutil
from collections import Counter, defaultdict
from itertools import combinations
from datetime import date, datetime
from pathlib import Path

from . import pronote as P
from .affectation import POIDS_DEFAUT, Probleme, resoudre
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


class Projet:
    def __init__(self, dossier):
        self.dossier = Path(dossier)
        self.dossier.mkdir(parents=True, exist_ok=True)
        (self.dossier / "sources").mkdir(exist_ok=True)
        self.chemin = self.dossier / "projet.json"
        self.etat = self._charger()
        self._cache_ics = {}

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
            self._cache_ics[chemin] = P.lire_ics(chemin)[0]
        return self._cache_ics[chemin]

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

    def grilles(self, population=None):
        """
        Emploi du temps type de chaque élève, selon les deux semaines choisies.

        Un élève sans aucun cours ces deux semaines-là (stage, arrivée tardive) n'est pas abandonné :
        on retombe sur ses deux semaines les plus fournies, en gardant l'alternance A/B alignée sur
        celle de l'établissement. Le repli est signalé, jamais silencieux.

        Retourne (grilles, heures hors plage, replis) où « replis » liste les élèves concernés.
        """
        population = population or self.population()
        h_min, h_max = self.etat.get("plage") or PLAGE_DEFAUT
        semaines = self.etat.get("semaines_types") or []
        grilles, hors_plage, replis = {}, 0, []
        if not semaines:
            return grilles, hors_plage, replis
        # Matières retirées de l'accompagnement : globalement (familles décochées) ou pour un élève
        # donné (effort mis à 0). Le retrait se fait ici, à la source : ces créneaux disparaissent de
        # l'emploi du temps à couvrir, donc du besoin de l'élève et du taux de couverture — sinon on
        # lui reprocherait éternellement des heures qu'on a nous-mêmes décidé de ne pas accompagner.
        exclues = set(self.etat.get("matieres_exclues") or [])
        efforts = self.etat.get("efforts") or {}
        referentiel = self.referentiel

        def accompagne(id_eleve, matiere):
            famille = referentiel.famille(matiere)
            if famille in exclues:
                return False
            return efforts.get(id_eleve, {}).get(famille) != 0
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
                    if case[parite] and accompagne(eleve["id"], case[parite][0]["matiere"]):
                        creneaux[(parite, jour, s)] = case[parite][0]
            grilles[eleve["id"]] = creneaux
            hors_plage += len(hors_grille)
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

    # ───────────────────────────── Calcul ─────────────────────────────

    def calculer(self, secondes=30, journal=None):
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
            max_aesh_par_eleve=self.etat.get("max_aesh_par_eleve", 3)), secondes=secondes, journal=journal)
        resultat["calcule_le"] = maintenant()
        self.etat["resultat"] = resultat
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


def supprimer_projet(nom):
    """
    Supprime définitivement un projet et tout ce qu'il contient.

    On n'accepte qu'un nom de projet existant, résolu sous DOSSIER_PROJETS : impossible de faire
    sortir la suppression de ce dossier, même avec un nom fabriqué.
    """
    cible = (DOSSIER_PROJETS / nom).resolve()
    if cible.parent != DOSSIER_PROJETS.resolve() or not (cible / "projet.json").exists():
        raise ValueError(f"Projet introuvable : {nom}")
    shutil.rmtree(cible)


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
    nom = "".join(c for c in (nom or "").strip() if c.isalnum() or c in " -_") or "Projet"
    return Projet(DOSSIER_PROJETS / nom)
