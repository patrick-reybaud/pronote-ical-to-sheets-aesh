#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aesh_saisie.py — classeur de recueil des disponibilités et des affinités des AESH (étape 1).

Un onglet « Mode d'emploi » puis un onglet par AESH, contenant trois blocs :

  1. disponibilités    grille Lundi→Vendredi en demi-heures, une case à cocher par créneau,
                       totaux par jour et comparaison automatique à la quotité de service ;
  2. affinités         une note de 1 à 5 par famille de matières (vide = neutre) ;
  3. remarques         texte libre (déplacements, temps cantine, contraintes particulières).

Tout l'onglet est verrouillé sauf ces trois zones : les AESH ne peuvent ni déformer la grille
ni effacer les formules. Voir construire_onglet_aesh() pour le détail des plages laissées ouvertes.

Module appelé par `python aesh.py saisie` — pas d'exécution directe.
"""

from noyau import (JOURS, NB_LIGNES_ENTETE, PAS_MINUTES, SEP_FORMULE, nombre_formule,
                   COULEUR_ALERTE, COULEUR_COCHEE)

LARGEUR_COL_JOUR_SAISIE = 112
LARGEUR_COL_LIBELLE = 230
HAUTEUR_LIGNE_SAISIE = 21
NB_LIGNES_REMARQUES = 4
NOTE_MIN, NOTE_MAX = 1, 5


def colonne_a1(index):
    """0 → « A », 1 → « B »… (les grilles de saisie ne dépassent jamais la colonne Z)."""
    return chr(ord("A") + index)


def libelle_creneau(minutes):
    return f"{minutes // 60}h{minutes % 60:02d}"


# ───────────────────────────── Onglet d'un AESH ─────────────────────────────

def construire_onglet_aesh(aesh, familles, h_min, h_max, annee, echeance=""):
    """
    Modèle d'onglet de saisie pour un AESH, au format attendu par requetes_onglet() / rendre_html().

    « lignes » porte un libellé lisible (pour l'aperçu HTML) et « valeurs » la vraie valeur Google
    (case à cocher ou formule) — voir requetes_onglet() dans noyau.py.
    """
    nb_cols = 1 + len(JOURS)
    nb_creneaux = (h_max - h_min) * 60 // PAS_MINUTES
    quotite = aesh["quotite_h"]

    lignes, fusions, styles, valeurs = [], [], {}, {}

    def ajouter(textes=None, style_col0=None, fusionner=False, style=None):
        r = len(lignes)
        lignes.append(list(textes) + [""] * (nb_cols - len(textes)) if textes else [""] * nb_cols)
        if fusionner:
            fusions.append((r, r + 1, 0, nb_cols))
        if style_col0:
            styles[(r, 0)] = style_col0
        if style:
            for c in range(nb_cols):
                styles[(r, c)] = style
        return r

    # ── Titre
    ajouter([f"{aesh['nom_complet']} — disponibilités {annee}"], "titre", fusionner=True)
    quotite_texte = f"{quotite:g} h/semaine" if quotite else "quotité non renseignée"
    ajouter([f"Quotité de service : {quotite_texte}."
             + (f" Merci de remplir avant le {echeance}." if echeance else "")
             + " Seules les cases jaunes sont modifiables."], "sous_titre", fusionner=True)
    ajouter()

    # ── 1. Disponibilités
    ajouter(["1 · VOS DISPONIBILITÉS"], "section", fusionner=True)
    ajouter(["Cochez chaque demi-heure où vous êtes disponible pour accompagner un élève. "
             "Les totaux se calculent tout seuls : le message à droite vous dit s'il vous reste des heures à poser."],
            "consigne", fusionner=True)
    r = ajouter(["Horaires"] + list(JOURS))
    for c in range(nb_cols):
        styles[(r, c)] = "entete"

    premiere_grille = len(lignes)
    for s in range(nb_creneaux):
        debut = h_min * 60 + s * PAS_MINUTES
        r = ajouter([f"{libelle_creneau(debut)} - {libelle_creneau(debut + PAS_MINUTES)}"], "horaire")
        for c in range(1, nb_cols):
            lignes[r][c] = "☐"                       # aperçu HTML
            valeurs[(r, c)] = {"boolValue": False}   # vraie case à cocher dans Google Sheets
            styles[(r, c)] = "case"
    derniere_grille = len(lignes) - 1

    # Totaux par jour, puis bilan hebdomadaire. Noms de fonctions en anglais, mais séparateur
    # d'arguments imposé par la locale du classeur — voir SEP_FORMULE dans noyau.py.
    a1_debut, a1_fin = premiere_grille + 1, derniere_grille + 1
    r_totaux = ajouter(["Total par jour"], "total_libelle")
    for c in range(1, nb_cols):
        lettre = colonne_a1(c)
        lignes[r_totaux][c] = "— h"
        valeurs[(r_totaux, c)] = {"formulaValue":
                                  f"=COUNTIF({lettre}{a1_debut}:{lettre}{a1_fin}{SEP_FORMULE}TRUE)/2"}
        styles[(r_totaux, c)] = "total"

    r_bilan = ajouter(["Total semaine"], "total_libelle")
    lignes[r_bilan][1] = "— h"
    valeurs[(r_bilan, 1)] = {"formulaValue": f"=SUM(B{r_totaux + 1}:{colonne_a1(nb_cols - 1)}{r_totaux + 1})"}
    styles[(r_bilan, 1)] = "total"
    cellule_total = f"B{r_bilan + 1}"
    if quotite:
        q, sep = nombre_formule(quotite), SEP_FORMULE
        message = (f'=IF({cellule_total}=0{sep}""{sep}'
                   f'IF({cellule_total}>{q}{sep}"⚠ vous avez coché plus que votre quotité de {q} h"{sep}'
                   f'IF({cellule_total}<{q}{sep}"il reste "&({q}-{cellule_total})&" h à poser"{sep}'
                   f'"✓ compte juste")))')
    else:
        message = f'=IF({cellule_total}=0{SEP_FORMULE}""{SEP_FORMULE}"quotité de service non renseignée")'
    lignes[r_bilan][2] = f"(sur {quotite:g} h)" if quotite else "(quotité inconnue)"
    valeurs[(r_bilan, 2)] = {"formulaValue": message}
    fusions.append((r_bilan, r_bilan + 1, 2, nb_cols))
    styles[(r_bilan, 2)] = "consigne"
    ajouter()

    # ── 2. Affinités par matière
    ajouter(["2 · MATIÈRES OÙ VOUS ÊTES LE PLUS À L'AISE"], "section", fusionner=True)
    ajouter([f"Notez de {NOTE_MIN} à {NOTE_MAX} les matières que vous vous sentez le mieux à même d'accompagner "
             f"({NOTE_MAX} = tout à fait à l'aise). Laissez vide si vous n'avez pas de préférence : "
             "une case vide ne vous pénalise pas."], "consigne", fusionner=True)
    r = ajouter(["Matière", f"Aisance ({NOTE_MIN} à {NOTE_MAX})"])
    styles[(r, 0)] = styles[(r, 1)] = "entete"
    premiere_affinite = len(lignes)
    for famille in familles:
        r = ajouter([famille], "libelle")
        styles[(r, 1)] = "saisie"
    derniere_affinite = len(lignes) - 1
    ajouter()

    # ── 3. Remarques
    ajouter(["3 · REMARQUES"], "section", fusionner=True)
    ajouter(["Déplacements entre établissements, temps de cantine, contraintes de transport, "
             "élèves déjà suivis l'an dernier, tout ce qui nous aiderait à construire votre emploi du temps."],
            "consigne", fusionner=True)
    premiere_remarque = len(lignes)
    for _ in range(NB_LIGNES_REMARQUES):
        ajouter()
    fusions.append((premiere_remarque, premiere_remarque + NB_LIGNES_REMARQUES, 0, nb_cols))
    styles[(premiere_remarque, 0)] = "saisie_texte"

    # ── Zones laissées modifiables ; tout le reste de l'onglet est verrouillé
    grille = {"startRowIndex": premiere_grille, "endRowIndex": derniere_grille + 1,
              "startColumnIndex": 1, "endColumnIndex": nb_cols}
    affinites = {"startRowIndex": premiere_affinite, "endRowIndex": derniere_affinite + 1,
                 "startColumnIndex": 1, "endColumnIndex": 2}
    remarques = {"startRowIndex": premiere_remarque, "endRowIndex": premiere_remarque + NB_LIGNES_REMARQUES,
                 "startColumnIndex": 0, "endColumnIndex": nb_cols}

    return {
        "titre": aesh["nom_complet"],
        "id_aesh": aesh["id"],
        "lignes": lignes, "fusions": fusions, "styles": styles, "valeurs": valeurs, "nb_cols": nb_cols,
        "largeurs": [(0, 1, LARGEUR_COL_LIBELLE), (1, nb_cols, LARGEUR_COL_JOUR_SAISIE)],
        "figees": NB_LIGNES_ENTETE,
        "validations": [
            {"plage": grille, "regle": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}},
            {"plage": affinites, "regle": {
                "condition": {"type": "ONE_OF_LIST",
                              "values": [{"userEnteredValue": str(n)} for n in range(NOTE_MIN, NOTE_MAX + 1)]},
                "showCustomUi": True, "strict": True,
                "inputMessage": f"Laissez vide si neutre, sinon {NOTE_MIN} à {NOTE_MAX}"}},
        ],
        "formats_conditionnels": [
            {"plages": [grille], "regle": {
                "condition": {"type": "CUSTOM_FORMULA",
                              "values": [{"userEnteredValue": f"=B{premiere_grille + 1}=TRUE"}]},
                "format": {"backgroundColor": COULEUR_COCHEE}}},
            {"plages": [{"startRowIndex": r_bilan, "endRowIndex": r_bilan + 1,
                         "startColumnIndex": 1, "endColumnIndex": 2}],
             "regle": {"condition": {"type": "NUMBER_GREATER", "values": [{"userEnteredValue": nombre_formule(quotite)}]},
                       "format": {"backgroundColor": COULEUR_ALERTE}}} if quotite else None,
        ],
        "protections": [{"description": f"Saisie {aesh['nom_complet']} — grille verrouillée",
                         "ouvertes": [grille, affinites, remarques]}],
        "hauteur_ligne": HAUTEUR_LIGNE_SAISIE,
        "premiere_grille": premiere_grille,
        # Repères relus par la collecte (étape « collecte ») — évite de redécouvrir la mise en page
        "reperes": {"grille": grille, "affinites": affinites, "remarques": remarques,
                    "familles": list(familles), "h_min": h_min, "h_max": h_max},
    }


# ───────────────────────────── Onglet « Liste des AESH » ─────────────────────────────

NB_LIGNES_AJOUT = 3        # lignes vides pour déclarer une arrivée en cours d'année
COLONNES_LISTE = [
    ("AESH", 220, False),                    # (en-tête, largeur, modifiable)
    ("Actif", 70, True),
    ("Quotité retenue (h/sem.)", 130, True),
    ("Dispositif collectif (ULIS)", 130, True),
    ("Courriel", 240, True),
    ("Établissement", 250, False),
    ("EPP", 60, False),                      # colonnes d'origine, en lecture seule : elles servent
    ("SCO", 60, False),                      # de repère pour justifier la quotité retenue
    ("AESH Co", 70, False),
]


def construire_onglet_liste_aesh(aesh_liste, annee):
    """
    Onglet de pilotage de la liste des AESH : c'est ici que la coordination corrige les quotités,
    les courriels, désactive une personne partie ou déclare une arrivée, sans ouvrir de tableur local.
    Les colonnes issues du fichier académique restent verrouillées, comme repère.
    """
    nb_cols = len(COLONNES_LISTE)
    lignes, fusions, styles, valeurs = [], [], {}, {}

    def ajouter(textes=None):
        r = len(lignes)
        lignes.append(list(textes) + [""] * (nb_cols - len(textes)) if textes else [""] * nb_cols)
        return r

    r = ajouter([f"Liste des AESH — {annee}"])
    fusions.append((r, r + 1, 0, nb_cols))
    styles[(r, 0)] = "titre"
    r = ajouter(["Corrigez ici ce qui doit l'être : quotité réellement disponible, courriel, départ (Actif = non), "
                 "arrivée (lignes vides en bas). Les colonnes grises viennent du fichier académique et ne sont pas "
                 "modifiables. Après un ajout, relancez « aesh.py saisie » pour créer l'onglet de la personne."])
    fusions.append((r, r + 1, 0, nb_cols))
    styles[(r, 0)] = "sous_titre"
    ajouter()

    r_entete = ajouter([c[0] for c in COLONNES_LISTE])
    for c in range(nb_cols):
        styles[(r_entete, c)] = "entete"

    premiere = len(lignes)
    for a in aesh_liste:
        r = ajouter([a["nom_complet"],
                     a.get("actif", "oui"),
                     f"{a['quotite_h']:g}" if a["quotite_h"] else "",
                     "oui" if a.get("est_co") else "non",
                     a.get("email", ""),
                     a.get("etablissement", ""),
                     a.get("quotite_epp", ""), a.get("quotite_sco", ""), a.get("quotite_co", "")])
        # La quotité doit être un NOMBRE : écrite en texte, elle serait ignorée par le SUMIF du total
        # et refusée par la validation numérique de la colonne.
        if a["quotite_h"]:
            valeurs[(r, 2)] = {"numberValue": a["quotite_h"]}
        styles[(r, 0)] = "libelle"
        for c in range(1, 5):
            styles[(r, c)] = "saisie"
        for c in range(5, nb_cols):
            styles[(r, c)] = "total"        # gris : lecture seule
    derniere = len(lignes) - 1

    premiere_ajout = len(lignes)
    for _ in range(NB_LIGNES_AJOUT):
        r = ajouter()
        for c in range(0, 5):
            styles[(r, c)] = "saisie"
    derniere_ajout = len(lignes) - 1

    r_total = ajouter(["Total des AESH actifs"])
    styles[(r_total, 0)] = "total_libelle"
    lignes[r_total][2] = "— h"
    valeurs[(r_total, 2)] = {"formulaValue":
                             f'=SUMIF(B{premiere + 1}:B{derniere_ajout + 1}{SEP_FORMULE}"oui"'
                             f'{SEP_FORMULE}C{premiere + 1}:C{derniere_ajout + 1})'}
    styles[(r_total, 2)] = "total"
    for c in (1, 3, 4):
        styles[(r_total, c)] = "total"

    modifiables = {"startRowIndex": premiere, "endRowIndex": derniere + 1,
                   "startColumnIndex": 1, "endColumnIndex": 5}
    ajouts = {"startRowIndex": premiere_ajout, "endRowIndex": derniere_ajout + 1,
              "startColumnIndex": 0, "endColumnIndex": 5}
    toutes_lignes = {"startRowIndex": premiere, "endRowIndex": derniere_ajout + 1}
    oui_non = {"condition": {"type": "ONE_OF_LIST",
                             "values": [{"userEnteredValue": v} for v in ("oui", "non")]},
               "showCustomUi": True, "strict": True}

    return {
        "titre": "Liste des AESH",
        "lignes": lignes, "fusions": fusions, "styles": styles, "valeurs": valeurs, "nb_cols": nb_cols,
        "largeurs": [(i, i + 1, c[1]) for i, c in enumerate(COLONNES_LISTE)],
        "figees": r_entete + 1,
        "bordures": r_entete,
        "validations": [
            {"plage": {**toutes_lignes, "startColumnIndex": 1, "endColumnIndex": 2}, "regle": oui_non},
            {"plage": {**toutes_lignes, "startColumnIndex": 3, "endColumnIndex": 4}, "regle": oui_non},
            {"plage": {**toutes_lignes, "startColumnIndex": 2, "endColumnIndex": 3}, "regle": {
                "condition": {"type": "NUMBER_BETWEEN",
                              "values": [{"userEnteredValue": "0"}, {"userEnteredValue": "40"}]},
                "showCustomUi": True, "strict": True,
                "inputMessage": "Quotité hebdomadaire en heures (0 à 40)"}},
        ],
        "protections": [{"description": "Liste des AESH — colonnes d'origine verrouillées",
                         "ouvertes": [modifiables, ajouts]}],
        "reperes": {"lignes_aesh": {"startRowIndex": premiere, "endRowIndex": derniere_ajout + 1},
                    "colonnes": [c[0] for c in COLONNES_LISTE]},
    }


# ───────────────────────────── Onglet « Mode d'emploi » ─────────────────────────────

def construire_onglet_mode_emploi(aesh_liste, annee, h_min, h_max, echeance=""):
    nb_cols = 2
    lignes, fusions, styles = [], [], {}

    def ajouter(textes=None, style=None, fusionner=True):
        r = len(lignes)
        lignes.append(list(textes) + [""] * (nb_cols - len(textes)) if textes else [""] * nb_cols)
        if fusionner:
            fusions.append((r, r + 1, 0, nb_cols))
        if style:
            styles[(r, 0)] = style
        return r

    ajouter([f"Disponibilités des AESH — {annee}"], "titre")
    ajouter(["Merci de remplir l'onglet qui porte votre nom, en bas de la fenêtre."], "sous_titre")
    ajouter(fusionner=False)
    ajouter(["CE QU'IL Y A À FAIRE"], "section")
    for texte in [
        "1 · Ouvrez l'onglet à votre nom (les onglets sont en bas de l'écran).",
        f"2 · Dans la grille, cochez chaque demi-heure où vous êtes disponible, entre {h_min}h et {h_max}h.",
        "     Un clic dans la case suffit ; vous pouvez aussi cocher une case puis faire glisser vers le bas.",
        "3 · Vérifiez le « Total semaine » : il doit correspondre à votre quotité de service.",
        "4 · Notez de 1 à 5 les matières que vous êtes le plus à l'aise d'accompagner. "
        "Laissez vide si vous n'avez pas de préférence — une case vide ne vous pénalise pas.",
        "5 · Ajoutez vos remarques dans le dernier bloc.",
    ]:
        ajouter([texte], "libelle")
    ajouter(fusionner=False)

    ajouter(["BON À SAVOIR"], "section")
    for texte in [
        "· Seules les cases jaunes et les cases à cocher sont modifiables : le reste de l'onglet est verrouillé "
        "pour éviter d'effacer les formules par mégarde.",
        "· Cocher un créneau ne veut pas dire que vous y serez affecté : c'est la disponibilité maximale "
        "à partir de laquelle l'emploi du temps sera construit.",
        "· Les affinités par matière servent à mieux vous placer, pas à vous évaluer.",
        "· Vos réponses sont visibles par les autres AESH de l'établissement et par la coordination.",
        "· Rien à enregistrer : Google Sheets enregistre au fur et à mesure.",
    ]:
        ajouter([texte], "libelle")
    ajouter(fusionner=False)

    if echeance:
        ajouter([f"À REMPLIR AVANT LE {echeance.upper()}"], "section")
        ajouter(fusionner=False)

    ajouter(["ONGLETS DE CE CLASSEUR"], "section")
    r = ajouter(["AESH", "Quotité de service"], fusionner=False)
    styles[(r, 0)] = styles[(r, 1)] = "entete"
    for a in aesh_liste:
        r = ajouter([a["nom_complet"], f"{a['quotite_h']:g} h/semaine" if a["quotite_h"] else "non renseignée"],
                    "libelle", fusionner=False)
        styles[(r, 1)] = "libelle"

    return {"titre": "Mode d'emploi", "lignes": lignes, "fusions": fusions, "styles": styles,
            "nb_cols": nb_cols, "largeurs": [(0, 1, 620), (1, 2, 160)],
            "protections": [{"description": "Mode d'emploi — lecture seule", "ouvertes": []}]}


def construire_onglets(aesh_liste, familles, h_min, h_max, annee, echeance=""):
    """Classeur complet : mode d'emploi, liste des AESH (pilotage), puis un onglet par AESH."""
    onglets = [construire_onglet_mode_emploi(aesh_liste, annee, h_min, h_max, echeance),
               construire_onglet_liste_aesh(aesh_liste, annee)]
    for a in aesh_liste:
        onglet = construire_onglet_aesh(a, familles, h_min, h_max, annee, echeance)
        onglet["formats_conditionnels"] = [f for f in onglet["formats_conditionnels"] if f]
        onglets.append(onglet)
    return onglets
