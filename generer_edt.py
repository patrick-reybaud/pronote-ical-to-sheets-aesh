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
semaines occupe les deux (cellule large), un cours différent selon la semaine est écrit côte à côte
(deux cellules, même couleur). Export d'une seule semaine : une colonne par jour, colonnes datées.
"""

import argparse
import csv
import re
from datetime import date, datetime, timedelta

from noyau import (
    # configuration partagée
    RACINE, JOURS, HEURE_MIN_DEFAUT, HEURE_MAX_DEFAUT, PAS_MINUTES, SEMAINE_A_REFERENCE,
    NB_LIGNES_ENTETE, LARGEUR_COL_HORAIRE, LARGEUR_COL_JOUR, LARGEUR_DEMI_COL_JOUR,
    HAUTEUR_LIGNE_SOUS_TITRE,
    # utilitaires
    compacter, parser_date_fr, lundi_de,
    # lecture des entrées
    lire_onglet_ods, indexer_ics, apparier, lire_ics,
    # grille horaire et rendu
    heure_fin_arrondie, construire_grille, construire_onglet, rendre_html,
    # Google Sheets
    exporter_google,
)

# ───────────────────────────── Configuration ─────────────────────────────

ANNEE_DEFAUT = "2026-2027"
ONGLET_ELEVES = "Besoins_élèves"


# ───────────────────────────── Élèves (fichier de notifications) ─────────────────────────────

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
        grille, semaines, hors_grille, anomalies = construire_grille(e["cours"], h_min, h_max, lundi_reference)
        e["anomalies"] = anomalies
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
        if anomalies:
            sous_titre += f" · ⚠ {len(anomalies)} cours à périodicité inhabituelle (voir Récap)"
        if scinder_ab:
            sous_titre += ("\nLecture : cellule sur toute la largeur du jour = cours identique toutes les semaines ; "
                           "deux cellules côte à côte = cours différent en semaine A (gauche) et en semaine B (droite).")
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
