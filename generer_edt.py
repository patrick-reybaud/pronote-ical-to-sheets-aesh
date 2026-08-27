#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generer_edt.py — Emplois du temps des élèves notifiés (suivi AESH) à partir des exports ProNote.

Chaîne :
  <année>/Notif_*.ods (onglet "Besoins_élèves")   → liste des élèves à traiter
  <année>/**/Calendrier_NOM_Prenom_DDMMYYYY.ics   → appariement par date de naissance + nom
  grille interne 30 min, rendue par heure (cellule divisée quand il y a une demi-heure, comme ProNote)
  → aperçu HTML + rapport CSV dans <année>/sorties/
  --google → création d'un Google Sheet : onglet "Récap" + 1 onglet par élève

Usage :
  python generer_edt.py                                  # aperçu local uniquement
  python generer_edt.py --google                         # + création du Google Sheet
  python generer_edt.py --google --partager x@y.fr       # + partage du classeur (écriture)
  python generer_edt.py --annee 2027-2028                # autre dossier d'année

Semaines A/B : si les exports couvrent plusieurs semaines, l'alternance est détectée automatiquement
(cours différents entre semaines paires/impaires). L'étiquette "A"/"B" suit SEMAINE_A_REFERENCE
(numéro ISO d'une semaine A officielle) ; à défaut, les semaines ISO impaires sont étiquetées "A".
Rendu multi-semaines : chaque jour = 2 demi-colonnes « sem. A | sem. B » ; un cours identique toutes les
semaines occupe les deux (cellule large, bleue), un cours différent selon la semaine est écrit côte à côte
(deux cellules jaunes). Export d'une seule semaine : une colonne par jour, colonnes datées.
"""

import argparse
import csv
import difflib
import html
import math
import re
import sys
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pytz
from icalendar import Calendar

# ───────────────────────────── Configuration ─────────────────────────────

RACINE = Path(__file__).resolve().parent
ANNEE_DEFAUT = "2026-2027"
ONGLET_ELEVES = "Besoins_élèves"

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi"]  # weekday() 0..4 — ajouter "Samedi" si besoin
HEURE_MIN_DEFAUT = 7      # la plage est étendue automatiquement si des cours débordent
HEURE_MAX_DEFAUT = 19
PAS_MINUTES = 30

SEMAINE_A_REFERENCE = None   # ex. 36 → la semaine ISO 36 est une semaine "A" ; None → impaires = A
SEUIL_RELATIF = 0.5          # multi-semaines : un cours est "régulier" s'il apparaît ≥ 50 % des semaines de sa parité

TZ = pytz.timezone("Europe/Paris")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]
FICHIER_CREDENTIALS = RACINE / "credentials_oauth.json"
FICHIER_TOKEN = RACINE / "token.json"

# Couleurs (Google Sheets : composantes 0..1)
COULEUR_ENTETE = {"red": 0.85, "green": 0.85, "blue": 0.85}
COULEUR_COURS = {"red": 0.85, "green": 0.91, "blue": 0.98}
COULEUR_ALT = {"red": 1.0, "green": 0.95, "blue": 0.75}
COULEUR_BORDURE = {"red": 0.6, "green": 0.6, "blue": 0.6}
COULEUR_ABSENT = {"red": 0.98, "green": 0.85, "blue": 0.85}

LARGEUR_COL_HORAIRE = 110
LARGEUR_COL_JOUR = 210        # export d'une seule semaine : 1 colonne par jour
LARGEUR_DEMI_COL_JOUR = 135   # multi-semaines : 2 demi-colonnes par jour (sem. A | sem. B) → 270 px par jour
HAUTEUR_DEMI_LIGNE = 28       # hauteur (px) d'une demi-ligne dans Google Sheets / l'aperçu HTML → 1 h = 56 px
HAUTEUR_LIGNE_SOUS_TITRE = 34 # 2 lignes de texte (infos élève + légende)
TAILLE_POLICE_ALT = 8         # demi-colonnes A/B ; ramenée à 7 si le texte ne tient pas (estimation)

NB_LIGNES_ENTETE = 3  # titre, sous-titre, en-tête des colonnes


# ───────────────────────────── Utilitaires ─────────────────────────────

def normaliser(texte):
    """Majuscules, sans accents, sans ponctuation superflue — pour comparer des noms."""
    texte = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    texte = texte.upper().replace("-", " ").replace("_", " ")
    return re.sub(r"[^A-Z0-9 ]", " ", texte).strip()


def compacter(texte):
    return re.sub(r"\s+", " ", normaliser(texte))


def similarite(a, b):
    return difflib.SequenceMatcher(None, compacter(a), compacter(b)).ratio()


def parser_date_fr(texte):
    texte = (texte or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(texte, fmt).date()
        except ValueError:
            pass
    return None


def en_heure_paris(dt):
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(TZ)


def lundi_de(d):
    return d - timedelta(days=d.weekday())


# ───────────────────────────── Lecture de l'ODS ─────────────────────────────

NS_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
NS_TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"


def lire_onglet_ods(chemin, nom_onglet):
    """Retourne les lignes non vides d'un onglet ODS sous forme de listes de chaînes (sans dépendance externe)."""
    racine = ET.fromstring(zipfile.ZipFile(chemin).read("content.xml"))
    for table in racine.iter(f"{{{NS_TABLE}}}table"):
        if table.get(f"{{{NS_TABLE}}}name") != nom_onglet:
            continue
        lignes = []
        for ligne in table.iter(f"{{{NS_TABLE}}}table-row"):
            cellules = []
            for cellule in ligne:
                if cellule.tag not in (f"{{{NS_TABLE}}}table-cell", f"{{{NS_TABLE}}}covered-table-cell"):
                    continue
                repetition = int(cellule.get(f"{{{NS_TABLE}}}number-columns-repeated", "1"))
                texte = "\n".join("".join(p.itertext()) for p in cellule.iter(f"{{{NS_TEXT}}}p")).strip()
                cellules.extend([texte] * min(repetition, 60))
            while cellules and cellules[-1] == "":
                cellules.pop()
            if cellules:
                lignes.append(cellules)
        return lignes
    raise ValueError(f"Onglet {nom_onglet!r} introuvable dans {chemin.name}")


def lire_eleves(chemin_ods):
    """Liste des élèves de l'onglet Besoins_élèves. La classe 2026-2027 est dans la colonne REMARQUES."""
    lignes = lire_onglet_ods(chemin_ods, ONGLET_ELEVES)
    entetes = [compacter(h) for h in lignes[0]]

    def colonne(*motifs):
        for i, h in enumerate(entetes):
            if all(m in h for m in motifs):
                return i
        return None

    i_nom = colonne("NOM", "PRENOM")
    i_dob = colonne("DATE", "NAISSANCE")
    i_niveau = colonne("NIVEAU")
    i_type = colonne("TYPE")
    i_heures = colonne("HEURES")
    i_debut = colonne("DATE DEBUT")
    i_fin = colonne("DATE FIN")
    i_classe = colonne("REMARQUES")
    i_besoins = colonne("BESOINS")
    if i_nom is None or i_dob is None:
        raise ValueError(f"Colonnes NOM/Date naissance introuvables dans l'onglet {ONGLET_ELEVES!r} : {lignes[0]}")

    eleves = []
    for ligne in lignes[1:]:
        def val(i):
            return ligne[i].strip() if i is not None and i < len(ligne) else ""
        nom = val(i_nom)
        if not nom:
            continue
        eleves.append({
            "nom_complet": re.sub(r"\s+", " ", nom),
            "dob_texte": val(i_dob),
            "dob": parser_date_fr(val(i_dob)),
            "niveau": val(i_niveau),
            "type_aide": val(i_type).upper(),
            "heures": val(i_heures),
            "notif_debut": val(i_debut),
            "notif_fin": val(i_fin),
            "classe": val(i_classe),
            "besoins": val(i_besoins),
        })
    return eleves


# ───────────────────────────── Fichiers ICS ─────────────────────────────

RE_ICS = re.compile(r"^Calendrier_(.+)_(\d{2})(\d{2})(\d{4})\.ics$")


def indexer_ics(dossier):
    """Index des fichiers ICS : nom (gère les noms composés avec '_'), prénom = dernier segment, date de naissance."""
    index, ignores = [], []
    for chemin in sorted(dossier.rglob("*.ics")):
        m = RE_ICS.match(chemin.name)
        if not m:
            ignores.append(chemin.name)
            continue
        segments = m.group(1).split("_")
        prenom = segments[-1]
        nom = " ".join(segments[:-1]) if len(segments) > 1 else segments[0]
        try:
            dob = date(int(m.group(4)), int(m.group(3)), int(m.group(2)))
        except ValueError:
            dob = None
        index.append({"chemin": chemin, "nom": nom, "prenom": prenom, "libelle": f"{nom} {prenom}", "dob": dob})
    return index, ignores


def apparier(eleve, index):
    """Retourne (entrée ICS ou None, score, explication)."""
    candidats = [i for i in index if eleve["dob"] and i["dob"] == eleve["dob"]]
    if candidats:
        meilleur = max(candidats, key=lambda i: similarite(eleve["nom_complet"], i["libelle"]))
        score = similarite(eleve["nom_complet"], meilleur["libelle"])
        if score >= 0.6:
            return meilleur, score, "date de naissance + nom" + (" (orthographe différente)" if score < 0.95 else "")
        return None, score, f"même date de naissance mais nom trop différent ({meilleur['libelle']})"
    if index:
        meilleur = max(index, key=lambda i: similarite(eleve["nom_complet"], i["libelle"]))
        score = similarite(eleve["nom_complet"], meilleur["libelle"])
        if score >= 0.9:
            return meilleur, score, f"nom seul — DATE DE NAISSANCE DIFFÉRENTE ({meilleur['dob']}) à vérifier"
    return None, 0.0, "aucun fichier ICS correspondant"


def parser_description(texte):
    infos = {}
    for ligne in (texte or "").replace("\r", "").split("\n"):
        if " : " in ligne:
            cle, valeur = ligne.split(" : ", 1)
            infos[compacter(cle)] = html.unescape(valeur.strip())
    return infos


def lire_ics(chemin):
    """Retourne (cours, journees) : cours = événements 'Cours*' horodatés ; journees = événements journée entière."""
    cal = Calendar.from_ical(chemin.read_bytes())
    cours, journees = [], []
    for ev in cal.walk("VEVENT"):
        cat = ev.get("categories")
        cat = cat.to_ical().decode("utf-8", "ignore") if cat is not None else ""
        debut = ev.get("dtstart").dt
        fin = ev.get("dtend").dt if ev.get("dtend") is not None else debut
        resume = html.unescape(str(ev.get("summary", "")).strip())
        if not isinstance(debut, datetime):
            fin_incluse = fin - timedelta(days=1) if isinstance(fin, date) and fin > debut else debut
            journees.append({"categorie": cat, "libelle": resume, "debut": debut, "fin": fin_incluse})
            continue
        if not cat.startswith("Cours"):
            continue
        infos = parser_description(str(ev.get("description", "")))
        salle = infos.get("SALLE") or infos.get("SALLES") or html.unescape(str(ev.get("location", "") or "")).strip()
        groupe = (infos.get("GROUPE") or infos.get("GROUPES")
                  or infos.get("PARTIE DE CLASSE") or infos.get("PARTIES DE CLASSE") or "")
        cours.append({
            "debut": en_heure_paris(debut),
            "fin": en_heure_paris(fin),
            "matiere": infos.get("MATIERE") or resume,
            "prof": infos.get("PROFESSEUR") or infos.get("PROFESSEURS") or "",
            "salle": salle,
            "groupe": groupe,
            "precision": cat[len("Cours"):].strip(" -"),  # ex. "Remplacement", "Cours déplacé"
            "resume": resume,
        })
    cours.sort(key=lambda c: c["debut"])
    return cours, journees


def texte_cours(c):
    lignes = [c["matiere"]]
    if c["prof"]:
        lignes.append(c["prof"])
    details = c["salle"]
    if c["groupe"]:
        details = f"{details} ({c['groupe']})" if details else f"({c['groupe']})"
    if details:
        lignes.append(details)
    if c["precision"]:
        lignes.append(f"[{c['precision']}]")
    return "\n".join(lignes)


# ───────────────────────────── Grille horaire ─────────────────────────────

def creneau_debut(dt, h_min):
    return math.floor(((dt.hour * 60 + dt.minute) - h_min * 60) / PAS_MINUTES)


def creneau_fin(dt, h_min):
    minutes = dt.hour * 60 + dt.minute
    if dt.hour == 0 and dt.minute == 0:  # fin à minuit
        minutes = 24 * 60
    return math.ceil((minutes - h_min * 60) / PAS_MINUTES)


def heure_fin_arrondie(cours):
    """Heure entière (≤ 24) qui suit la fin du dernier cours de la liste."""
    fins = []
    for c in cours:
        f = c["fin"]
        fins.append(24 if (f.hour == 0 and f.minute == 0) else math.ceil((f.hour * 60 + f.minute) / 60))
    return min(24, max(fins)) if fins else HEURE_MAX_DEFAUT


def type_semaine(lundi, lundi_reference):
    return "A" if ((lundi - lundi_reference).days // 7) % 2 == 0 else "B"


def dominant(compteur, nb_semaines):
    if not compteur:
        return None
    texte, n = compteur.most_common(1)[0]
    if nb_semaines <= 1 or n >= max(1, math.ceil(SEUIL_RELATIF * nb_semaines)):
        return texte
    return None


def construire_grille(cours, h_min, h_max, lundi_reference):
    """
    Grille {(jour, créneau 30 min): contenu} avec contenu = ("T", texte) ou ("ALT", texte_A, texte_B).
    Retourne aussi les semaines vues par parité et les cours hors grille (jour non affiché).
    """
    nb_creneaux = (h_max - h_min) * 60 // PAS_MINUTES
    par_semaine = defaultdict(lambda: defaultdict(set))
    hors_grille = []
    for c in cours:
        jour = c["debut"].weekday()
        if jour >= len(JOURS):
            hors_grille.append(c)
            continue
        s0 = max(creneau_debut(c["debut"], h_min), 0)
        s1 = min(creneau_fin(c["fin"], h_min), nb_creneaux)
        for s in range(s0, s1):
            par_semaine[lundi_de(c["debut"].date())][(jour, s)].add(texte_cours(c))

    semaines = {"A": set(), "B": set()}
    occurrences = {"A": defaultdict(Counter), "B": defaultdict(Counter)}
    for lundi, cellules in par_semaine.items():
        t = type_semaine(lundi, lundi_reference)
        semaines[t].add(lundi)
        for cle, textes in cellules.items():
            occurrences[t][cle]["\n+ ".join(sorted(textes))] += 1

    grille = {}
    for jour in range(len(JOURS)):
        for s in range(nb_creneaux):
            a = dominant(occurrences["A"].get((jour, s)), len(semaines["A"]))
            b = dominant(occurrences["B"].get((jour, s)), len(semaines["B"]))
            if a and b and a != b:
                grille[(jour, s)] = ("ALT", a, b)
            elif a or b:
                grille[(jour, s)] = ("T", a or b)
    return grille, semaines, hors_grille


def compacter_texte(texte):
    return texte.replace("\n", " · ")


def texte_contenu(contenu, compact=False):
    """Texte d'une cellule (une colonne par jour) ; compact = bloc d'une seule demi-ligne → tout sur une ligne."""
    if contenu is None:
        return ""
    if contenu[0] == "T":
        return compacter_texte(contenu[1]) if compact else contenu[1]
    if compact:
        return f"A : {compacter_texte(contenu[1])} | B : {compacter_texte(contenu[2])}"
    return f"Sem. A : {contenu[1]}\n— — —\nSem. B : {contenu[2]}"


def texte_demi_colonne(texte, compact=False):
    """Texte d'une demi-colonne A ou B (plus dense) : matière sur sa ligne, puis « prof · salle (groupe) »."""
    lignes = texte.split("\n")
    if compact:
        return " · ".join(lignes)
    return "\n".join([lignes[0]] + ([" · ".join(lignes[1:])] if len(lignes) > 1 else []))


def texte_tient(texte, taille_police, largeur_px, hauteur_px):
    """Estimation grossière (rendu Google Sheets) : le texte replié tient-il dans une cellule largeur × hauteur ?"""
    px = taille_police * 1.33                 # points → pixels
    largeur_char, interligne = px * 0.62, px * 1.22
    nb_lignes = sum(max(1, math.ceil(len(l) * largeur_char / max(1, largeur_px - 6))) for l in texte.split("\n"))
    return nb_lignes * interligne <= hauteur_px - 4


def style_contenu(contenu, compact=False):
    if contenu is None:
        return "vide"
    base = "alt" if contenu[0] == "ALT" else "cours"
    return f"{base}_compact" if compact else base


def construire_onglet(titre, sous_titre, grille, h_min, h_max, dates_jours, scinder_ab=False):
    """
    Modèle d'un onglet : lignes (textes), fusions (r0, r1, c0, c1 — fin exclue), styles {(r, c): style},
    lignes_demi (lignes dont le bord supérieur est une demi-heure → trait pointillé), premiere_grille (index de
    la première ligne de la grille horaire).
    Quadrillage à l'heure : l'étiquette "8h - 9h" est fusionnée sur les 2 demi-lignes de l'heure ;
    granularité demi-heure : chaque heure = 2 lignes. Les cellules identiques consécutives d'une colonne
    sont fusionnées en un bloc (comme ProNote) ; un bloc d'une seule demi-ligne est écrit en compact.
    scinder_ab : chaque jour = 2 demi-colonnes « sem. A | sem. B » (sous-en-tête) ; un cours identique toutes les
    semaines est fusionné sur les deux, un cours différent selon la semaine est écrit côte à côte (A à gauche, B à droite).
    """
    nb_jours = len(JOURS)
    sous_cols = 2 if scinder_ab else 1
    nb_cols = 1 + nb_jours * sous_cols
    lignes, fusions, styles, lignes_demi = [], [], {}, []

    lignes.append([titre] + [""] * (nb_cols - 1))
    fusions.append((0, 1, 0, nb_cols))
    styles[(0, 0)] = "titre"
    lignes.append([sous_titre] + [""] * (nb_cols - 1))
    fusions.append((1, 2, 0, nb_cols))
    styles[(1, 0)] = "sous_titre"
    entete = ["Horaires"] + [""] * (nb_cols - 1)
    for j in range(nb_jours):
        entete[1 + j * sous_cols] = f"{JOURS[j]}{' ' + dates_jours[j] if dates_jours.get(j) else ''}"
        if sous_cols > 1:
            fusions.append((2, 3, 1 + j * sous_cols, 1 + (j + 1) * sous_cols))
    lignes.append(entete)
    for c in range(nb_cols):
        styles[(2, c)] = "entete"
    if scinder_ab:  # sous-en-tête « sem. A | sem. B » sous chaque jour ; « Horaires » fusionné sur les 2 lignes
        lignes.append([""] + ["sem. A", "sem. B"] * nb_jours)
        fusions.append((2, 4, 0, 1))
        styles[(3, 0)] = "entete"
        for c in range(1, nb_cols):
            styles[(3, c)] = "entete_ab"

    sous_pas = 60 // PAS_MINUTES  # demi-lignes par heure
    premiere = len(lignes)
    contenus = []  # par ligne de grille : contenu de chaque jour
    for h in range(h_min, h_max):
        r = len(lignes)
        for k in range(sous_pas):
            s = (h - h_min) * sous_pas + k
            lignes.append([f"{h}h - {h + 1}h" if k == 0 else ""] + [""] * (nb_cols - 1))
            styles[(r + k, 0)] = "horaire"
            for c in range(1, nb_cols):
                styles[(r + k, c)] = "vide"
            if k > 0:
                lignes_demi.append(r + k)
            contenus.append([grille.get((j, s)) for j in range(nb_jours)])
        fusions.append((r, r + sous_pas, 0, 1))

    # Blocs verticaux par jour
    for j in range(nb_jours):
        c0 = 1 + j * sous_cols
        r = 0
        while r < len(contenus):
            contenu = contenus[r][j]
            fin = r + 1
            while contenu is not None and fin < len(contenus) and contenus[fin][j] == contenu:
                fin += 1
            if contenu is not None:
                compact = (fin - r) == 1
                r0, r1 = premiere + r, premiere + fin
                if scinder_ab and contenu[0] == "ALT":
                    # Cours différent selon la semaine : demi-colonne A | demi-colonne B, côte à côte
                    hauteur = (fin - r) * HAUTEUR_DEMI_LIGNE
                    for k in (0, 1):
                        texte = texte_demi_colonne(contenu[1 + k], compact)
                        lignes[r0][c0 + k] = texte
                        if compact:
                            styles[(r0, c0 + k)] = "alt_compact"
                        else:
                            styles[(r0, c0 + k)] = "alt" if texte_tient(texte, TAILLE_POLICE_ALT, LARGEUR_DEMI_COL_JOUR, hauteur) else "alt_petit"
                            fusions.append((r0, r1, c0 + k, c0 + k + 1))
                else:
                    lignes[r0][c0] = texte_contenu(contenu, compact)
                    styles[(r0, c0)] = style_contenu(contenu, compact)
                    if not compact or sous_cols > 1:
                        fusions.append((r0, r1, c0, c0 + sous_cols))
            r = fin
    return {"titre": titre, "lignes": lignes, "fusions": fusions, "styles": styles, "nb_cols": nb_cols,
            "lignes_demi": lignes_demi, "hauteur_ligne": HAUTEUR_DEMI_LIGNE, "premiere_grille": premiere}


# ───────────────────────────── Rendu HTML (aperçu local) ─────────────────────────────

CSS_HTML = """
body{font-family:-apple-system,Helvetica,Arial,sans-serif;font-size:12px;margin:20px;color:#222}
h1{font-size:20px} h2{font-size:16px;margin-top:40px;border-top:2px solid #999;padding-top:12px}
table{border-collapse:collapse;margin:8px 0;table-layout:fixed;border-bottom:1px solid #999}
td,th{border-left:1px solid #999;border-right:1px solid #999;border-top:1px solid #999;border-bottom:none;padding:2px 5px;vertical-align:middle;white-space:pre-line}
tr.demi td{border-top:1px dotted #bbb} tr.grille{height:__HAUTEUR__px} tr.grille td{overflow:hidden}
th{background:#ddd} th.entete_ab{background:#fff2bf;font-weight:normal;font-style:italic;font-size:10px}
td.horaire{font-weight:bold;text-align:center;background:#f4f4f4}
td.cours,td.cours_compact{background:#d9e8fa;text-align:center} td.alt,td.alt_petit,td.alt_compact{background:#fff2bf;text-align:center}
td.alt{font-size:11px} td.alt_petit{font-size:9.5px}
td.cours_compact,td.alt_compact{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:11px} td.alt_compact{font-size:9.5px}
td.titre{font-weight:bold;font-size:14px;background:#eee}
td.sous_titre{color:#555;background:#eee} td.absent{background:#fadada} .nav a{margin-right:12px}
"""


def rendre_html(onglets, titre_document):
    css = CSS_HTML.replace("__HAUTEUR__", str(HAUTEUR_DEMI_LIGNE))
    parties = [f"<!doctype html><html lang='fr'><head><meta charset='utf-8'><title>{html.escape(titre_document)}</title><style>{css}</style></head><body>"]
    parties.append(f"<h1>{html.escape(titre_document)}</h1><p class='nav'>")
    for i, o in enumerate(onglets):
        parties.append(f"<a href='#o{i}'>{html.escape(o['titre'])}</a> ")
    parties.append("</p>")
    for i, o in enumerate(onglets):
        largeurs = {}
        for (c0, c1, largeur) in o.get("largeurs", []):
            for c in range(c0, c1):
                largeurs[c] = largeur
        colonnes = [largeurs.get(c, 120) for c in range(o["nb_cols"])]
        parties.append(f"<h2 id='o{i}'>{html.escape(o['titre'])}</h2><table style='width:{sum(colonnes)}px'><colgroup>"
                       + "".join(f"<col style='width:{l}px'>" for l in colonnes) + "</colgroup>")
        premiere_grille = o.get("premiere_grille", NB_LIGNES_ENTETE)
        couvertes, spans = set(), {}
        for (r0, r1, c0, c1) in o["fusions"]:
            spans[(r0, c0)] = (r1 - r0, c1 - c0)
            for r in range(r0, r1):
                for c in range(c0, c1):
                    if (r, c) != (r0, c0):
                        couvertes.add((r, c))
        demi = set(o.get("lignes_demi", []))
        for r, ligne in enumerate(o["lignes"]):
            classe_tr = ""
            if o.get("hauteur_ligne") and r >= premiere_grille:
                classe_tr = " class='grille demi'" if r in demi else " class='grille'"
            parties.append(f"<tr{classe_tr}>")
            for c in range(o["nb_cols"]):
                if (r, c) in couvertes:
                    continue
                texte = html.escape(ligne[c] if c < len(ligne) else "")
                style = o["styles"].get((r, c), "")
                rs, cs = spans.get((r, c), (1, 1))
                attrs = (f" rowspan='{rs}'" if rs > 1 else "") + (f" colspan='{cs}'" if cs > 1 else "")
                balise = "th" if style in ("entete", "entete_ab") else "td"
                parties.append(f"<{balise} class='{style}'{attrs}>{texte}</{balise}>")
            parties.append("</tr>")
        parties.append("</table>")
    parties.append("</body></html>")
    return "".join(parties)


# ───────────────────────────── Google Sheets ─────────────────────────────

def authentifier_google():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if FICHIER_TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(FICHIER_TOKEN), SCOPES)
        if creds and creds.expired and creds.refresh_token:
            try:
                print("🔄 Rafraîchissement du jeton Google…")
                creds.refresh(Request())
            except Exception as e:  # refresh token périmé (appli OAuth en mode "Test" : 7 jours)
                print(f"   Jeton impossible à rafraîchir ({e.__class__.__name__}) → nouvelle authentification.")
                creds = None
    if not creds or not creds.valid:
        if not FICHIER_CREDENTIALS.exists():
            raise SystemExit(f"❌ {FICHIER_CREDENTIALS.name} introuvable — voir GUIDE_OAUTH2.md")
        print("🔐 Ouverture du navigateur pour l'authentification Google (compte à utiliser : celui du Drive cible)…")
        flow = InstalledAppFlow.from_client_secrets_file(str(FICHIER_CREDENTIALS), SCOPES)
        creds = flow.run_local_server(port=0)
    FICHIER_TOKEN.write_text(creds.to_json())
    return creds


FORMATS = {
    "base": {"wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE", "textFormat": {"fontSize": 9}},
    "titre": {"textFormat": {"bold": True, "fontSize": 13}, "verticalAlignment": "MIDDLE"},
    "sous_titre": {"wrapStrategy": "WRAP", "textFormat": {"italic": True, "fontSize": 9, "foregroundColor": {"red": 0.35, "green": 0.35, "blue": 0.35}}, "verticalAlignment": "MIDDLE"},
    "entete": {"textFormat": {"bold": True, "fontSize": 10}, "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "backgroundColor": COULEUR_ENTETE},
    "entete_ab": {"textFormat": {"italic": True, "fontSize": 8}, "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE", "backgroundColor": COULEUR_ALT},
    "horaire": {"textFormat": {"bold": True, "fontSize": 9}, "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"},
    "cours": {"wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE", "horizontalAlignment": "CENTER", "textFormat": {"fontSize": 9}, "backgroundColor": COULEUR_COURS},
    # demi-colonnes A/B (multi-semaines) : police réduite ; "alt_petit" quand le texte ne tiendrait pas
    "alt": {"wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE", "horizontalAlignment": "CENTER", "textFormat": {"fontSize": TAILLE_POLICE_ALT}, "backgroundColor": COULEUR_ALT},
    "alt_petit": {"wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE", "horizontalAlignment": "CENTER", "textFormat": {"fontSize": TAILLE_POLICE_ALT - 1}, "backgroundColor": COULEUR_ALT},
    "vide": {"wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE", "textFormat": {"fontSize": 9}},
    "absent": {"wrapStrategy": "WRAP", "verticalAlignment": "MIDDLE", "textFormat": {"fontSize": 9}, "backgroundColor": COULEUR_ABSENT},
    # blocs d'une seule demi-ligne : une ligne de texte, coupée si trop longue (pas de retour à la ligne)
    "cours_compact": {"wrapStrategy": "CLIP", "verticalAlignment": "MIDDLE", "horizontalAlignment": "CENTER", "textFormat": {"fontSize": 8}, "backgroundColor": COULEUR_COURS},
    "alt_compact": {"wrapStrategy": "CLIP", "verticalAlignment": "MIDDLE", "horizontalAlignment": "CENTER", "textFormat": {"fontSize": TAILLE_POLICE_ALT - 1}, "backgroundColor": COULEUR_ALT},
}


def titre_onglet_google(titre, deja_pris):
    t = re.sub(r"[\[\]\*\?/\\:]", " ", titre).strip()[:95] or "Sans nom"
    base, n = t, 2
    while t in deja_pris:
        t, n = f"{base} ({n})", n + 1
    deja_pris.add(t)
    return t


def requetes_onglet(sheet_id, onglet, largeurs, lignes_figees):
    lignes, nb_cols = onglet["lignes"], onglet["nb_cols"]
    rows = []
    for r, ligne in enumerate(lignes):
        valeurs = []
        for c in range(nb_cols):
            texte = ligne[c] if c < len(ligne) else ""
            fmt = FORMATS.get(onglet["styles"].get((r, c), "base"), FORMATS["base"])
            valeurs.append({"userEnteredValue": {"stringValue": texte}, "userEnteredFormat": fmt})
        rows.append({"values": valeurs})
    reqs = [{"updateCells": {"rows": rows, "fields": "userEnteredValue,userEnteredFormat",
                             "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0}}}]
    for (r0, r1, c0, c1) in onglet["fusions"]:
        reqs.append({"mergeCells": {"range": {"sheetId": sheet_id, "startRowIndex": r0, "endRowIndex": r1,
                                              "startColumnIndex": c0, "endColumnIndex": c1}, "mergeType": "MERGE_ALL"}})
    for (c0, c1, largeur) in largeurs:
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": c0, "endIndex": c1},
                                                   "properties": {"pixelSize": largeur}, "fields": "pixelSize"}})
    if onglet.get("bordures"):
        bord = {"style": "SOLID", "width": 1, "color": COULEUR_BORDURE}
        reqs.append({"updateBorders": {"range": {"sheetId": sheet_id, "startRowIndex": onglet["bordures"], "endRowIndex": len(lignes),
                                                 "startColumnIndex": 0, "endColumnIndex": nb_cols},
                                       "top": bord, "bottom": bord, "left": bord, "right": bord, "innerHorizontal": bord, "innerVertical": bord}})
        # Demi-heures : trait pointillé en haut de la 2e demi-ligne (invisible à l'intérieur des blocs fusionnés)
        pointille = {"style": "DOTTED", "width": 1, "color": COULEUR_BORDURE}
        for r in onglet.get("lignes_demi", []):
            reqs.append({"updateBorders": {"range": {"sheetId": sheet_id, "startRowIndex": r, "endRowIndex": r + 1,
                                                     "startColumnIndex": 0, "endColumnIndex": nb_cols}, "top": pointille}})
    if onglet.get("hauteur_ligne"):
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": onglet.get("premiere_grille", NB_LIGNES_ENTETE), "endIndex": len(lignes)},
                                                   "properties": {"pixelSize": onglet["hauteur_ligne"]}, "fields": "pixelSize"}})
    if onglet.get("hauteur_sous_titre"):
        reqs.append({"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 1, "endIndex": 2},
                                                   "properties": {"pixelSize": onglet["hauteur_sous_titre"]}, "fields": "pixelSize"}})
    if lignes_figees:
        # Lignes d'en-tête figées uniquement : figer une colonne est refusé par Google car le titre est fusionné sur toute la largeur
        reqs.append({"updateSheetProperties": {"properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": lignes_figees}},
                                               "fields": "gridProperties.frozenRowCount"}})
    return reqs


def exporter_google(onglets, nom_classeur, partager_avec):
    import gspread

    creds = authentifier_google()
    client = gspread.authorize(creds)
    classeur = client.create(nom_classeur)
    print(f"✓ Classeur créé : {nom_classeur}\n  {classeur.url}")

    titres_pris = set()
    reqs_ajout = []
    for o in onglets:
        o["titre_google"] = titre_onglet_google(o["titre"], titres_pris)
        reqs_ajout.append({"addSheet": {"properties": {"title": o["titre_google"],
                                                       "gridProperties": {"rowCount": len(o["lignes"]) + 2, "columnCount": max(o["nb_cols"], 2)}}}})
    id_defaut = classeur.sheet1.id
    reponse = classeur.batch_update({"requests": reqs_ajout + [{"deleteSheet": {"sheetId": id_defaut}}]})
    ids = [r["addSheet"]["properties"]["sheetId"] for r in reponse["replies"] if "addSheet" in r]

    lot, taille_lot = [], 0
    for o, sheet_id in zip(onglets, ids):
        lot.extend(requetes_onglet(sheet_id, o, o["largeurs"], o.get("figees", 0)))
        taille_lot += 1
        if taille_lot >= 6:
            classeur.batch_update({"requests": lot})
            lot, taille_lot = [], 0
    if lot:
        classeur.batch_update({"requests": lot})

    if partager_avec:
        for courriel in partager_avec:
            classeur.share(courriel, perm_type="user", role="writer", notify=True)
            print(f"✓ Partagé (écriture) avec {courriel}")
    return classeur.url


# ───────────────────────────── Programme principal ─────────────────────────────

def trouver_entrees(dossier_annee):
    ods = sorted(dossier_annee.glob("*.ods"))
    if not ods:
        raise SystemExit(f"❌ Aucun fichier .ods (notifications) dans {dossier_annee}")
    if len(ods) > 1:
        print(f"⚠ Plusieurs .ods trouvés, utilisation du plus récent : {ods[-1].name}")
    dossiers_ics = sorted({p.parent for p in dossier_annee.rglob("*.ics")})
    if not dossiers_ics:
        raise SystemExit(f"❌ Aucun fichier .ics dans {dossier_annee}")
    return ods[-1], dossiers_ics


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--annee", default=ANNEE_DEFAUT, help="dossier d'année scolaire (défaut : %(default)s)")
    ap.add_argument("--google", action="store_true", help="créer le Google Sheet (sinon aperçu local uniquement)")
    ap.add_argument("--partager", action="append", default=[], metavar="EMAIL", help="partager le classeur en écriture avec cet e-mail (répétable)")
    ap.add_argument("--nom", default=None, help="nom du classeur Google (défaut : EDT_Eleves_AESH_<année>_<horodatage>)")
    args = ap.parse_args()

    dossier_annee = RACINE / args.annee
    if not dossier_annee.is_dir():
        raise SystemExit(f"❌ Dossier d'année introuvable : {dossier_annee}")
    chemin_ods, dossiers_ics = trouver_entrees(dossier_annee)
    dossier_sorties = dossier_annee / "sorties"
    dossier_sorties.mkdir(exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 70)
    print(f"Emplois du temps élèves notifiés — {args.annee}")
    print("=" * 70)
    print(f"📋 Notifications : {chemin_ods.name} (onglet {ONGLET_ELEVES!r})")

    eleves = lire_eleves(chemin_ods)
    print(f"   {len(eleves)} élève(s) à traiter")
    index = []
    for d in dossiers_ics:
        idx, ignores = indexer_ics(d)
        index.extend(idx)
        print(f"📁 {d.relative_to(RACINE)} : {len(idx)} fichier(s) ICS" + (f", {len(ignores)} nom(s) non reconnus" if ignores else ""))

    # ── Appariement et lecture des ICS
    print("\n🔗 Appariement élèves ↔ fichiers ICS")
    resultats = []
    for e in eleves:
        entree, score, explication = apparier(e, index)
        e["ics"] = entree
        e["score"] = score
        e["explication"] = explication
        if entree:
            e["cours"], e["journees"] = lire_ics(entree["chemin"])
        else:
            e["cours"], e["journees"] = [], []
        marque = "✓" if entree else "✗"
        print(f"  {marque} {e['nom_complet']:<28} {e['dob_texte']:<11} → {entree['chemin'].name if entree else '—':<48} {len(e['cours']):>3} cours  ({explication})")
        resultats.append(e)

    tous_cours = [c for e in resultats for c in e["cours"]]
    if not tous_cours:
        raise SystemExit("❌ Aucun cours trouvé pour les élèves à traiter.")

    # ── Plage horaire : début commun à tous les onglets, fin étendue par élève (≥ HEURE_MAX_DEFAUT)
    h_min = min(HEURE_MIN_DEFAUT, min(c["debut"].hour for c in tous_cours))
    h_max_global = max(HEURE_MAX_DEFAUT, heure_fin_arrondie(tous_cours))
    lundis = sorted({lundi_de(c["debut"].date()) for c in tous_cours})
    annee_debut = lundis[0].year
    lundi_reference = date.fromisocalendar(annee_debut, SEMAINE_A_REFERENCE or 35, 1)
    print(f"\n🕒 Grille {h_min}h → {HEURE_MAX_DEFAUT}h (étendue jusqu'à {h_max_global}h pour les élèves concernés), pas {PAS_MINUTES} min ; jours : {', '.join(JOURS)}")
    print(f"📅 Semaine(s) couverte(s) par les exports : " + ", ".join(f"S{l.isocalendar()[1]} ({l.strftime('%d/%m')} → {(l + timedelta(days=6)).strftime('%d/%m/%Y')})" for l in lundis))
    if len(lundis) == 1:
        print("   ⚠ Une seule semaine exportée : pas de détection d'alternance A/B possible (l'emploi du temps affiché est celui de cette semaine).")
    else:
        print(f"   Alternance A/B : semaine A de référence = ISO {SEMAINE_A_REFERENCE or '35 (impaires = A, par défaut)'}")

    # ── Construction des onglets (plusieurs semaines → demi-colonnes « sem. A | sem. B » par jour)
    scinder_ab = len(lundis) > 1
    onglets = []
    date_gen = datetime.now().strftime("%d/%m/%Y %H:%M")
    for e in resultats:
        if not e["ics"]:
            continue
        h_max = max(HEURE_MAX_DEFAUT, heure_fin_arrondie(e["cours"]))
        grille, semaines, hors_grille = construire_grille(e["cours"], h_min, h_max, lundi_reference)
        lundis_eleve = sorted(semaines["A"] | semaines["B"])
        dates_jours = {}
        if len(lundis_eleve) == 1:
            dates_jours = {j: (lundis_eleve[0] + timedelta(days=j)).strftime("%d/%m") for j in range(len(JOURS))}
        aide = f"{e['type_aide']} {e['heures']} h".strip() if e["type_aide"] or e["heures"] else "aide non renseignée"
        titre = f"{e['ics']['libelle']}" + (f" — {e['classe']}" if e["classe"] else "") + f" — aide humaine : {aide}"
        infos_sem = ("semaine " + ", ".join(f"S{l.isocalendar()[1]}" for l in lundis_eleve) if len(lundis_eleve) == 1
                     else f"{len(lundis_eleve)} semaines (A : {len(semaines['A'])}, B : {len(semaines['B'])})")
        notif = f"notification {e['notif_debut'] or '?'} → {e['notif_fin'] or '?'}" if (e["notif_debut"] or e["notif_fin"]) else "dates de notification non renseignées"
        sous_titre = (f"Né(e) le {e['dob_texte']} · {notif}"
                      + (f" · besoins : {e['besoins']}" if e["besoins"] else "")
                      + f" · source ProNote : {e['ics']['chemin'].name} ({infos_sem}, {len(e['cours'])} cours) · généré le {date_gen}")
        if hors_grille:
            sous_titre += f" · ⚠ {len(hors_grille)} cours hors jours affichés"
        if scinder_ab:
            sous_titre += ("\nLecture : cellule bleue sur toute la largeur du jour = cours identique toutes les semaines ; "
                           "cellules jaunes côte à côte = cours différent en semaine A (gauche) et en semaine B (droite).")
        o = construire_onglet(e["ics"]["libelle"], sous_titre, grille, h_min, h_max, dates_jours, scinder_ab)
        o["lignes"][0][0] = titre
        o["largeurs"] = [(0, 1, LARGEUR_COL_HORAIRE), (1, o["nb_cols"], LARGEUR_DEMI_COL_JOUR if scinder_ab else LARGEUR_COL_JOUR)]
        o["bordures"] = 2
        o["figees"] = o["premiere_grille"]
        if scinder_ab:
            o["hauteur_sous_titre"] = HAUTEUR_LIGNE_SOUS_TITRE
        onglets.append(o)
        e["nb_lignes"] = len(o["lignes"])

    # ── Onglet Récap (en tête)
    entete = ["Élève (ODS)", "Né(e) le", "Classe (col. REMARQUES)", "Niveau", "Aide", "Heures", "Notif. début", "Notif. fin", "Besoins", "Fichier ICS", "Cours", "Appariement"]
    lignes = [[f"Élèves notifiés — {args.annee} — {len(resultats)} élève(s), {sum(1 for e in resultats if e['ics'])} emploi(s) du temps"] + [""] * (len(entete) - 1),
              [f"Source : {chemin_ods.name} · exports ProNote : {', '.join(d.name for d in dossiers_ics)} · généré le {date_gen}"] + [""] * (len(entete) - 1),
              entete]
    styles = {(0, 0): "titre", (1, 0): "sous_titre"}
    styles.update({(2, c): "entete" for c in range(len(entete))})
    for e in resultats:
        r = len(lignes)
        lignes.append([e["nom_complet"], e["dob_texte"], e["classe"], e["niveau"], e["type_aide"], e["heures"], e["notif_debut"], e["notif_fin"], e["besoins"],
                       e["ics"]["chemin"].name if e["ics"] else "AUCUN", str(len(e["cours"])) if e["ics"] else "", e["explication"]])
        if not e["ics"]:
            for c in range(len(entete)):
                styles[(r, c)] = "absent"
    journees = {}
    for e in resultats:
        for j in e["journees"]:
            journees[(j["debut"], j["fin"], j["libelle"])] = j
    if journees:
        lignes.append([""] * len(entete))
        r = len(lignes)
        lignes.append(["Calendrier ProNote (journées entières)", "Du", "Au"] + [""] * (len(entete) - 3))
        for c in range(3):
            styles[(r, c)] = "entete"
        for (d0, d1, lib) in sorted(journees):
            lignes.append([lib, d0.strftime("%d/%m/%Y"), d1.strftime("%d/%m/%Y")] + [""] * (len(entete) - 3))
    recap = {"titre": "Récap", "lignes": lignes, "fusions": [(0, 1, 0, len(entete)), (1, 2, 0, len(entete))], "styles": styles, "nb_cols": len(entete),
             "largeurs": [(0, 1, 200), (1, 2, 90), (2, 4, 110), (4, 8, 85), (8, 9, 260), (9, 10, 300), (10, 11, 60), (11, 12, 260)], "bordures": 2, "figees": NB_LIGNES_ENTETE}
    onglets.insert(0, recap)

    # ── Sorties locales
    nom_classeur = args.nom or f"EDT_Eleves_AESH_{args.annee}_{horodatage}"
    chemin_html = dossier_sorties / f"{nom_classeur}.html"
    chemin_html.write_text(rendre_html(onglets, nom_classeur), encoding="utf-8")
    chemin_csv = dossier_sorties / f"{nom_classeur}_appariement.csv"
    with chemin_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(entete)
        for l in lignes[3:3 + len(resultats)]:
            w.writerow(l)
    print(f"\n💾 Aperçu local : {chemin_html.relative_to(RACINE)}")
    print(f"💾 Appariement : {chemin_csv.relative_to(RACINE)}")
    absents = [e["nom_complet"] for e in resultats if not e["ics"]]
    if absents:
        print(f"⚠ Sans emploi du temps ({len(absents)}) : {', '.join(absents)}")

    # ── Google Sheets
    if args.google:
        print("\n📊 Création du Google Sheet…")
        url = exporter_google(onglets, nom_classeur, args.partager)
        (dossier_sorties / f"{nom_classeur}_google_url.txt").write_text(url + "\n")
        print("\n" + "=" * 70 + f"\n✓ Terminé — {len(onglets) - 1} onglet(s) élève + Récap\n  {url}\n" + "=" * 70)
    else:
        print("\nℹ Aperçu local uniquement. Ajouter --google pour créer le Google Sheet.")


if __name__ == "__main__":
    main()
