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

import traceback
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from . import export
from .affectation import POIDS_DEFAUT, REGLES_DURES, REGLES_SOUPLES
from .matieres import EFFORTS_PAR_DEFAUT, FAMILLES, NON_CLASSE
from .projet import DOSSIER_PROJETS, lister_projets, ouvrir_projet, supprimer_projet
from .pronote import JOURS, PAS_MINUTES

RACINE_STATIQUE = Path(__file__).resolve().parent / "static"
EXTENSIONS_CLASSEUR = {".ods", ".xlsx", ".xlsm"}

application = Flask(__name__, static_folder=None)
# Un export ProNote d'année entière pèse ~370 Ko par élève : un PIAL complet dépasse facilement
# le millier de fichiers. Les deux plafonds comptent — celui des octets ET celui du nombre de
# parties du formulaire (1000 par défaut), qui est le premier atteint.
application.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024
application.config["MAX_FORM_PARTS"] = 5000
application.config["MAX_FORM_MEMORY_SIZE"] = 64 * 1024 * 1024
_courant = {"projet": None}


def projet_courant():
    if _courant["projet"] is None:
        raise Erreur("Aucun projet ouvert. Créez-en un ou ouvrez-en un depuis l'écran d'accueil.")
    return _courant["projet"]


class Erreur(Exception):
    """Erreur destinée à l'utilisateur : le message est affiché tel quel dans l'interface."""


@application.errorhandler(Erreur)
def _erreur_metier(e):
    return jsonify({"erreur": str(e)}), 400


@application.errorhandler(Exception)
def _erreur_inattendue(e):
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
    return jsonify({"projets": lister_projets(), "dossier": str(DOSSIER_PROJETS)})


@application.post("/api/projets")
def api_ouvrir_projet():
    nom = (request.json or {}).get("nom", "").strip()
    if not nom:
        raise Erreur("Donnez un nom au projet (par exemple « Calanques-2 2026-2027 »).")
    _courant["projet"] = ouvrir_projet(nom)
    return jsonify(api_etat().json)


@application.delete("/api/projets/<nom>")
def api_supprimer_projet(nom):
    try:
        supprimer_projet(nom)
    except ValueError as e:
        raise Erreur(str(e))
    if _courant["projet"] is not None and _courant["projet"].dossier.name == nom:
        _courant["projet"] = None
    return jsonify({"ok": True})


@application.get("/api/etat")
def api_etat():
    if _courant["projet"] is None:
        return jsonify({"ouvert": False, "familles": FAMILLES, "jours": JOURS,
                        "pas_minutes": PAS_MINUTES, "poids_defaut": POIDS_DEFAUT, "efforts_defaut": EFFORTS_PAR_DEFAUT,
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
    projet = projet_courant()
    fichiers = [f for f in request.files.getlist("fichiers")
                if Path(f.filename).suffix.lower() == ".ics"]
    if not fichiers:
        raise Erreur("Aucun fichier .ics reçu. Déposez les exports ProNote (un fichier par élève) "
                     "ou le dossier qui les contient.")
    dossier = projet.dossier / "sources" / "ics"
    dossier.mkdir(parents=True, exist_ok=True)
    remplaces, conserves = [], []
    for f in fichiers:
        cible = dossier / Path(f.filename).name
        contenu = f.read()
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
    index, ignores = projet.ajouter_sources_ics([dossier])
    return jsonify({"recus": len(fichiers), "indexes": len(index),
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
                "max_aesh_par_eleve", "appariements_forces"):
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
    secondes = int((request.json or {}).get("secondes", 30))
    resultat = projet.calculer(secondes=max(5, min(secondes, 300)))
    return jsonify(resultat)


@application.get("/api/resultat")
def api_resultat():
    return jsonify(projet_courant().etat.get("resultat") or {"statut": "JAMAIS_CALCULE"})


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
    elif format == "recueil":
        chemin = export.classeur_recueil(projet)
    else:
        raise Erreur(f"Format d'export inconnu : {format}")
    return send_from_directory(chemin.parent, chemin.name, as_attachment=True)


@application.get("/api/recueil")
def api_recueil():
    """Classeur de recueil des disponibilités, à envoyer aux AESH (un onglet par personne)."""
    projet = projet_courant()
    chemin = export.classeur_recueil(projet)
    return send_from_directory(chemin.parent, chemin.name, as_attachment=True)
