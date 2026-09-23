#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pronote.py — lecture des exports ProNote et construction de l'emploi du temps type.

Deux choses importantes s'y jouent.

1. **L'identifiant de cours.** Le champ UID d'un événement ICS ProNote a la forme
   « Cours-<id cours>-<n° séance>-<horodatage>-Index-Education ». Toutes les occurrences d'un même
   cours partagent cet <id cours> : c'est lui qui dit si deux séances sont le même cours, et non le
   libellé (deux cours de même matière, même professeur et même salle peuvent avoir des périodicités
   différentes — cas vérifié sur les données réelles).

2. **Les deux semaines types.** Un export d'année entière décrit un calendrier, pas un emploi du temps.
   Plutôt que de deviner une périodicité par vote majoritaire — ce qui produit des approximations —
   l'utilisateur choisit deux semaines de référence : un cours présent dans les deux a lieu toutes les
   semaines, un cours présent dans une seule a lieu une semaine sur deux. C'est exact par construction.
"""

import html
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pytz
from icalendar import Calendar

TZ = pytz.timezone("Europe/Paris")
JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"]
PAS_MINUTES = 30
RE_NOM_ICS = re.compile(r"^Calendrier_(.+)_(\d{2})(\d{2})(\d{4})\.ics$", re.IGNORECASE)
RE_UID_COURS = re.compile(r"Cours-(\d+)-")

# ProNote n'exporte ni les stages ni les CCF. En revanche il exporte, sous forme de cours ordinaires
# ou de catégories particulières, trois situations qui changent le besoin d'accompagnement :
RE_DISPENSE = re.compile(r"^\s*DISPENSE\b", re.IGNORECASE)          # présence facultative
RE_INTEGRATION = re.compile(r"INTEGRATION", re.IGNORECASE)           # journée d'intégration
CATEGORIE_SORTIE = "Sorties"                                          # sortie pédagogique


def compacter(texte):
    texte = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode()
    texte = texte.upper().replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", texte)).strip()


def similarite(a, b):
    import difflib
    return difflib.SequenceMatcher(None, compacter(a), compacter(b)).ratio()


def lundi_de(d):
    return d - timedelta(days=d.weekday())


# ───────────────────────────── Index des fichiers ─────────────────────────────

def collecter_ics(chemins):
    """Fichiers .ics contenus dans une liste de fichiers et/ou de dossiers, sans doublon."""
    fichiers, vus = [], set()
    for chemin in chemins:
        chemin = Path(chemin)
        candidats = sorted(chemin.rglob("*.ics")) if chemin.is_dir() else [chemin]
        for f in candidats:
            if f.suffix.lower() == ".ics" and f.resolve() not in vus:
                vus.add(f.resolve())
                fichiers.append(f)
    return fichiers


def indexer_ics(chemins):
    """
    Index des exports : nom, prénom (dernier segment), date de naissance lue dans le nom de fichier.
    Retourne (index, fichiers au nom non reconnu).
    """
    index, ignores = [], []
    for chemin in collecter_ics(chemins):
        m = RE_NOM_ICS.match(chemin.name)
        if not m:
            ignores.append(chemin.name)
            continue
        segments = m.group(1).split("_")
        nom = " ".join(segments[:-1]) if len(segments) > 1 else segments[0]
        try:
            dob = date(int(m.group(4)), int(m.group(3)), int(m.group(2)))
        except ValueError:
            ignores.append(chemin.name)
            continue
        index.append({"chemin": str(chemin), "nom": nom, "prenom": segments[-1],
                      "libelle": f"{nom} {segments[-1]}", "dob": dob})
    return index, ignores


def apparier(eleve, index, seuil=0.6):
    """
    (entrée ICS ou None, score, explication). La date de naissance est la clé ; le nom départage
    les homonymes de date et tolère les différences d'orthographe.
    """
    dob = eleve.get("dob")
    dob = date.fromisoformat(dob) if isinstance(dob, str) and dob else dob
    candidats = [i for i in index if dob and i["dob"] == dob]
    if candidats:
        meilleur = max(candidats, key=lambda i: similarite(eleve["nom_complet"], i["libelle"]))
        score = similarite(eleve["nom_complet"], meilleur["libelle"])
        if score >= seuil:
            return meilleur, score, ("date de naissance + nom"
                                     + (" (orthographe différente)" if score < 0.95 else ""))
        return None, score, f"même date de naissance mais nom trop différent ({meilleur['libelle']})"
    if index:
        meilleur = max(index, key=lambda i: similarite(eleve["nom_complet"], i["libelle"]))
        score = similarite(eleve["nom_complet"], meilleur["libelle"])
        if score >= 0.92:
            return meilleur, score, f"nom seul — DATE DE NAISSANCE DIFFÉRENTE ({meilleur['dob']}), à vérifier"
    return None, 0.0, "aucun emploi du temps dans les exports fournis"


# ───────────────────────────── Lecture d'un emploi du temps ─────────────────────────────

def _infos_description(texte):
    infos = {}
    for ligne in (texte or "").replace("\r", "").split("\n"):
        if " : " in ligne:
            cle, valeur = ligne.split(" : ", 1)
            infos[compacter(cle)] = html.unescape(valeur.strip())
    return infos


def _en_heure_paris(dt):
    return (pytz.utc.localize(dt) if dt.tzinfo is None else dt).astimezone(TZ)


def lire_ics(chemin):
    """
    (cours, journées entières, sorties pédagogiques).

    Chaque cours porte son identifiant ProNote (« id_cours ») et deux drapeaux lus dans le libellé :
    « dispense » (présence facultative) et « integration » (journée d'intégration). Les sorties
    pédagogiques sont retournées à part : ce ne sont pas des cours, mais elles occupent l'élève.
    """
    cal = Calendar.from_ical(Path(chemin).read_bytes())
    cours, journees, sorties = [], [], []
    for ev in cal.walk("VEVENT"):
        categorie = ev.get("categories")
        categorie = categorie.to_ical().decode("utf-8", "ignore") if categorie is not None else ""
        debut = ev.get("dtstart").dt
        fin = ev.get("dtend").dt if ev.get("dtend") is not None else debut
        resume = html.unescape(str(ev.get("summary", "")).strip())
        if not isinstance(debut, datetime):
            fin_incluse = fin - timedelta(days=1) if isinstance(fin, date) and fin > debut else debut
            journees.append({"categorie": categorie, "libelle": resume,
                             "debut": debut.isoformat(), "fin": fin_incluse.isoformat()})
            continue
        if not categorie.startswith("Cours"):
            if CATEGORIE_SORTIE in categorie:
                sorties.append({"debut": _en_heure_paris(debut), "fin": _en_heure_paris(fin),
                                "libelle": resume, "categorie": categorie})
            continue
        infos = _infos_description(str(ev.get("description", "")))
        uid = str(ev.get("uid", ""))
        m = RE_UID_COURS.match(uid)
        groupe = (infos.get("GROUPE") or infos.get("GROUPES")
                  or infos.get("PARTIE DE CLASSE") or infos.get("PARTIES DE CLASSE") or "")
        cours.append({
            "id_cours": m.group(1) if m else f"sans-id-{uid[:20]}",
            "debut": _en_heure_paris(debut), "fin": _en_heure_paris(fin),
            "matiere": infos.get("MATIERE") or resume.split(" - ")[0].strip(),
            "prof": infos.get("PROFESSEUR") or infos.get("PROFESSEURS") or "",
            "salle": infos.get("SALLE") or infos.get("SALLES")
                     or html.unescape(str(ev.get("location", "") or "")).strip(),
            "groupe": groupe,
            "classe": infos.get("CLASSE") or infos.get("CLASSES") or "",
            "precision": categorie[len("Cours"):].strip(" -"),
            # Présence facultative : l'élève peut ne pas venir, l'accompagner n'a pas de sens.
            "dispense": bool(RE_DISPENSE.match(resume)),
            # Journée d'intégration : exportée comme un cours exceptionnel, mais ce n'en est pas un.
            "integration": bool(RE_INTEGRATION.search(resume)),
        })
    cours.sort(key=lambda c: c["debut"])
    return cours, journees, sorties


def texte_cours(c, avec_prof=True):
    lignes = [c["matiere"]]
    if avec_prof and c["prof"]:
        lignes.append(c["prof"])
    details = c["salle"]
    if c["groupe"]:
        details = f"{details} ({c['groupe']})" if details else f"({c['groupe']})"
    if details:
        lignes.append(details)
    return "\n".join(lignes)


# ───────────────────────────── Semaines types ─────────────────────────────

def inventaire_semaines(tous_cours):
    """
    Par semaine ISO : nombre de séances, nombre d'élèves concernés, dates.
    Sert à proposer — et à faire choisir — les deux semaines de référence.
    """
    par_semaine = defaultdict(lambda: {"seances": 0, "eleves": set(), "lundi": None})
    for id_eleve, cours in tous_cours.items():
        for c in cours:
            jour = c["debut"].date() if hasattr(c["debut"], "date") else date.fromisoformat(c["debut"][:10])
            semaine = jour.isocalendar()[1]
            info = par_semaine[semaine]
            info["seances"] += 1
            info["eleves"].add(id_eleve)
            info["lundi"] = lundi_de(jour)
    resultat = []
    for semaine, info in sorted(par_semaine.items(), key=lambda kv: kv[1]["lundi"]):
        resultat.append({"semaine": semaine, "seances": info["seances"],
                         "eleves": len(info["eleves"]),
                         "lundi": info["lundi"].isoformat(),
                         "libelle": f"S{semaine} — du {info['lundi'].strftime('%d/%m')} au "
                                    f"{(info['lundi'] + timedelta(days=4)).strftime('%d/%m/%Y')}"})
    return resultat


def proposer_semaines_types(inventaire):
    """
    Deux semaines consécutives représentatives.

    Le critère qui compte d'abord est le **nombre d'élèves qui ont cours** ces deux semaines-là, et
    non le volume de séances : une semaine très fournie où deux élèves sont en stage laisserait ces
    élèves sans emploi du temps, donc sans accompagnement possible. Le volume ne sert qu'à départager
    les paires qui couvrent autant d'élèves, et l'écart entre les deux semaines à écarter les paires
    bancales (une pleine, une tronquée).
    """
    if not inventaire:
        return []
    if len(inventaire) == 1:
        return [inventaire[0]["semaine"]]
    meilleures, meilleur_score = None, None
    for a, b in zip(inventaire, inventaire[1:]):
        if (date.fromisoformat(b["lundi"]) - date.fromisoformat(a["lundi"])).days != 7:
            continue                                     # semaines réellement consécutives
        score = (min(a["eleves"], b["eleves"]),           # d'abord : personne laissé de côté
                 a["seances"] + b["seances"],             # ensuite : le plus de cours possible
                 -abs(a["seances"] - b["seances"]))       # enfin : deux semaines comparables
        if meilleur_score is None or score > meilleur_score:
            meilleures, meilleur_score = [a["semaine"], b["semaine"]], score
    if meilleures:
        return meilleures
    deux = sorted(inventaire, key=lambda s: (-s["eleves"], -s["seances"]))[:2]
    return sorted(s["semaine"] for s in deux)


def semaines_de_repli(cours, semaines_types):
    """
    Deux semaines de référence propres à un élève qui n'a aucun cours dans les semaines retenues
    pour tout le monde (stage, arrivée en cours d'année, absence longue).

    L'alternance reste alignée sur le reste de l'établissement : c'est la **parité du numéro de
    semaine ISO** qui décide si une semaine est « A » ou « B », donc la semaine A d'un élève tombe
    toujours la même semaine que celle de son AESH. Retourne None si l'élève n'a aucun cours.
    """
    par_semaine = defaultdict(int)
    for c in cours:
        jour = c["debut"].date() if hasattr(c["debut"], "date") else date.fromisoformat(c["debut"][:10])
        par_semaine[jour.isocalendar()[1]] += 1
    if not par_semaine:
        return None
    parite_a = semaines_types[0] % 2 if semaines_types else 1
    paires = [(s, s + 1) for s in sorted(par_semaine) if s + 1 in par_semaine]
    if paires:
        a, b = max(paires, key=lambda p: par_semaine[p[0]] + par_semaine[p[1]])
        return [a, b] if a % 2 == parite_a else [b, a]
    unique = max(par_semaine, key=par_semaine.get)
    return [unique, unique]


def creneau(moment, h_min, arrondi_sup=False):
    minutes = moment.hour * 60 + moment.minute
    if arrondi_sup and moment.hour == 0 and moment.minute == 0:
        minutes = 24 * 60
    brut = (minutes - h_min * 60) / PAS_MINUTES
    return math.ceil(brut) if arrondi_sup else math.floor(brut)


def grille_type(cours, semaines_types, h_min, h_max):
    """
    Emploi du temps type d'un élève : {(jour, créneau): {"A": [séances], "B": [séances]}}.

    Un cours présent dans les deux semaines de référence a lieu toutes les semaines ; présent dans
    une seule, il a lieu une semaine sur deux. Retourne aussi les cours écartés faute d'être dans
    l'une des deux semaines choisies, pour pouvoir le dire à l'utilisateur.
    """
    nb_creneaux = (h_max - h_min) * 60 // PAS_MINUTES
    semaine_a = semaines_types[0]
    semaine_b = semaines_types[1] if len(semaines_types) > 1 else semaines_types[0]

    par_cours = defaultdict(dict)
    hors_selection = 0
    for c in cours:
        jour = c["debut"].date() if hasattr(c["debut"], "date") else date.fromisoformat(c["debut"][:10])
        semaine = jour.isocalendar()[1]
        if semaine == semaine_a:
            par_cours[c["id_cours"]]["A"] = c
        elif semaine == semaine_b:
            par_cours[c["id_cours"]]["B"] = c
        else:
            hors_selection += 1

    grille, hors_grille = {}, []
    for identifiant, presences in par_cours.items():
        reference = presences.get("A") or presences.get("B")
        jour = reference["debut"].weekday()
        if jour >= len(JOURS):
            hors_grille.append(reference)
            continue
        parites = ["A", "B"] if len(presences) == 2 else list(presences)
        debut = max(creneau(reference["debut"], h_min), 0)
        fin = min(creneau(reference["fin"], h_min, arrondi_sup=True), nb_creneaux)
        for s in range(debut, fin):
            case = grille.setdefault((jour, s), {"A": [], "B": []})
            for parite in parites:
                case[parite].append(reference)
    return grille, hors_grille, hors_selection


def amplitude(tous_cours, defaut=(8, 18)):
    """Plage horaire couvrant les cours fournis, arrondie à l'heure."""
    debuts, fins = [], []
    for cours in tous_cours.values():
        for c in cours:
            debuts.append(c["debut"].hour)
            f = c["fin"]
            fins.append(24 if (f.hour == 0 and f.minute == 0) else math.ceil((f.hour * 60 + f.minute) / 60))
    if not debuts:
        return defaut
    return min(defaut[0], min(debuts)), min(24, max(defaut[1], max(fins)))
