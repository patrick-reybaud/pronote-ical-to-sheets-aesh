#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aesh.py — chaîne d'affectation des AESH aux élèves notifiés.

Complète generer_edt.py (emplois du temps des élèves) par tout ce qui concerne les accompagnants :
recueil de leurs disponibilités, affectation aux élèves, publication de leurs emplois du temps.

Sous-commandes :
  matieres   référentiel des matières : regroupe les libellés ProNote en familles (Français, Maths, TP Cuisine…)
  liste      liste des AESH : importée de l'onglet « Moyens_AESH_terrain » du fichier de notifications
  saisie     classeur Google de recueil : disponibilités (cases à cocher) + affinités par matière
  besoins    classeur des difficultés des élèves par matière (coordination uniquement)
  collecte   relire les classeurs remplis → <année>/aesh/dispos.json + contrôles

Usage :
  python aesh.py matieres                       # crée/actualise <année>/aesh/matieres.csv
  python aesh.py liste                          # crée/actualise <année>/aesh/aesh.csv
  python aesh.py liste --etablissement COLLEGE  # autre filtre d'établissement
  python aesh.py saisie                         # aperçu local du classeur de saisie
  python aesh.py saisie --google --partager-aesh --echeance "vendredi 2 octobre"
  python aesh.py besoins --google                # difficultés des élèves (à ne pas partager aux AESH)
  python aesh.py collecte                       # relit les réponses
  python aesh.py <cmd> --annee 2027-2028        # autre dossier d'année

Les fichiers CSV produits sont faits pour être relus et corrigés à la main (tableur) : une nouvelle
exécution conserve les modifications et se contente d'ajouter ce qui est nouveau.
"""

import argparse
import csv
import json
import re
import sys
from datetime import datetime

from noyau import (JOURS, PAS_MINUTES, RACINE, apparier, compacter, exporter_google,
                   indexer_ics, lire_ics, lire_onglet_ods, rendre_html)

ANNEE_DEFAUT = "2026-2027"
ONGLET_AESH = "Moyens_AESH_terrain"
ETABLISSEMENT_DEFAUT = "HOTELIER"   # filtre appliqué à la colonne « Nom établissement »
PLAGE_SAISIE_DEFAUT = (7, 19)       # amplitude de la grille de saisie des disponibilités (heures entières)

# Familles de matières, dans l'ordre où elles seront présentées aux AESH et aux élèves.
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

# Règles de classement des libellés ProNote, appliquées dans l'ordre (première correspondance retenue).
# Le libellé est comparé après compacter() : majuscules, sans accents ni ponctuation.
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

NON_CLASSE = "??? à classer"


# ───────────────────────────── Fichiers de travail ─────────────────────────────

def dossier_aesh(annee):
    d = RACINE / annee / "aesh"
    d.mkdir(parents=True, exist_ok=True)
    return d


def lire_csv(chemin):
    """Lignes d'un CSV « ; » sous forme de dictionnaires ; liste vide si le fichier n'existe pas."""
    if not chemin.exists():
        return []
    with chemin.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def ecrire_csv(chemin, colonnes, lignes):
    """CSV « ; » encodé utf-8-sig, pour s'ouvrir directement dans LibreOffice ou Excel."""
    with chemin.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=colonnes, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(lignes)


def trouver_ods(annee):
    dossier = RACINE / annee
    if not dossier.is_dir():
        raise SystemExit(f"❌ Dossier d'année introuvable : {dossier}")
    ods = sorted(dossier.glob("*.ods"))
    if not ods:
        raise SystemExit(f"❌ Aucun fichier .ods (notifications) dans {dossier}")
    if len(ods) > 1:
        print(f"⚠ Plusieurs .ods trouvés, utilisation du plus récent : {ods[-1].name}")
    return ods[-1]


def index_colonnes(entetes, *groupes):
    """Indices des colonnes dont l'en-tête compacté contient tous les motifs d'un groupe (None si absente)."""
    compacts = [compacter(h) for h in entetes]
    resultats = []
    for motifs in groupes:
        trouve = None
        for i, h in enumerate(compacts):
            if all(m in h for m in motifs):
                trouve = i
                break
        resultats.append(trouve)
    return resultats


# ───────────────────────────── Référentiel des matières ─────────────────────────────

def deviner_famille(libelle):
    """Famille proposée pour un libellé ProNote, ou NON_CLASSE si aucune règle ne s'applique."""
    compact = compacter(libelle)
    for motif, famille in REGLES_FAMILLE:
        if re.search(motif, compact):
            return famille
    return NON_CLASSE


def relever_matieres(annee):
    """Compte les occurrences de chaque libellé de matière dans tous les ICS du dossier d'année."""
    dossier = RACINE / annee
    index, _ = indexer_ics(dossier)
    if not index:
        raise SystemExit(f"❌ Aucun fichier .ics dans {dossier}")
    occurrences = {}
    for entree in index:
        cours, _ = lire_ics(entree["chemin"])
        for c in cours:
            occurrences[c["matiere"]] = occurrences.get(c["matiere"], 0) + 1
    return occurrences, len(index)


def charger_matieres(annee):
    """Retourne (correspondance libellé → famille, familles dans l'ordre d'affichage)."""
    chemin = dossier_aesh(annee) / "matieres.csv"
    lignes = lire_csv(chemin)
    if not lignes:
        raise SystemExit(f"❌ {chemin.relative_to(RACINE)} absent — lancer d'abord : python aesh.py matieres")
    correspondance = {l["libelle_pronote"]: l["famille"] for l in lignes if l.get("libelle_pronote")}
    connues = list(dict.fromkeys(correspondance.values()))
    familles = [f for f in FAMILLES if f in connues] + [f for f in connues if f not in FAMILLES]
    return correspondance, familles


def cmd_matieres(args):
    chemin = dossier_aesh(args.annee) / "matieres.csv"
    occurrences, nb_ics = relever_matieres(args.annee)
    print(f"📚 {len(occurrences)} libellé(s) de matière relevé(s) dans {nb_ics} fichier(s) ICS")

    existant = {l["libelle_pronote"]: l["famille"] for l in lire_csv(chemin) if l.get("libelle_pronote")}
    lignes, nouveaux, disparus = [], [], [m for m in existant if m not in occurrences]
    for libelle in sorted(occurrences):
        if libelle in existant:
            famille = existant[libelle]
        else:
            famille = deviner_famille(libelle)
            nouveaux.append((libelle, famille))
        lignes.append({"famille": famille, "libelle_pronote": libelle, "occurrences": occurrences[libelle]})

    rang = {f: i for i, f in enumerate(FAMILLES)}
    lignes.sort(key=lambda l: (rang.get(l["famille"], len(FAMILLES)), l["famille"], l["libelle_pronote"]))
    ecrire_csv(chemin, ["famille", "libelle_pronote", "occurrences"], lignes)

    par_famille = {}
    for l in lignes:
        par_famille.setdefault(l["famille"], []).append(l)
    print(f"\n{'Famille':<34} {'libellés':>8} {'cours':>7}")
    print("─" * 52)
    for famille in [f for f in FAMILLES if f in par_famille] + [f for f in par_famille if f not in FAMILLES]:
        groupe = par_famille[famille]
        print(f"{famille:<34} {len(groupe):>8} {sum(int(l['occurrences']) for l in groupe):>7}")

    if existant:
        print(f"\n✓ {len(lignes) - len(nouveaux)} classement(s) existant(s) conservé(s)")
    if nouveaux:
        print(f"\n🆕 {len(nouveaux)} nouveau(x) libellé(s) classé(s) automatiquement :")
        for libelle, famille in nouveaux:
            print(f"   {libelle:<28} → {famille}")
    if disparus:
        print(f"\n🗑 {len(disparus)} libellé(s) qui n'apparaissent plus dans les ICS, retiré(s) : {', '.join(disparus)}")

    a_classer = [l["libelle_pronote"] for l in lignes if l["famille"] == NON_CLASSE]
    if a_classer:
        print(f"\n⚠ {len(a_classer)} libellé(s) que je n'ai pas su classer — à corriger dans le fichier :")
        for libelle in a_classer:
            print(f"   {libelle}")
    print(f"\n💾 {chemin.relative_to(RACINE)}"
          + ("\n   Relisez la colonne « famille » et corrigez si besoin : vos corrections seront conservées."
             if nouveaux or not existant else ""))


# ───────────────────────────── Liste des AESH ─────────────────────────────

COLONNES_AESH = ["id", "nom_complet", "actif", "aesh_co", "quotite_retenue", "etablissement",
                 "quotite_sco", "quotite_epp", "quotite_co", "quotite_cantine", "email", "telephone"]


def identifiant(nom_complet, deja_pris):
    base = re.sub(r"[^a-z0-9]+", "_", compacter(nom_complet).lower()).strip("_") or "aesh"
    ident, n = base, 2
    while ident in deja_pris:
        ident, n = f"{base}_{n}", n + 1
    deja_pris.add(ident)
    return ident


def nombre(texte):
    """Valeur numérique d'une cellule ODS (« 24 », « 24,5 »…), ou None."""
    try:
        return float((texte or "").replace(",", ".").strip())
    except ValueError:
        return None


def quotite_de_service(sco, co, epp):
    """
    Quotité hebdomadaire à retenir, et la colonne dont elle vient.

    « Quotité SCO » est le temps devant élèves et fait foi quand elle est renseignée. Les AESH affectés
    à un dispositif collectif (ULIS) n'ont pas de SCO mais une « Quotité AESH Co ». « Quotité EPP »
    (temps de service total) ne sert que de dernier recours.
    """
    for valeur, origine in ((sco, "SCO"), (co, "AESH Co"), (epp, "EPP")):
        if valeur is not None:
            return valeur, origine
    return None, "—"


def cmd_liste(args):
    chemin = dossier_aesh(args.annee) / "aesh.csv"
    chemin_ods = trouver_ods(args.annee)
    lignes_ods = lire_onglet_ods(chemin_ods, ONGLET_AESH)
    entetes = lignes_ods[0]
    (i_nom, i_etab, i_sco, i_epp, i_co, i_cantine, i_mail, i_tel) = index_colonnes(
        entetes, ("NOM PRENOM AESH",), ("NOM ETABLISSEMENT",), ("QUOTITE SCO",), ("QUOTITE EPP",),
        ("QUOTITE AESH CO",), ("QUOTITE TEMPS CANTINE", args.annee[:4]), ("MEL",), ("TELEPHONE",))
    if i_nom is None:
        raise SystemExit(f"❌ Colonne « NOM PRENOM AESH » introuvable dans l'onglet {ONGLET_AESH!r}")

    print(f"👥 Source : {chemin_ods.name} (onglet {ONGLET_AESH!r}, {len(lignes_ods) - 1} AESH dans le PIAL)")
    motif = compacter(args.etablissement)

    def val(ligne, i):
        return ligne[i].strip() if i is not None and i < len(ligne) else ""

    existant = {l["id"]: l for l in lire_csv(chemin)}
    retenus, ignores, deja_pris = [], 0, set()
    mails_douteux, ecarts_quotite, sans_quotite = [], [], []
    for ligne in lignes_ods[1:]:
        nom = re.sub(r"\s+", " ", val(ligne, i_nom))
        if not nom:
            continue
        etablissement = val(ligne, i_etab)
        if motif and motif not in compacter(etablissement):
            ignores += 1
            continue
        ident = identifiant(nom, deja_pris)
        sco, epp, co = nombre(val(ligne, i_sco)), nombre(val(ligne, i_epp)), nombre(val(ligne, i_co))
        quotite, origine = quotite_de_service(sco, co, epp)
        if quotite is None:
            sans_quotite.append(nom)
        elif origine != "SCO":
            ecarts_quotite.append(f"{nom} : pas de quotité SCO, quotité « {origine} » retenue ({quotite:g} h)")
        elif epp is not None and epp != sco:
            ecarts_quotite.append(f"{nom} : EPP {epp:g} h ≠ SCO {sco:g} h — SCO retenue")
        email = val(ligne, i_mail)
        if email and "@" not in email:
            mails_douteux.append(f"{nom} : « {email} » dans la colonne courriel")
            email = ""
        ancien = existant.get(ident, {})
        retenus.append({
            "id": ident,
            "nom_complet": nom,
            # colonnes modifiables à la main : conservées d'une exécution à l'autre
            "actif": ancien.get("actif") or "oui",
            "aesh_co": ancien.get("aesh_co") or ("oui" if sco is None and co is not None else "non"),
            "quotite_retenue": ancien.get("quotite_retenue") or (f"{quotite:g}" if quotite is not None else ""),
            "etablissement": etablissement,
            "quotite_sco": f"{sco:g}" if sco is not None else "",
            "quotite_epp": f"{epp:g}" if epp is not None else "",
            "quotite_co": f"{co:g}" if co is not None else "",
            "quotite_cantine": val(ligne, i_cantine),
            "email": email,
            "telephone": val(ligne, i_tel),
        })

    if not retenus:
        raise SystemExit(f"❌ Aucun AESH dont l'établissement contient « {args.etablissement} ». "
                         f"Établissements présents : {sorted({val(l, i_etab) for l in lignes_ods[1:] if val(l, i_etab)})}")

    ajoutes = [r for r in retenus if r["id"] not in existant]
    partis = [l for i, l in existant.items() if i not in {r["id"] for r in retenus}]
    ecrire_csv(chemin, COLONNES_AESH, retenus)

    print(f"   filtre « {args.etablissement} » → {len(retenus)} retenu(s), {ignores} écarté(s)\n")
    print(f"{'AESH':<32} {'quotité':>8} {'EPP':>6} {'SCO':>6} {'Co':>6}  courriel")
    print("─" * 96)
    for r in retenus:
        marque = " " if r["actif"].lower().startswith("o") else "✗"
        suffixe = "  [collectif ULIS]" if r["aesh_co"].lower().startswith("o") else ""
        print(f"{marque}{r['nom_complet']:<31} {r['quotite_retenue']:>8} {r['quotite_epp']:>6} "
              f"{r['quotite_sco']:>6} {r['quotite_co']:>6}  {r['email'] or '—'}{suffixe}")
    actifs = [r for r in retenus if r["actif"].lower().startswith("o")]
    total = sum(nombre(r["quotite_retenue"]) or 0 for r in actifs)
    total_indiv = sum(nombre(r["quotite_retenue"]) or 0 for r in actifs if not r["aesh_co"].lower().startswith("o"))
    print("─" * 96)
    print(f"{'Total (AESH actifs)':<32} {total:>8g} h/semaine"
          + (f"  dont {total_indiv:g} h hors dispositif collectif" if total_indiv != total else ""))

    for titre, anomalies in (("⚠ Quotités à vérifier", ecarts_quotite),
                             ("⚠ Courriels à vérifier dans le fichier source", mails_douteux),
                             ("⚠ Aucune quotité renseignée", sans_quotite)):
        if anomalies:
            print(f"\n{titre} :")
            for a in anomalies:
                print(f"   {a}")

    if existant:
        print(f"\n✓ Colonnes « actif » et « quotite_retenue » conservées pour {len(retenus) - len(ajoutes)} AESH")
    if ajoutes:
        print(f"🆕 {len(ajoutes)} AESH ajouté(s) : {', '.join(r['nom_complet'] for r in ajoutes)}")
    if partis:
        print(f"🗑 {len(partis)} AESH retiré(s) (absent(s) du fichier source) : "
              f"{', '.join(l['nom_complet'] for l in partis)}")
    sans_mail = [r["nom_complet"] for r in retenus if not r["email"]]
    if sans_mail:
        print(f"\n⚠ Sans courriel — le partage du classeur de saisie devra être fait à la main : {', '.join(sans_mail)}")
    print(f"\n💾 {chemin.relative_to(RACINE)}"
          "\n   « actif » (oui/non) et « quotite_retenue » (heures/semaine) sont faits pour être ajustés à la main.")


# ───────────────────────────── Classeur de saisie des disponibilités ─────────────────────────────

def charger_aesh(annee, actifs_seulement=True):
    """Liste des AESH depuis aesh.csv, quotité convertie en nombre (clé « quotite_h »)."""
    chemin = dossier_aesh(annee) / "aesh.csv"
    lignes = lire_csv(chemin)
    if not lignes:
        raise SystemExit(f"❌ {chemin.relative_to(RACINE)} absent — lancer d'abord : python aesh.py liste")
    retenus = []
    for l in lignes:
        if actifs_seulement and not l.get("actif", "").lower().startswith("o"):
            continue
        l["quotite_h"] = nombre(l.get("quotite_retenue")) or 0.0
        l["est_co"] = l.get("aesh_co", "").lower().startswith("o")
        retenus.append(l)
    if not retenus:
        raise SystemExit(f"❌ Aucun AESH actif dans {chemin.relative_to(RACINE)}")
    return retenus


def cours_eleves_notifies(annee):
    """Tous les cours des élèves notifiés (tous exports confondus), pour dimensionner et contrôler la grille."""
    from generer_edt import lire_eleves
    eleves = lire_eleves(trouver_ods(annee))
    index, _ = indexer_ics(RACINE / annee)
    tous_cours = []
    for e in eleves:
        entree, _, _ = apparier(e, index)
        if entree:
            cours, _ = lire_ics(entree["chemin"])
            tous_cours.extend(cours)
    if not tous_cours:
        raise SystemExit("❌ Aucun cours trouvé pour les élèves notifiés.")
    return tous_cours


def couverture_plage(cours, h_min, h_max):
    """(demi-heures de cours dans la plage, hors plage, heures concernées hors plage)."""
    dedans, dehors, heures = 0, 0, set()
    for c in cours:
        minute = c["debut"].hour * 60 + c["debut"].minute
        fin = c["fin"].hour * 60 + c["fin"].minute
        if fin <= minute:                      # cours finissant à minuit
            fin = 24 * 60
        while minute < fin:
            if h_min * 60 <= minute < h_max * 60:
                dedans += 1
            else:
                dehors += 1
                heures.add(minute // 60)
            minute += PAS_MINUTES
    return dedans, dehors, sorted(heures)


def plage_horaire(annee, plage_demandee=None):
    """
    Amplitude de la grille de saisie : (h_min, h_max), heures entières.

    La plage par défaut est volontairement fixe : la déduire des données donnerait 7h → 24h à cause de
    quelques services de restauration du soir, et ferait cocher 170 cases à chaque AESH pour rien.
    L'appelant compare ensuite avec couverture_plage() et propose --plage si le reste à couvrir est réel.
    """
    if not plage_demandee:
        return PLAGE_SAISIE_DEFAUT
    try:
        debut, fin = (int(x) for x in plage_demandee.split("-"))
    except ValueError:
        raise SystemExit(f"❌ --plage attend « début-fin » en heures entières, ex. 7-19 (reçu : {plage_demandee!r})")
    if not 0 <= debut < fin <= 24:
        raise SystemExit(f"❌ Plage horaire invalide : {plage_demandee}")
    return debut, fin


def cmd_saisie(args):
    import aesh_saisie

    aesh_liste = charger_aesh(args.annee)
    _, familles = charger_matieres(args.annee)
    h_min, h_max = plage_horaire(args.annee, args.plage)

    print(f"📝 Classeur de saisie des disponibilités — {args.annee}")
    print(f"   {len(aesh_liste)} AESH actif(s) · {len(familles)} famille(s) de matières")
    origine = "imposée par --plage" if args.plage else "plage par défaut"
    nb_creneaux = (h_max - h_min) * 60 // PAS_MINUTES
    print(f"   Grille {h_min}h → {h_max}h ({origine}) : {nb_creneaux} demi-heures × {len(JOURS)} jours "
          f"= {nb_creneaux * len(JOURS)} cases à cocher par AESH")

    dedans, dehors, heures = couverture_plage(cours_eleves_notifies(args.annee), h_min, h_max)
    part = 100 * dedans / (dedans + dehors)
    print(f"   Couvre {part:.1f} % des demi-heures de cours des élèves notifiés")
    if dehors:
        plages = ", ".join(f"{h}h" for h in heures)
        print(f"   ⚠ {dehors} demi-heure(s) de cours hors grille ({plages}) — aucun accompagnement "
              f"ne pourra y être affecté. Pour les inclure : --plage {min(h_min, min(heures))}-{max(h_max, max(heures) + 1)}")

    sans_quotite = [a["nom_complet"] for a in aesh_liste if not a["quotite_h"]]
    if sans_quotite:
        print(f"   ⚠ Quotité inconnue (le total ne pourra pas être comparé) : {', '.join(sans_quotite)}")

    onglets = aesh_saisie.construire_onglets(aesh_liste, familles, h_min, h_max, args.annee, args.echeance)

    dossier_sorties = RACINE / args.annee / "sorties"
    dossier_sorties.mkdir(exist_ok=True)
    nom = args.nom or f"Saisie_AESH_{args.annee}"
    chemin_html = dossier_sorties / f"{nom}.html"
    chemin_html.write_text(rendre_html(onglets, nom), encoding="utf-8")
    print(f"\n💾 Aperçu local : {chemin_html.relative_to(RACINE)}")

    if not args.google:
        print("\nℹ Aperçu local uniquement. Ajouter --google pour créer le classeur partageable.")
        return

    destinataires = list(args.partager)
    if args.partager_aesh:
        courriels = [a["email"] for a in aesh_liste if a["email"]]
        manquants = [a["nom_complet"] for a in aesh_liste if not a["email"]]
        destinataires += courriels
        print(f"\n📧 Partage avec {len(courriels)} AESH"
              + (f" — à partager à la main avec : {', '.join(manquants)}" if manquants else ""))

    print("\n📊 Création du Google Sheet…")
    url = exporter_google(onglets, nom, destinataires)
    (dossier_sorties / f"{nom}_google_url.txt").write_text(url + "\n")

    # Descripteur du classeur : c'est lui qui permet à « collecte » de relire les bonnes plages
    # sans redécouvrir la mise en page ni la coder en dur à deux endroits.
    descripteur = {
        "url": url,
        "id": url.rstrip("/").split("/")[-1],
        "nom": nom,
        "cree_le": datetime.now().isoformat(timespec="seconds"),
        "annee": args.annee,
        "h_min": h_min, "h_max": h_max, "pas_minutes": PAS_MINUTES,
        "familles": familles,
        "onglets": {o["titre_google"]: {"type": "aesh" if o.get("id_aesh") else "liste",
                                        "id_aesh": o.get("id_aesh"), "reperes": o["reperes"]}
                    for o in onglets if o.get("reperes")},
    }
    chemin_desc = dossier_aesh(args.annee) / "classeur_saisie.json"
    chemin_desc.write_text(json.dumps(descripteur, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 Descripteur du classeur : {chemin_desc.relative_to(RACINE)}")
    print(f"\n{'=' * 70}\n✓ Terminé — {len(onglets) - 1} onglet(s) AESH + mode d'emploi\n  {url}\n{'=' * 70}")
    print("  Conservez cette URL : c'est elle que lira « python aesh.py collecte ».")


# ───────────────────────────── Difficultés des élèves par matière ─────────────────────────────

def cmd_besoins(args):
    import aesh_besoins
    from generer_edt import lire_eleves

    _, familles = charger_matieres(args.annee)
    eleves = lire_eleves(trouver_ods(args.annee))
    onglet = aesh_besoins.construire_onglet_difficultes(eleves, familles, args.annee)

    print(f"📗 Difficultés des élèves par matière — {args.annee}")
    print(f"   {len(eleves)} élève(s) × {len(familles)} famille(s) de matières")
    print(f"   {onglet['preremplies']} case(s) pré-remplie(s) d'après le texte libre de la colonne « Besoins »")
    sans_besoins = [e["nom_complet"] for e in eleves if not e.get("besoins")]
    if sans_besoins:
        print(f"   {len(sans_besoins)} élève(s) sans texte dans « Besoins » — tout est à saisir pour eux")
    print("   ⚠ Ce classeur porte des informations liées au handicap : à ne partager qu'avec la coordination.")

    dossier_sorties = RACINE / args.annee / "sorties"
    dossier_sorties.mkdir(exist_ok=True)
    nom = args.nom or f"Besoins_Eleves_{args.annee}"
    chemin_html = dossier_sorties / f"{nom}.html"
    chemin_html.write_text(rendre_html([onglet], nom), encoding="utf-8")
    print(f"\n💾 Aperçu local : {chemin_html.relative_to(RACINE)}")

    if not args.google:
        print("\nℹ Aperçu local uniquement. Ajouter --google pour créer le classeur.")
        return

    print("\n📊 Création du Google Sheet…")
    url = exporter_google([onglet], nom, args.partager)
    descripteur = {"url": url, "id": url.rstrip("/").split("/")[-1], "nom": nom,
                   "cree_le": datetime.now().isoformat(timespec="seconds"), "annee": args.annee,
                   "familles": familles,
                   "onglets": {onglet["titre_google"]: {"type": "difficultes", "reperes": onglet["reperes"]}}}
    chemin_desc = dossier_aesh(args.annee) / "classeur_besoins.json"
    chemin_desc.write_text(json.dumps(descripteur, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{'=' * 70}\n✓ Terminé\n  {url}\n{'=' * 70}")
    print(f"💾 Descripteur : {chemin_desc.relative_to(RACINE)}")


# ───────────────────────────── Collecte des réponses ─────────────────────────────

def plage_a1(titre, plage, colonnes=None):
    """Plage Google au format A1 à partir d'un repère {startRowIndex, endRowIndex, start/endColumnIndex}."""
    c0 = plage["startColumnIndex"] if colonnes is None else colonnes[0]
    c1 = (plage["endColumnIndex"] if colonnes is None else colonnes[1]) - 1
    titre_echappe = titre.replace("'", "''")
    return f"'{titre_echappe}'!{chr(65 + c0)}{plage['startRowIndex'] + 1}:{chr(65 + c1)}{plage['endRowIndex']}"


def cellule(grille, ligne, colonne):
    """Valeur d'une cellule d'un bloc renvoyé par l'API, qui tronque les lignes et colonnes vides."""
    if ligne >= len(grille):
        return ""
    ligne_lue = grille[ligne]
    return ligne_lue[colonne] if colonne < len(ligne_lue) else ""


def charger_descripteur(annee, url=None):
    chemin = dossier_aesh(annee) / "classeur_saisie.json"
    if url:
        return {"id": url.rstrip("/").split("/")[-1], "url": url, "onglets": None}
    if not chemin.exists():
        raise SystemExit(f"❌ {chemin.relative_to(RACINE)} absent — lancer d'abord : python aesh.py saisie --google\n"
                         f"   (ou indiquer le classeur avec --classeur <URL>)")
    return json.loads(chemin.read_text(encoding="utf-8"))


def cmd_collecte(args):
    import gspread
    from noyau import authentifier_google

    desc = charger_descripteur(args.annee, args.classeur)
    if not desc.get("onglets"):
        raise SystemExit("❌ Descripteur incomplet : relancer « python aesh.py saisie --google » pour le régénérer.")
    classeur = gspread.authorize(authentifier_google()).open_by_key(desc["id"])
    print(f"📥 Collecte depuis « {desc.get('nom', desc['id'])} »\n   {desc['url']}")

    # ── Une seule requête pour toutes les plages utiles
    demandes, cles = [], []
    for titre, info in desc["onglets"].items():
        r = info["reperes"]
        if info["type"] == "aesh":
            for zone in ("grille", "affinites", "remarques"):
                demandes.append(plage_a1(titre, r[zone]))
                cles.append((titre, zone))
        else:
            demandes.append(plage_a1(titre, r["lignes_aesh"], colonnes=(0, 5)))
            cles.append((titre, "liste"))
    reponse = classeur.values_batch_get(demandes, params={"valueRenderOption": "UNFORMATTED_VALUE"})
    lus = {cle: (bloc.get("values") or []) for cle, bloc in zip(cles, reponse["valueRanges"])}

    # ── Onglet « Liste des AESH » : il fait foi sur l'état de l'équipe
    maj_liste, ajouts = [], []
    for (titre, zone), valeurs in lus.items():
        if zone != "liste":
            continue
        for ligne in valeurs:
            nom = str(cellule([ligne], 0, 0) or "").strip()
            if not nom:
                continue
            maj_liste.append({"nom_complet": re.sub(r"\s+", " ", nom),
                              "actif": str(cellule([ligne], 0, 1) or "oui").strip().lower(),
                              "quotite": nombre(str(cellule([ligne], 0, 2) or "")),
                              "aesh_co": str(cellule([ligne], 0, 3) or "non").strip().lower(),
                              "email": str(cellule([ligne], 0, 4) or "").strip()})

    connus = {compacter(l["nom_complet"]): l for l in lire_csv(dossier_aesh(args.annee) / "aesh.csv")}
    for entree in maj_liste:
        if compacter(entree["nom_complet"]) not in connus:
            ajouts.append(entree["nom_complet"])

    # ── Onglets AESH : disponibilités, affinités, remarques
    nb_creneaux = (desc["h_max"] - desc["h_min"]) * 60 // desc["pas_minutes"]
    familles = desc["familles"]
    collecte = {}
    for titre, info in desc["onglets"].items():
        if info["type"] != "aesh":
            continue
        grille = lus.get((titre, "grille"), [])
        dispos = [[bool(cellule(grille, s, j)) for s in range(nb_creneaux)] for j in range(len(JOURS))]
        demi_heures = sum(sum(jour) for jour in dispos)

        bloc_aff = lus.get((titre, "affinites"), [])
        affinites = {}
        for i, famille in enumerate(familles):
            note = nombre(str(cellule(bloc_aff, i, 0) or ""))
            if note:
                affinites[famille] = int(note)

        remarques = "\n".join(str(cellule(lus.get((titre, "remarques"), []), i, 0) or "").strip()
                              for i in range(4)).strip()
        collecte[info["id_aesh"]] = {
            "nom_complet": titre, "disponibilites": dispos,
            "heures_cochees": demi_heures * desc["pas_minutes"] / 60,
            "affinites": affinites, "remarques": remarques,
            "rempli": demi_heures > 0,
        }

    # ── Confrontation avec les quotités
    quotites = {compacter(e["nom_complet"]): e["quotite"] for e in maj_liste}
    print(f"\n{'AESH':<26} {'coché':>8} {'quotité':>8}  état")
    print("─" * 78)
    for donnees in sorted(collecte.values(), key=lambda d: d["nom_complet"]):
        q = quotites.get(compacter(donnees["nom_complet"]))
        h = donnees["heures_cochees"]
        if not donnees["rempli"]:
            etat = "⚠ rien de coché"
        elif q is None:
            etat = "quotité inconnue"
        elif h > q:
            etat = f"⚠ dépasse de {h - q:g} h"
        elif h < q:
            etat = f"⚠ il manque {q - h:g} h"
        else:
            etat = "✓ compte juste"
        aff = f" · {len(donnees['affinites'])} affinité(s)" if donnees["affinites"] else ""
        print(f"{donnees['nom_complet']:<26} {h:>6g} h {q if q is not None else '—':>7}  {etat}{aff}")

    remplis = sum(1 for d in collecte.values() if d["rempli"])
    print("─" * 78)
    print(f"{remplis} / {len(collecte)} AESH ont commencé à remplir")

    chemin = dossier_aesh(args.annee) / "dispos.json"
    chemin.write_text(json.dumps({
        "collecte_le": datetime.now().isoformat(timespec="seconds"),
        "classeur": {"id": desc["id"], "url": desc["url"]},
        "h_min": desc["h_min"], "h_max": desc["h_max"], "pas_minutes": desc["pas_minutes"],
        "jours": JOURS, "familles": familles,
        "liste_aesh": maj_liste, "aesh": collecte,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n💾 {chemin.relative_to(RACINE)}")

    if ajouts:
        print(f"\n🆕 {len(ajouts)} AESH ajouté(s) dans l'onglet « Liste des AESH » : {', '.join(ajouts)}")
        print("   Relancer « python aesh.py saisie --google » pour créer leur onglet de saisie.")
    avec_remarque = [d["nom_complet"] for d in collecte.values() if d["remarques"]]
    if avec_remarque:
        print(f"\n📝 Remarques laissées par : {', '.join(avec_remarque)}")

    collecter_difficultes(args.annee, classeur.client)


def collecter_difficultes(annee, client):
    """Relit le classeur des difficultés élèves, s'il a été créé. Silencieux sinon."""
    chemin_desc = dossier_aesh(annee) / "classeur_besoins.json"
    if not chemin_desc.exists():
        print("\nℹ Classeur des difficultés élèves non créé — « python aesh.py besoins --google » "
              "quand vous voudrez l'ajouter.")
        return
    desc = json.loads(chemin_desc.read_text(encoding="utf-8"))
    titre, info = next(iter(desc["onglets"].items()))
    r = info["reperes"]
    classeur = client.open_by_key(desc["id"])
    valeurs = classeur.values_batch_get(
        [plage_a1(titre, r["notes"]),
         plage_a1(titre, {"startRowIndex": r["notes"]["startRowIndex"],
                          "endRowIndex": r["notes"]["endRowIndex"]}, colonnes=(0, 1))],
        params={"valueRenderOption": "UNFORMATTED_VALUE"})["valueRanges"]
    notes_lues, noms_lus = (valeurs[0].get("values") or []), (valeurs[1].get("values") or [])

    familles = r["familles"]
    difficultes, notes_totales = {}, 0
    for i, nom_attendu in enumerate(r["eleves"]):
        nom = str(cellule(noms_lus, i, 0) or "").strip() or nom_attendu
        par_famille = {}
        for j, famille in enumerate(familles):
            note = nombre(str(cellule(notes_lues, i, j) or ""))
            if note:
                par_famille[famille] = int(note)
                notes_totales += 1
        difficultes[nom] = par_famille

    renseignes = sum(1 for v in difficultes.values() if v)
    print(f"\n📗 Difficultés élèves : {renseignes} / {len(difficultes)} élève(s) renseigné(s), "
          f"{notes_totales} note(s) au total")
    manquants = [nom for nom, v in difficultes.items() if not v]
    if manquants:
        print(f"   ⚠ Aucun besoin noté pour {len(manquants)} élève(s) : {', '.join(manquants[:6])}"
              + (" …" if len(manquants) > 6 else ""))
        print("     (tous leurs créneaux seront traités comme neutres par le calcul d'affectation)")

    chemin = dossier_aesh(annee) / "difficultes.json"
    chemin.write_text(json.dumps({
        "collecte_le": datetime.now().isoformat(timespec="seconds"),
        "classeur": {"id": desc["id"], "url": desc["url"]},
        "familles": familles, "eleves": difficultes,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 {chemin.relative_to(RACINE)}")


# ───────────────────────────── Programme principal ─────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--annee", default=ANNEE_DEFAUT, help="dossier d'année scolaire (défaut : %(default)s)")
    sous = ap.add_subparsers(dest="commande", metavar="<commande>")

    p = sous.add_parser("matieres", help="référentiel des matières (libellés ProNote → familles)")
    p.set_defaults(fonction=cmd_matieres)

    p = sous.add_parser("liste", help="liste des AESH depuis le fichier de notifications")
    p.add_argument("--etablissement", default=ETABLISSEMENT_DEFAUT,
                   help="ne retenir que les AESH dont l'établissement contient ce texte "
                        "(défaut : %(default)s ; passer \"\" pour tout le PIAL)")
    p.set_defaults(fonction=cmd_liste)

    p = sous.add_parser("saisie", help="classeur de recueil des disponibilités et affinités des AESH")
    p.add_argument("--google", action="store_true", help="créer le classeur (sinon aperçu local uniquement)")
    p.add_argument("--partager", action="append", default=[], metavar="EMAIL",
                   help="partager en écriture avec cet e-mail (répétable)")
    p.add_argument("--partager-aesh", action="store_true",
                   help="partager aussi avec chaque AESH, au courriel figurant dans aesh.csv")
    p.add_argument("--plage", default=None, metavar="DÉBUT-FIN",
                   help="amplitude horaire de la grille, ex. 7-19 (défaut : déduite des cours des élèves)")
    p.add_argument("--echeance", default="", metavar="DATE",
                   help="date limite affichée dans le classeur, ex. \"vendredi 2 octobre\"")
    p.add_argument("--nom", default=None, help="nom du classeur (défaut : Saisie_AESH_<année>)")
    p.set_defaults(fonction=cmd_saisie)

    p = sous.add_parser("besoins", help="classeur des difficultés des élèves par famille de matières")
    p.add_argument("--google", action="store_true", help="créer le classeur (sinon aperçu local uniquement)")
    p.add_argument("--partager", action="append", default=[], metavar="EMAIL",
                   help="partager en écriture — coordination uniquement (répétable)")
    p.add_argument("--nom", default=None, help="nom du classeur (défaut : Besoins_Eleves_<année>)")
    p.set_defaults(fonction=cmd_besoins)

    p = sous.add_parser("collecte", help="relire le classeur de saisie : disponibilités, affinités, liste")
    p.add_argument("--classeur", default=None, metavar="URL",
                   help="URL du classeur à relire (défaut : celui de <année>/aesh/classeur_saisie.json)")
    p.set_defaults(fonction=cmd_collecte)

    args = ap.parse_args()
    if not args.commande:
        ap.print_help()
        return 1
    args.fonction(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
