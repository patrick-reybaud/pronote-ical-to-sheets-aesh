#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pial.py — lecture du fichier de gestion du PIAL (élèves notifiés + moyens AESH).

Un seul classeur porte les deux populations, dans deux onglets. Les intitulés de colonnes changent
d'une année et d'une académie à l'autre : tout est retrouvé par mots-clés (voir tableur.Entetes),
et ce qui n'a pas pu l'être est remonté en avertissement plutôt que de faire échouer l'import.
"""

import re
import unicodedata
from datetime import datetime

from .tableur import Entetes, compacter, lire_classeur, trouver_onglet

COLONNES_ELEVES = {
    "nom": [["NOM", "ELEVE"], ["NOM", "PRENOM"], ["ELEVE"]],
    "dob": [["DATE", "NAISSANCE"], ["NE LE"]],
    "etablissement": [["ETABLISSEMENT", "2026"], ["ETABLISSEMENT", "2027"],
                      ["ETABLISSEMENT", "SCOLARISATION"], ["ETABLISSEMENT"]],
    "niveau": [["NIVEAU", "CLASSE"], ["NIVEAU"]],
    "type_aide": [["TYPE", "AIDE"]],
    "heures": [["HEURES", "ATTRIBUEES"], ["HEURES"]],
    "notif_debut": [["DATE", "DEBUT"]],
    "notif_fin": [["DATE", "FIN"]],
    "remarques": [["REMARQUES"]],
    "etat": [["ETAT", "NOTIFICATION"]],
    "cantine": [["TYPE", "AIDE", "CANTINE"], ["PRISE", "CHARGE", "CANTINE"]],
}

COLONNES_AESH = {
    "nom": [["NOM", "PRENOM", "AESH"], ["NOM", "AESH"], ["NOM", "PRENOM"]],
    "dob": [["DATE", "NAISSANCE"]],
    "etablissement": [["NOM", "ETABLISSEMENT"], ["ETABLISSEMENT"]],
    "quotite_sco": [["QUOTITE", "SCO"]],
    "quotite_epp": [["QUOTITE", "EPP"]],
    "quotite_co": [["QUOTITE", "AESH", "CO"]],
    "quotite_cantine": [["QUOTITE", "TEMPS", "CANTINE"]],
    "email": [["MEL"], ["COURRIEL"], ["MAIL"]],
    "telephone": [["TELEPHONE"]],
}

# Types d'aide humaine, tels qu'ils sont saisis (casse et libellés variables)
TYPES_AIDE = {"I": "individuelle", "M": "mutualisée", "CO": "collective"}


def identifiant(texte, deja_pris):
    base = re.sub(r"[^a-z0-9]+", "_", compacter(texte).lower()).strip("_") or "sans_nom"
    ident, n = base, 2
    while ident in deja_pris:
        ident, n = f"{base}_{n}", n + 1
    deja_pris.add(ident)
    return ident


def parser_date(texte):
    texte = (texte or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texte, fmt).date()
        except ValueError:
            pass
    return None


def nombre(texte):
    try:
        return float(str(texte or "").replace(",", ".").replace(" ", "").strip())
    except ValueError:
        return None


def normaliser_type_aide(texte):
    """« i », « I », « M », « CO », « Mutualisée »… → « I » / « M » / « CO » / ''."""
    compact = compacter(texte)
    if not compact:
        return ""
    if compact.startswith("CO") or "COLLECT" in compact:
        return "CO"
    if compact.startswith("M") or "MUTUAL" in compact:
        return "M"
    if compact.startswith("I") or "INDIVID" in compact:
        return "I"
    return ""


def quotite_de_service(sco, co, epp):
    """
    Quotité hebdomadaire retenue et colonne d'origine. « SCO » est le temps devant élèves et fait foi ;
    les AESH d'un dispositif collectif (ULIS) n'ont qu'une quotité « AESH Co » ; « EPP » en dernier recours.
    """
    for valeur, origine in ((sco, "SCO"), (co, "AESH Co"), (epp, "EPP")):
        if valeur is not None:
            return valeur, origine
    return None, ""


# ───────────────────────────── Lecture ─────────────────────────────

def lire_pial(chemin):
    """
    Retourne {"eleves", "aesh", "etablissements", "avertissements", "onglets"}.

    Les avertissements décrivent ce qui a été deviné, ignoré ou n'a pas été trouvé : c'est ce que
    l'écran d'import affiche pour que l'utilisateur sache à quoi s'en tenir avant de continuer.
    """
    onglets = lire_classeur(chemin)
    avertissements = []

    nom_eleves = trouver_onglet(onglets, "Besoins_élèves", "Besoins eleves", "eleves", obligatoire=False)
    nom_aesh = trouver_onglet(onglets, "Moyens_AESH_terrain", "Moyens AESH", "AESH", obligatoire=False)
    if not nom_eleves:
        raise ValueError("Aucun onglet d'élèves notifiés trouvé (attendu : « Besoins_élèves »). "
                         f"Onglets présents : {', '.join(onglets)}")
    if not nom_aesh:
        avertissements.append("Aucun onglet AESH trouvé (attendu : « Moyens_AESH_terrain ») — "
                              "la liste des accompagnants devra être saisie à la main.")

    eleves = _lire_eleves(onglets[nom_eleves], avertissements)
    aesh = _lire_aesh(onglets[nom_aesh], avertissements) if nom_aesh else []

    etablissements = {}
    for personne, cle in [(e, "eleves") for e in eleves] + [(a, "aesh") for a in aesh]:
        nom = personne["etablissement"] or "(établissement non renseigné)"
        etablissements.setdefault(nom, {"nom": nom, "eleves": 0, "aesh": 0})[cle] += 1
    classes = sorted(etablissements.values(), key=lambda e: (-e["eleves"] - e["aesh"], e["nom"]))

    return {"eleves": eleves, "aesh": aesh, "etablissements": classes,
            "avertissements": avertissements, "onglets": list(onglets)}


def colonne_annee_la_plus_recente(entetes, motif="ETABLISSEMENT"):
    """
    Indice de la colonne « <motif> » portant l'année la plus récente.

    Le fichier PIAL garde la colonne de l'année passée à côté de celle de l'année en cours
    (« Etablissement de scolarisation 2025-2026 » et « Etablissement 2026-2027ate ») : une recherche
    par mots-clés tombe sur la première. On départage par l'année citée dans l'intitulé, ce qui
    reste juste l'an prochain sans rien modifier.
    """
    candidats = []
    for i, libelle in enumerate(entetes.libelles):
        compact = compacter(libelle)
        if motif not in compact:
            continue
        annees = [int(a) for a in re.findall(r"\b(20\d{2})\b", compact)]
        candidats.append((max(annees) if annees else 0, i))
    if not candidats:
        return None
    return max(candidats)[1]


def _lire_eleves(lignes, avertissements):
    entetes = Entetes(lignes, COLONNES_ELEVES)
    recente = colonne_annee_la_plus_recente(entetes)
    if recente is not None and recente != entetes.index.get("etablissement"):
        ancienne = entetes.index.get("etablissement")
        entetes.index["etablissement"] = recente
        if ancienne is not None:
            avertissements.append(
                f"Élèves — établissement lu dans « {entetes.libelles[recente]} » "
                f"(et non « {entetes.libelles[ancienne]} », qui concerne l'année précédente).")
    if entetes.manquantes:
        avertissements.append("Élèves — colonnes non reconnues : " + ", ".join(entetes.manquantes))
    if entetes.ligne_entete > 0:
        avertissements.append(f"Élèves — en-tête détecté à la ligne {entetes.ligne_entete + 1} "
                              f"({entetes.ligne_entete} ligne(s) ignorée(s) au-dessus).")
    eleves, deja_pris, sans_date, sans_heures = [], set(), 0, 0
    for ligne in entetes.donnees:
        nom = re.sub(r"\s+", " ", entetes.valeur(ligne, "nom"))
        if not nom or compacter(nom) in ("NOM PRENOM ELEVE", "TOTAL"):
            continue
        dob = parser_date(entetes.valeur(ligne, "dob"))
        heures = nombre(entetes.valeur(ligne, "heures"))
        if dob is None:
            sans_date += 1
        if heures is None:
            sans_heures += 1
        eleves.append({
            "id": identifiant(nom, deja_pris),
            "nom_complet": nom,
            "dob": dob.isoformat() if dob else None,
            "dob_texte": entetes.valeur(ligne, "dob"),
            "etablissement": entetes.valeur(ligne, "etablissement"),
            "niveau": entetes.valeur(ligne, "niveau"),
            "classe": entetes.valeur(ligne, "remarques"),   # la classe est souvent notée là
            "type_aide": normaliser_type_aide(entetes.valeur(ligne, "type_aide")),
            "type_aide_brut": entetes.valeur(ligne, "type_aide"),
            "heures": heures or 0.0,
            "notif_debut": entetes.valeur(ligne, "notif_debut"),
            "notif_fin": entetes.valeur(ligne, "notif_fin"),
            "etat": entetes.valeur(ligne, "etat"),
            "cantine": entetes.valeur(ligne, "cantine"),
            "remarques": entetes.valeur(ligne, "remarques"),
        })
    if sans_date:
        avertissements.append(f"Élèves — {sans_date} date(s) de naissance illisible(s) : "
                              "ces élèves ne pourront pas être rapprochés d'un emploi du temps.")
    if sans_heures:
        avertissements.append(f"Élèves — {sans_heures} quotité(s) horaire(s) absente(s) ou illisible(s).")
    return eleves


def _lire_aesh(lignes, avertissements):
    entetes = Entetes(lignes, COLONNES_AESH)
    if entetes.manquantes:
        avertissements.append("AESH — colonnes non reconnues : " + ", ".join(entetes.manquantes))
    aesh, deja_pris, mails_douteux, ecarts = [], set(), [], []
    for ligne in entetes.donnees:
        nom = re.sub(r"\s+", " ", entetes.valeur(ligne, "nom"))
        if not nom or compacter(nom).startswith("NOM PRENOM AESH"):
            continue
        sco = nombre(entetes.valeur(ligne, "quotite_sco"))
        epp = nombre(entetes.valeur(ligne, "quotite_epp"))
        co = nombre(entetes.valeur(ligne, "quotite_co"))
        quotite, origine = quotite_de_service(sco, co, epp)
        email = entetes.valeur(ligne, "email")
        if email and "@" not in email:
            mails_douteux.append(f"{nom} (« {email} »)")
            email = ""
        if sco is not None and epp is not None and sco != epp:
            ecarts.append(f"{nom} : EPP {epp:g} h ≠ SCO {sco:g} h")
        aesh.append({
            "id": identifiant(nom, deja_pris),
            "nom_complet": nom,
            "etablissement": entetes.valeur(ligne, "etablissement"),
            "quotite": quotite or 0.0,
            "quotite_origine": origine,
            "quotite_sco": sco, "quotite_epp": epp, "quotite_co": co,
            "quotite_cantine": nombre(entetes.valeur(ligne, "quotite_cantine")),
            "est_co": sco is None and co is not None,
            "email": email,
            "telephone": entetes.valeur(ligne, "telephone"),
            "actif": True,
        })
    if mails_douteux:
        avertissements.append("AESH — la colonne courriel contient autre chose qu'une adresse pour : "
                              + ", ".join(mails_douteux[:5]) + (" …" if len(mails_douteux) > 5 else ""))
    if ecarts:
        avertissements.append(f"AESH — {len(ecarts)} écart(s) entre quotité EPP et SCO (c'est la SCO qui est "
                              "retenue) : " + ", ".join(ecarts[:4]) + (" …" if len(ecarts) > 4 else ""))
    return aesh
