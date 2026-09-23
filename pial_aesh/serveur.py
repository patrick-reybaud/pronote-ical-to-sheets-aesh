#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
serveur.py — API locale de l'application.

L'application est un logiciel de bureau : le serveur n'écoute que sur 127.0.0.1 et ne sert qu'à
faire parler l'interface (dans le navigateur) et le calcul (en Python). Rien ne sort du poste, sauf
si l'utilisateur demande explicitement la création d'un classeur Google.

Toutes les réponses d'erreur sont des messages en français destinés à l'utilisateur final, pas des
traces techniques : c'est lui qui les lira.
"""

import logging
import time
import traceback
from pathlib import Path
from urllib.parse import quote

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from . import export
from . import tableau
from .affectation import POIDS_DEFAUT, REGLES_DURES, REGLES_SOUPLES, SANS_ACCOMPAGNEMENT
from .matieres import EFFORTS_PAR_DEFAUT, FAMILLES, NON_CLASSE
from .affectation import EXIGENCES
from .projet import (DOSSIER_PROJETS, Projet, exporter_projet, importer_projet,
                     lister_projets, ouvrir_dans_explorateur, ouvrir_projet,
                     supprimer_projet)
from .pronote import JOURS, PAS_MINUTES

RACINE_STATIQUE = Path(__file__).resolve().parent / "static"
EXTENSIONS_CLASSEUR = {".ods", ".xlsx", ".xlsm"}

application = Flask(__name__, static_folder=None)
# Un export ProNote d'année entière pèse ~370 Ko par élève : un PIAL complet dépasse facilement
# le millier de fichiers. Les deux plafonds comptent — celui des octets ET celui du nombre de
# parties du formulaire (1000 par défaut), qui est le premier atteint.
application.config["MAX_CONTENT_LENGTH"] = 2 * 1024 ** 3
application.config["MAX_FORM_PARTS"] = 5000
# Pas de plafond sur la mémoire de formulaire : les fichiers déposés sont écrits sur disque au fil
# de la lecture, et un plafond bas n'apportait qu'un risque d'échec en cours d'import.
application.config["MAX_FORM_MEMORY_SIZE"] = None
journal = logging.getLogger("pial.serveur")
_courant = {"projet": None}


def _fichier_pret(chemin):
    """
    Annonce un fichier fabriqué, au lieu de le renvoyer dans la foulée.

    Les routes d'export reconstruisent le fichier à chaque appel. Or le gestionnaire de
    téléchargement d'un navigateur redemande volontiers la même adresse — pour reprendre, pour
    vérifier, ou simplement parce qu'il refait la requête pour son propre compte. Il obtenait alors
    un fichier recalculé, de taille et d'empreinte différentes, et abandonnait : « Zéro ko sur
    145 ko — interrompu ».

    La fabrication renvoie donc l'adresse d'un fichier déjà écrit sur le disque, servi par
    « /api/telechargement/… » — une adresse stable, qu'on peut redemander autant de fois qu'on veut
    avec toujours les mêmes octets.
    """
    return jsonify({"projet": chemin.parent.parent.name, "fichier": chemin.name,
                    "octets": chemin.stat().st_size,
                    "adresse": f"/api/telechargement/{quote(chemin.parent.parent.name)}"
                               f"/{quote(chemin.name)}"})


@application.get("/api/telechargement/<projet>/<fichier>")
def api_telechargement(projet, fichier):
    """Sert un fichier déjà fabriqué, sans rien recalculer."""
    dossier = (DOSSIER_PROJETS / projet / "sorties").resolve()
    if DOSSIER_PROJETS.resolve() not in dossier.parents or not dossier.is_dir():
        raise Erreur("Ce fichier n'existe plus. Relancez l'export.")
    if not (dossier / fichier).is_file():
        raise Erreur("Ce fichier n'existe plus. Relancez l'export.")
    return send_from_directory(dossier, fichier, as_attachment=True)


def projet_courant():
    if _courant["projet"] is None:
        raise Erreur("Aucun projet ouvert. Créez-en un ou ouvrez-en un depuis l'écran d'accueil.")
    return _courant["projet"]


class Erreur(Exception):
    """Erreur destinée à l'utilisateur : le message est affiché tel quel dans l'interface."""


@application.errorhandler(Erreur)
def _erreur_metier(e):
    journal.warning("refus sur %s %s : %s", request.method, request.path, e)
    return jsonify({"erreur": str(e)}), 400


@application.errorhandler(HTTPException)
def _erreur_http(e):
    # Sans ceci, un 404 ressortait en « Erreur inattendue : NotFound » avec une trace complète :
    # le message affiché à l'utilisateur ne voulait rien dire, et le journal criait à tort.
    journal.info("refus %s sur %s %s", e.code, request.method, request.path)
    return jsonify({"erreur": f"{e.description} ({e.code})"}), e.code


@application.errorhandler(Exception)
def _erreur_inattendue(e):
    journal.exception("erreur inattendue sur %s %s", request.method, request.path)
    traceback.print_exc()
    return jsonify({"erreur": f"Erreur inattendue : {e.__class__.__name__} — {e}",
                    "detail": traceback.format_exc()[-1500:]}), 500


# ───────────────────────────── Pages ─────────────────────────────

@application.get("/")
def accueil():
    return send_from_directory(RACINE_STATIQUE, "index.html")


@application.get("/<path:fichier>")
def statique(fichier):
    return send_from_directory(RACINE_STATIQUE, fichier)


# ───────────────────────────── Projets ─────────────────────────────

@application.get("/api/projets")
def api_projets():
    from .projet import CORBEILLE
    corbeille = DOSSIER_PROJETS / CORBEILLE
    return jsonify({"projets": lister_projets(), "dossier": str(DOSSIER_PROJETS),
                    "corbeille": len(list(corbeille.iterdir())) if corbeille.is_dir() else 0})


@application.post("/api/projets")
def api_ouvrir_projet():
    nom = (request.json or {}).get("nom", "").strip()
    if not nom:
        raise Erreur("Donnez un nom au projet (par exemple « Calanques-2 2026-2027 »).")
    _courant["projet"] = ouvrir_projet(nom)
    return jsonify(api_etat().json)


@application.get("/api/projets/<nom>/export")
def api_exporter_projet(nom):
    complet = request.args.get("complet") in ("1", "true", "oui")
    try:
        archive = exporter_projet(nom, complet=complet)
    except ValueError as e:
        raise Erreur(str(e))
    return _fichier_pret(archive)


@application.post("/api/projets/importer")
def api_importer_projet():
    """
    Recrée un projet à partir d'une archive .zip ou d'un dossier de projet déposé tel quel.

    Les deux sont acceptés parce que certains navigateurs décompressent les archives au
    téléchargement : l'utilisateur récupère alors un dossier, et il n'y a aucune raison de le lui
    reprocher.
    """
    recus = request.files.getlist("fichiers")
    if not recus:
        raise Erreur("Rien n'a été déposé.")
    archives = [f for f in recus if Path(f.filename).suffix.lower() == ".zip"]
    depot = DOSSIER_PROJETS / ".import"
    depot.mkdir(parents=True, exist_ok=True)
    chemin = None
    try:
        if archives:
            chemin = depot / "archive.zip"
            chemin.write_bytes(archives[0].read())
            nom, pial, ics = importer_projet(chemin)
        else:
            fichiers = [(f.filename, f.read()) for f in recus]
            if not any(Path(c).name == "projet.json" for c, _ in fichiers):
                raise Erreur("Ce dossier ne contient pas de fichier « projet.json ». Déposez le "
                             "dossier du projet lui-même (celui qui contient projet.json), ou "
                             "l'archive .zip produite par « Exporter… ».")
            nom, pial, ics = importer_projet(None, fichiers=fichiers)
    except ValueError as e:
        raise Erreur(str(e))
    finally:
        if chemin:
            chemin.unlink(missing_ok=True)
    journal.info("projet importé : %s (PIAL %s, %d ICS)", nom, "oui" if pial else "non", ics)
    return jsonify({"nom": nom, "pial": pial, "ics": ics})


@application.post("/api/projets/<nom>/fichiers")
def api_ajouter_fichiers(nom):
    """
    Ajoute des fichiers dans un projet existant, en respectant leur chemin relatif.

    Sert à l'import d'un projet volumineux : le dossier déposé est envoyé en plusieurs fois, le
    premier envoi crée le projet à partir de projet.json, les suivants le remplissent. Sans cela,
    un dossier de deux mille fichiers passerait dans autant de lots dont un seul contiendrait
    projet.json — et tous les autres seraient refusés.
    """
    from .projet import chemin_sur, nom_de_dossier

    dossier = DOSSIER_PROJETS / nom_de_dossier(nom)
    if not (dossier / "projet.json").exists():
        raise Erreur(f"Projet introuvable : {nom}")
    recus = request.files.getlist("fichiers")
    prefixe = (request.args.get("prefixe") or "").strip("/")
    ecrits, ignores = 0, 0
    for f in recus:
        relatif = chemin_sur(f.filename)
        if relatif is None:
            ignores += 1
            continue
        if prefixe and relatif.parts and relatif.parts[0] == prefixe:
            relatif = relatif.relative_to(prefixe) if len(relatif.parts) > 1 else None
        if relatif is None:
            ignores += 1
            continue
        cible = dossier / relatif
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_bytes(f.read())
        ecrits += 1

    if request.args.get("dernier") in ("1", "true", "oui"):
        projet = ouvrir_projet(nom_de_dossier(nom))
        from .projet import recaler_chemins
        pial, ics = recaler_chemins(projet)
        journal.info("projet « %s » complété : %d fichiers, PIAL %s, %d ICS",
                     nom, ecrits, "oui" if pial else "non", ics)
        return jsonify({"ecrits": ecrits, "ignores": ignores, "pial": pial, "ics": ics, "fini": True})
    return jsonify({"ecrits": ecrits, "ignores": ignores, "fini": False})


@application.post("/api/dossier")
def api_ouvrir_dossier():
    """Ouvre le dossier de travail dans l'explorateur de fichiers du poste."""
    corps = request.json or {}
    cible = ouvrir_dans_explorateur(corps.get("projet"), corps.get("sous_dossier"))
    return jsonify({"dossier": str(cible)})


@application.delete("/api/projets/<nom>")
def api_supprimer_projet(nom):
    try:
        destination = supprimer_projet(nom)
    except ValueError as e:
        raise Erreur(str(e))
    if _courant["projet"] is not None and _courant["projet"].dossier.name == nom:
        _courant["projet"] = None
    journal.info("projet « %s » déplacé dans la corbeille : %s", nom, destination)
    return jsonify({"ok": True, "corbeille": str(destination)})


@application.get("/api/etat")
def api_etat():
    if _courant["projet"] is None:
        return jsonify({"ouvert": False, "familles": FAMILLES, "jours": JOURS,
                        "pas_minutes": PAS_MINUTES, "poids_defaut": POIDS_DEFAUT, "efforts_defaut": EFFORTS_PAR_DEFAUT,
                        "exigences": EXIGENCES, "types_periode": Projet.TYPES_PERIODE,
                        "regles_dures": REGLES_DURES, "regles_souples": REGLES_SOUPLES})
    projet = _courant["projet"]
    index, ignores = projet.index_ics()
    donnees = None
    try:
        donnees = projet.donnees_pial()
    except ValueError as e:
        raise Erreur(str(e))
    return jsonify({
        "ouvert": True, "nom": projet.etat["nom"], "dossier": str(projet.dossier),
        "etat": projet.etat, "familles": FAMILLES, "jours": JOURS, "pas_minutes": PAS_MINUTES,
        "poids_defaut": POIDS_DEFAUT, "efforts_defaut": EFFORTS_PAR_DEFAUT,
        "exigences": EXIGENCES, "types_periode": Projet.TYPES_PERIODE,
        "regles_dures": REGLES_DURES, "regles_souples": REGLES_SOUPLES,
        "pial": {"charge": bool(donnees),
                 "fichier": Path(projet.etat["fichier_pial"]).name if projet.etat.get("fichier_pial") else None,
                 "eleves": len(donnees["eleves"]) if donnees else 0,
                 "aesh": len(donnees["aesh"]) if donnees else 0,
                 "etablissements": donnees["etablissements"] if donnees else [],
                 "avertissements": donnees["avertissements"] if donnees else []},
        "ics": {"fichiers": len(index), "ignores": ignores[:20], "nb_ignores": len(ignores),
                "sources": projet.etat["sources_ics"]},
    })


# ───────────────────────────── Imports ─────────────────────────────

@application.post("/api/import/pial")
def api_import_pial():
    projet = projet_courant()
    fichiers = request.files.getlist("fichiers")
    classeurs = [f for f in fichiers if Path(f.filename).suffix.lower() in EXTENSIONS_CLASSEUR]
    if not classeurs:
        raise Erreur("Déposez le fichier de gestion du PIAL au format .ods ou .xlsx. "
                     f"Reçu : {', '.join(Path(f.filename).name for f in fichiers) or 'rien'}.")
    if len(classeurs) > 1:
        raise Erreur(f"Un seul fichier PIAL à la fois ({len(classeurs)} reçus).")
    chemin = projet.deposer(classeurs[0].filename, classeurs[0].read())
    try:
        donnees = projet.importer_pial(chemin)
    except ValueError as e:
        raise Erreur(str(e))
    return jsonify({"eleves": len(donnees["eleves"]), "aesh": len(donnees["aesh"]),
                    "etablissements": donnees["etablissements"],
                    "avertissements": donnees["avertissements"], "onglets": donnees["onglets"]})


@application.post("/api/import/ics")
def api_import_ics():
    """
    Reçoit un lot d'exports ProNote et les écrit dans le projet.

    L'import se fait par lots : l'interface en envoie plusieurs à la suite. Réindexer à chaque lot
    serait du travail refait autant de fois qu'il y a de lots, d'où le paramètre « dernier », qui
    ne déclenche l'indexation qu'à la fin. Chaque lot est tracé dans le journal : sans cela, un
    incident en cours d'import ne laisse rien à examiner.
    """
    debut = time.monotonic()
    projet = projet_courant()
    recus = request.files.getlist("fichiers")
    fichiers = [f for f in recus if Path(f.filename).suffix.lower() == ".ics"]
    if not fichiers:
        raise Erreur("Aucun fichier .ics reçu. Déposez les exports ProNote (un fichier par élève) "
                     "ou le dossier qui les contient.")
    dossier = projet.dossier / "sources" / "ics"
    dossier.mkdir(parents=True, exist_ok=True)
    remplaces, conserves, octets = [], [], 0
    for f in fichiers:
        cible = dossier / Path(f.filename).name
        contenu = f.read()
        octets += len(contenu)
        # Un même élève peut arriver par deux exports (par exemple un export de quelques semaines
        # puis un export d'année entière). On garde le plus complet — c'est-à-dire le plus gros —
        # au lieu d'écraser aveuglément, et on le dit.
        if cible.exists():
            if len(contenu) > cible.stat().st_size:
                remplaces.append(cible.name)
            else:
                conserves.append(cible.name)
                continue
        cible.write_bytes(contenu)

    dernier = request.args.get("dernier") in ("1", "true", "oui")
    if dernier:
        index, ignores = projet.ajouter_sources_ics([dossier])
    else:
        index, ignores = [], []
    total = len(list(dossier.glob("*.ics")))
    journal.info("import ICS : %d reçus, %.1f Mo, %d en tout, %.1f s%s",
                 len(fichiers), octets / 1e6, total, time.monotonic() - debut,
                 " (indexation)" if dernier else "")
    return jsonify({"recus": len(fichiers), "total": total,
                    "indexes": len(index) if dernier else total,
                    "ignores": ignores[:20], "nb_ignores": len(ignores),
                    "remplaces": len(remplaces), "conserves": len(conserves)})


@application.post("/api/import/dispos")
def api_import_dispos():
    """Réinjection du classeur de recueil rempli par les AESH (.xlsx/.ods, un onglet par personne)."""
    projet = projet_courant()
    fichiers = [f for f in request.files.getlist("fichiers")
                if Path(f.filename).suffix.lower() in EXTENSIONS_CLASSEUR]
    if not fichiers:
        raise Erreur("Déposez le classeur de recueil rempli (.xlsx ou .ods).")
    chemin = projet.deposer(fichiers[0].filename, fichiers[0].read())
    rapport = export.importer_recueil(projet, chemin)
    projet.enregistrer()
    return jsonify(rapport)


# ───────────────────────────── Paramètres ─────────────────────────────

@application.post("/api/parametres")
def api_parametres():
    projet = projet_courant()
    corps = request.json or {}
    if "plage" in corps:                 # passe par changer_plage : les disponibilités suivent
        projet.changer_plage(corps.pop("plage"))
    for cle in ("etablissement", "semaines_types", "max_mutualise", "heures_eleves",
                "poids", "efforts", "affinites", "paires", "corrections_matieres",
                "aesh_desactives", "mutualisation", "paires_eleves", "matieres_exclues",
                "max_aesh_par_eleve", "appariements_forces", "pause", "cours_imposes"):
        if cle in corps:
            projet.etat[cle] = corps[cle]
            if cle in ("etablissement", "semaines_types", "heures_eleves",
                       "appariements_forces", "matieres_exclues", "corrections_matieres"):
                projet.etat["resultat"] = None
    projet.enregistrer()
    return jsonify({"ok": True})


@application.get("/api/population")
def api_population():
    projet = projet_courant()
    population = projet.population()
    grilles, hors_plage, replis = projet.grilles(population)
    referentiel = projet.referentiel
    eleves = []
    for eleve in population["eleves"]:
        creneaux = grilles.get(eleve["id"], {})
        familles = sorted({referentiel.famille(c["matiere"]) for c in creneaux.values()})
        eleves.append({**{k: v for k, v in eleve.items() if k != "creneaux"},
                       "a_edt": eleve["id"] in grilles,
                       "heures_presence": round(len(creneaux) / 4, 2),
                       "familles": familles})
    # Une case de disponibilité vaut un créneau de PAS_MINUTES ; le total s'exprime en heures
    # par semaine, comme la quotité à laquelle l'utilisateur va le comparer.
    aesh = [{**a, "dispo_heures": round(len(projet.disponibilites(a["id"])) * PAS_MINUTES / 60, 2),
             "desactive": a["id"] in set(projet.etat.get("aesh_desactives", []))}
            for a in population["aesh"]]
    return jsonify({
        "eleves": eleves, "aesh": aesh, "appariement": population["appariement"],
        "semaines": population["semaines"], "hors_plage": hors_plage, "replis": replis,
        "amplitude": projet.amplitude_cours(population),
        "matieres": referentiel.inventaire(population["matieres"]),
        "non_classees": referentiel.non_classees(population["matieres"]),
        "familles_utilisees": sorted({referentiel.famille(m) for m in population["matieres"]}),
        "matieres_exclues": projet.etat.get("matieres_exclues") or [],
        "heures_retirees": projet.heures_retirees(population),
    })


@application.get("/api/candidats/<id_eleve>")
def api_candidats(id_eleve):
    """Fichiers ProNote proposables pour un élève — sert à forcer une association à la main."""
    projet = projet_courant()
    population = projet.population()
    eleve = next((e for e in population["eleves"] if e["id"] == id_eleve), None)
    if not eleve:
        raise Erreur("Élève introuvable dans l'établissement retenu.")
    recherche = request.args.get("q", "")
    return jsonify({"eleve": eleve["nom_complet"], "dob": eleve.get("dob_texte", ""),
                    "force": (projet.etat.get("appariements_forces") or {}).get(id_eleve),
                    "candidats": projet.candidats_ics(eleve, recherche)})


@application.get("/api/mutualisation")
def api_mutualisation():
    """Couples d'élèves partageant un cours, et réglages en vigueur — écran « Mutualisation »."""
    projet = projet_courant()
    population = projet.population()
    grilles, _, _ = projet.grilles(population)
    return jsonify({
        "couples": projet.opportunites_mutualisation(population, grilles),
        "eleves": [{"id": e["id"], "nom": e["nom_complet"], "type_aide": e["type_aide"],
                    "heures": e["heures"], "a_edt": e["id"] in grilles,
                    "mode": projet.etat.get("mutualisation", {}).get(e["id"], "auto")}
                   for e in population["eleves"]],
        "max_mutualise": projet.etat.get("max_mutualise", 2),
    })


@application.post("/api/semaines/proposer")
def api_proposer_semaines():
    """Recalcule la proposition automatique de semaines types (utile après un nouvel import)."""
    projet = projet_courant()
    population = projet.population()
    from .pronote import proposer_semaines_types
    proposition = proposer_semaines_types(population["semaines"])
    projet.etat["semaines_types"] = proposition
    projet.etat["resultat"] = None
    projet.enregistrer()
    return jsonify({"semaines_types": proposition})


@application.post("/api/plage/ajuster")
def api_ajuster_plage():
    """Cale la plage horaire sur les cours réellement suivis par les élèves notifiés."""
    projet = projet_courant()
    amplitude = projet.amplitude_cours()
    if not amplitude:
        raise Erreur("Aucun cours exploitable : importez les exports ProNote et choisissez les semaines types.")
    tout = (request.json or {}).get("tout")
    plage = ([amplitude["min_reel"], amplitude["max_reel"]] if tout
             else [amplitude["propose_min"], amplitude["propose_max"]])
    projet.changer_plage(plage)
    return jsonify({"plage": plage})


@application.post("/api/semaines/inverser")
def api_inverser_semaines():
    """
    Échange les rôles des deux semaines types.

    L'application sait avec certitude que deux semaines alternent, mais rien dans l'export ProNote ne
    dit laquelle l'établissement appelle « A » : c'est une convention locale. Ce bouton la règle.
    """
    projet = projet_courant()
    semaines = list(projet.etat.get("semaines_types") or [])
    if len(semaines) != 2:
        raise Erreur("Choisissez d'abord deux semaines types.")
    projet.etat["semaines_types"] = [semaines[1], semaines[0]]
    projet.etat["resultat"] = None
    projet.enregistrer()
    return jsonify({"semaines_types": projet.etat["semaines_types"]})


@application.get("/api/dispos/<id_aesh>")
def api_dispos(id_aesh):
    projet = projet_courant()
    h_min, h_max = projet.etat.get("plage") or (8, 18)
    nb = (h_max - h_min) * 60 // PAS_MINUTES
    return jsonify({"grille": projet.grille_disponibilites(id_aesh),
                    "h_min": h_min, "h_max": h_max, "nb_creneaux": nb})


@application.post("/api/dispos/<id_aesh>")
def api_definir_dispos(id_aesh):
    projet = projet_courant()
    projet.definir_disponibilites(id_aesh, (request.json or {}).get("grille") or [])
    return jsonify({"ok": True})


# ───────────────────────────── Calcul et publication ─────────────────────────────

@application.post("/api/calculer")
def api_calculer():
    projet = projet_courant()
    exigence = (request.json or {}).get("exigence", "standard")
    return jsonify(projet.calculer(exigence=exigence))


@application.get("/api/periodes")
def api_periodes():
    """Périodes déclarées (stages, journées d'intégration, CCF) et leur affectation propre."""
    projet = projet_courant()
    population = projet.population()
    resultats = projet.etat.get("resultats_periodes") or {}
    periodes = []
    for periode in projet.periodes():
        resultat = resultats.get(periode["id"]) or {}
        periodes.append({**periode, "semaines": projet.semaines_de(periode),
                         "calcule": bool(resultat.get("affectations")),
                         "synthese": resultat.get("synthese") or {}})
    return jsonify({"periodes": periodes, "types": Projet.TYPES_PERIODE,
                    "eleves": [{"id": e["id"], "nom": e["nom_complet"], "type_aide": e["type_aide"]}
                               for e in population["eleves"]]})


@application.get("/api/periodes/detecter")
def api_detecter_periodes():
    """Périodes candidates déduites des exports ProNote — propositions, jamais appliquées d'office."""
    projet = projet_courant()
    population = projet.population()
    noms = {e["id"]: e["nom_complet"] for e in population["eleves"]}
    propositions = []
    for p in projet.periodes_detectees(population):
        propositions.append({**p, "noms": [noms.get(i, i) for i in p["eleves"]]})
    return jsonify({"propositions": propositions})


@application.post("/api/periodes")
def api_enregistrer_periodes():
    projet = projet_courant()
    periodes = (request.json or {}).get("periodes")
    if periodes is None:
        raise Erreur("Aucune période transmise.")
    connus = {p["id"] for p in periodes if p.get("id")}
    projet.etat["periodes"] = periodes
    projet.etat["resultats_periodes"] = {k: v for k, v in (projet.etat.get("resultats_periodes") or {}).items()
                                         if k in connus}
    projet.enregistrer()
    return jsonify({"ok": True})


@application.post("/api/periodes/<identifiant>/calculer")
def api_calculer_periode(identifiant):
    projet = projet_courant()
    exigence = (request.json or {}).get("exigence", "standard")
    try:
        return jsonify(projet.calculer_periode(identifiant, exigence=exigence))
    except ValueError as e:
        raise Erreur(str(e))


@application.get("/api/resultat")
def api_resultat():
    return jsonify(projet_courant().etat.get("resultat") or {"statut": "JAMAIS_CALCULE"})


@application.get("/api/alternatives")
def api_alternatives():
    """Cours affectés et AESH qui pourraient les reprendre — écran des résultats."""
    projet = projet_courant()
    return jsonify({"cours": projet.alternatives_affectation(),
                    "imposes": projet.etat.get("cours_imposes") or {}})


@application.post("/api/imposer")
def api_imposer():
    """
    Verrouille un cours sur un AESH — ou sur personne — et laisse relancer le calcul.

    Un verrou est une décision, pas une préférence : le calcul suivant s'organisera autour, ou dira
    qu'il n'y arrive pas. Plusieurs cours peuvent être verrouillés d'un seul appel, ce qui permet de
    figer d'un geste tout ce qu'un élève a obtenu.
    """
    projet = projet_courant()
    corps = request.json or {}
    cles = corps.get("cours") or []
    if isinstance(cles, str):
        cles = [cles]
    if not cles:
        raise Erreur("Aucun cours indiqué.")
    id_aesh = corps.get("aesh")
    if id_aesh and id_aesh != SANS_ACCOMPAGNEMENT:
        connus = {a["id"] for a in projet.population()["aesh"]}
        if id_aesh not in connus:
            raise Erreur("Cet AESH ne fait pas partie de l'établissement retenu.")
    imposes = dict(projet.etat.get("cours_imposes") or {})
    for cle in cles:
        if id_aesh:
            imposes[cle] = id_aesh
        else:
            imposes.pop(cle, None)
    projet.etat["cours_imposes"] = imposes
    projet.perimer_resultat()
    projet.enregistrer()
    return jsonify({"cours_imposes": imposes, "resultat_perime": True})


@application.post("/api/verrous")
def api_verrous():
    """Verrouille ou libère d'un coup tout ce qu'un élève — ou tout le monde — a obtenu."""
    projet = projet_courant()
    corps = request.json or {}
    action, id_eleve = corps.get("action"), corps.get("eleve")
    resultat = projet.etat.get("resultat") or {}
    imposes = dict(projet.etat.get("cours_imposes") or {})
    if action == "verrouiller":
        if not resultat.get("affectations"):
            raise Erreur("Il n'y a rien à verrouiller : lancez d'abord un calcul.")
        for a in resultat["affectations"]:
            if id_eleve and a["eleve"] != id_eleve:
                continue
            imposes[f"{a['eleve']}|{a['parite']}|{a['id_cours']}"] = a["aesh"]
    elif action == "liberer":
        # Sans élève désigné, on libère tout : c'est le sens de « tout déverrouiller ».
        imposes = ({cle: v for cle, v in imposes.items() if cle.split("|", 1)[0] != id_eleve}
                   if id_eleve else {})
    else:
        raise Erreur("Action inconnue : indiquez « verrouiller » ou « liberer ».")
    projet.etat["cours_imposes"] = imposes
    projet.perimer_resultat()
    projet.enregistrer()
    return jsonify({"cours_imposes": imposes, "resultat_perime": True})


@application.get("/api/tableau/<vue>")
def api_tableau(vue):
    """Emplois du temps affichés à l'écran — côté élèves (modifiable) ou côté AESH (lecture)."""
    projet = projet_courant()
    resultat = projet.etat.get("resultat") or {}
    if vue == "eleves":
        return jsonify(tableau.tableau_eleves(projet, resultat))
    if vue == "aesh":
        return jsonify(tableau.tableau_aesh(projet, resultat))
    raise Erreur(f"Vue inconnue : {vue}")


@application.get("/api/cours")
def api_cours():
    """
    Un cours et les AESH qui pourraient s'en charger — ce qu'affiche le volet d'une case.

    La clé passe par la requête et non par le chemin : elle contient l'identifiant de l'élève tel
    que le fichier PIAL le donne, sur lequel on n'a aucune garantie de forme.
    """
    projet = projet_courant()
    cle = request.args.get("cle", "")
    for entree in projet.alternatives_affectation():
        if entree["cle"] == cle:
            return jsonify(entree)
    raise Erreur("Ce cours n'est plus dans l'emploi du temps. Rechargez l'écran.")


@application.post("/api/retouches")
def api_retouches():
    """Corrige l'emploi du temps d'un élève : déplacer, redimensionner, supprimer, ajouter."""
    projet = projet_courant()
    corps = request.json or {}
    id_eleve = corps.get("eleve")
    if not id_eleve:
        raise Erreur("Élève non précisé.")
    try:
        retour = projet.retoucher(id_eleve, corps.get("cles") or [], corps.get("action"),
                                  corps.get("valeurs"), corps.get("parites"))
    except ValueError as e:
        raise Erreur(str(e))
    projet.perimer_resultat()
    return jsonify({**retour, "resultat_perime": True})


@application.get("/api/export/<format>")
def api_export(format):
    projet = projet_courant()
    resultat = projet.etat.get("resultat")
    if not resultat or not resultat.get("affectations"):
        raise Erreur("Lancez d'abord un calcul : il n'y a pas encore d'affectation à exporter.")
    if format == "html":
        chemin = export.emplois_du_temps_html(projet, resultat)
    elif format == "xlsx":
        chemin = export.emplois_du_temps_xlsx(projet, resultat)
    elif format == "eleves":
        chemin = export.emplois_du_temps_eleves(projet, resultat)
    elif format == "eleves-xlsx":
        chemin = export.emplois_du_temps_eleves_xlsx(projet, resultat)
    elif format == "recueil":
        chemin = export.classeur_recueil(projet)
    else:
        raise Erreur(f"Format d'export inconnu : {format}")
    return _fichier_pret(chemin)


@application.get("/api/recueil")
def api_recueil():
    """Classeur de recueil des disponibilités, à envoyer aux AESH (un onglet par personne)."""
    projet = projet_courant()
    return _fichier_pret(export.classeur_recueil(projet))
