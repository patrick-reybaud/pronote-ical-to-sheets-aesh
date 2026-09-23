#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export.py — classeur de recueil des disponibilités, réimport, et publication des emplois du temps.

Le classeur de recueil est volontairement au format .xlsx : il s'ouvre aussi bien dans Excel que
dans LibreOffice ou Google Sheets, il peut circuler par courriel comme être déposé sur un Drive, et
il revient dans l'application par le même chemin quel qu'ait été le trajet. L'application ne dépend
donc d'aucun service en ligne — mais n'en interdit aucun.

La mise en page du recueil est décrite une seule fois (DISPOSITION) et sert autant à l'écriture
qu'à la relecture : impossible que les deux divergent.
"""

import html
import re
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .matieres import FAMILLES
from .pronote import JOURS, PAS_MINUTES

MARQUE = "X"
DISPOSITION = {
    "ligne_titre": 1, "ligne_consigne": 2, "ligne_entete": 4, "premiere_ligne_grille": 5,
    "colonne_horaires": 1, "premiere_colonne_jour": 2,
    "lignes_avant_affinites": 2,        # lignes vides entre la grille et le bloc affinités
}
JOURS_SEMAINE = JOURS[:5]

_BLEU = PatternFill("solid", fgColor="D9E8FA")
_JAUNE = PatternFill("solid", fgColor="FFFBE6")
_GRIS = PatternFill("solid", fgColor="EDEDED")
_VERT = PatternFill("solid", fgColor="CCE8CC")
_ENTETE = PatternFill("solid", fgColor="D9D9D9")
_BORDURE = Border(*[Side("thin", color="AAAAAA")] * 4)


def _horodatage():
    return datetime.now().strftime("%Y%m%d_%H%M")


def _libelle_creneau(h_min, indice):
    minutes = h_min * 60 + indice * PAS_MINUTES
    fin = minutes + PAS_MINUTES
    return f"{minutes // 60}h{minutes % 60:02d} - {fin // 60}h{fin % 60:02d}"


def _dossier_sortie(projet):
    dossier = projet.dossier / "sorties"
    dossier.mkdir(exist_ok=True)
    return dossier


# ───────────────────────────── Classeur de recueil ─────────────────────────────

def classeur_recueil(projet):
    """Un onglet par AESH actif : grille des disponibilités à cocher, puis affinités par matière."""
    population = projet.population()
    desactives = set(projet.etat.get("aesh_desactives", []))
    aesh = [a for a in population["aesh"] if a["id"] not in desactives]
    if not aesh:
        raise ValueError("Aucun AESH actif pour cet établissement : rien à recueillir.")
    h_min, h_max = projet.etat.get("plage") or (8, 18)
    nb_creneaux = (h_max - h_min) * 60 // PAS_MINUTES

    classeur = Workbook()
    classeur.remove(classeur.active)
    mode = classeur.create_sheet("Mode d'emploi")
    _remplir_mode_emploi(mode, aesh, h_min, h_max)

    for personne in aesh:
        feuille = classeur.create_sheet(_titre_onglet(personne["nom_complet"], classeur.sheetnames))
        _remplir_onglet_aesh(feuille, personne, h_min, nb_creneaux)

    chemin = _dossier_sortie(projet) / f"Recueil_disponibilites_{_horodatage()}.xlsx"
    classeur.save(chemin)
    return chemin


def _titre_onglet(nom, deja_pris):
    titre = re.sub(r"[\[\]\*\?/\\:]", " ", nom).strip()[:31] or "AESH"
    base, n = titre, 2
    while titre in deja_pris:
        titre, n = f"{base[:28]} {n}", n + 1
    return titre


def _remplir_mode_emploi(feuille, aesh, h_min, h_max):
    feuille.column_dimensions["A"].width = 95
    lignes = [
        ("Recueil des disponibilités des AESH", True),
        ("", False),
        ("Chaque AESH remplit l'onglet qui porte son nom (onglets en bas de la fenêtre).", False),
        ("", False),
        (f"1 · Dans la grille, inscrivez « {MARQUE} » sur chaque demi-heure où vous êtes disponible "
         f"(plage {h_min}h – {h_max}h).", False),
        ("     Une case vide signifie « non disponible ». Vous pouvez copier-coller une colonne entière.", False),
        ("2 · Le total en bas de grille se met à jour tout seul : comparez-le à votre quotité de service.", False),
        ("3 · Notez de 1 à 5 les matières que vous êtes le plus à l'aise d'accompagner.", False),
        ("     Laissez vide si vous n'avez pas de préférence : une case vide ne vous pénalise pas.", False),
        ("4 · Ajoutez vos remarques en bas de votre onglet, puis renvoyez le fichier à la coordination.", False),
        ("", False),
        ("Cocher un créneau ne veut pas dire que vous y serez affecté : c'est la disponibilité maximale "
         "à partir de laquelle l'emploi du temps sera construit.", False),
        ("", False),
        ("Onglets de ce classeur :", True),
    ]
    for i, (texte, gras) in enumerate(lignes, start=1):
        cellule = feuille.cell(row=i, column=1, value=texte)
        cellule.font = Font(bold=gras, size=13 if i == 1 else 11)
        cellule.alignment = Alignment(wrap_text=True, vertical="center")
    for j, personne in enumerate(aesh, start=len(lignes) + 1):
        quotite = f"{personne['quotite']:g} h/semaine" if personne["quotite"] else "quotité non renseignée"
        feuille.cell(row=j, column=1, value=f"    • {personne['nom_complet']} — {quotite}")


def _remplir_onglet_aesh(feuille, personne, h_min, nb_creneaux):
    d = DISPOSITION
    quotite = f"{personne['quotite']:g} h/semaine" if personne["quotite"] else "quotité non renseignée"
    titre = feuille.cell(row=d["ligne_titre"], column=1,
                         value=f"{personne['nom_complet']} — disponibilités")
    titre.font = Font(bold=True, size=13)
    feuille.cell(row=d["ligne_consigne"], column=1,
                 value=f"Quotité de service : {quotite}. Inscrivez « {MARQUE} » sur vos créneaux disponibles.")
    feuille.cell(row=d["ligne_consigne"], column=1).font = Font(italic=True, size=9)

    feuille.column_dimensions["A"].width = 16
    entete = feuille.cell(row=d["ligne_entete"], column=d["colonne_horaires"], value="Horaires")
    entete.fill, entete.font, entete.border = _ENTETE, Font(bold=True), _BORDURE
    for j, jour in enumerate(JOURS_SEMAINE):
        colonne = d["premiere_colonne_jour"] + j
        feuille.column_dimensions[get_column_letter(colonne)].width = 12
        cellule = feuille.cell(row=d["ligne_entete"], column=colonne, value=jour)
        cellule.fill, cellule.font, cellule.border = _ENTETE, Font(bold=True), _BORDURE
        cellule.alignment = Alignment(horizontal="center")

    for s in range(nb_creneaux):
        ligne = d["premiere_ligne_grille"] + s
        cellule = feuille.cell(row=ligne, column=d["colonne_horaires"], value=_libelle_creneau(h_min, s))
        cellule.font, cellule.border = Font(size=9), _BORDURE
        for j in range(len(JOURS_SEMAINE)):
            case = feuille.cell(row=ligne, column=d["premiere_colonne_jour"] + j)
            case.fill, case.border = _JAUNE, _BORDURE
            case.alignment = Alignment(horizontal="center")

    ligne_total = d["premiere_ligne_grille"] + nb_creneaux
    cellule = feuille.cell(row=ligne_total, column=d["colonne_horaires"], value="Total (heures)")
    cellule.font, cellule.fill = Font(bold=True), _GRIS
    premiere, derniere = d["premiere_ligne_grille"], ligne_total - 1
    for j in range(len(JOURS_SEMAINE)):
        lettre = get_column_letter(d["premiere_colonne_jour"] + j)
        case = feuille.cell(row=ligne_total, column=d["premiere_colonne_jour"] + j,
                            value=f'=COUNTA({lettre}{premiere}:{lettre}{derniere})/2')
        case.font, case.fill, case.alignment = Font(bold=True), _GRIS, Alignment(horizontal="center")
    lettre_fin = get_column_letter(d["premiere_colonne_jour"] + len(JOURS_SEMAINE) - 1)
    bilan = feuille.cell(row=ligne_total + 1, column=d["colonne_horaires"], value="Total semaine")
    bilan.font = Font(bold=True)
    feuille.cell(row=ligne_total + 1, column=d["premiere_colonne_jour"],
                 value=f'=SUM(B{ligne_total}:{lettre_fin}{ligne_total})').font = Font(bold=True)
    if personne["quotite"]:
        feuille.cell(row=ligne_total + 1, column=d["premiere_colonne_jour"] + 1,
                     value=f"quotité : {personne['quotite']:g} h")

    # ── Affinités par matière
    depart = ligne_total + 1 + DISPOSITION["lignes_avant_affinites"] + 1
    titre = feuille.cell(row=depart, column=1, value="MATIÈRES OÙ VOUS ÊTES LE PLUS À L'AISE")
    titre.font, titre.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="455A73")
    feuille.cell(row=depart + 1, column=1,
                 value="Note de 1 à 5 — laissez vide si vous n'avez pas de préférence.").font = Font(italic=True, size=9)
    validation = DataValidation(type="list", formula1='"1,2,3,4,5"', allow_blank=True, showDropDown=False)
    feuille.add_data_validation(validation)
    for i, famille in enumerate(FAMILLES):
        ligne = depart + 2 + i
        feuille.cell(row=ligne, column=1, value=famille).font = Font(size=10)
        case = feuille.cell(row=ligne, column=2)
        case.fill, case.border, case.alignment = _JAUNE, _BORDURE, Alignment(horizontal="center")
        validation.add(case)

    ligne_remarques = depart + 2 + len(FAMILLES) + 1
    feuille.cell(row=ligne_remarques, column=1, value="REMARQUES").font = Font(bold=True)
    case = feuille.cell(row=ligne_remarques + 1, column=1)
    case.fill, case.alignment = _JAUNE, Alignment(wrap_text=True, vertical="top")
    feuille.merge_cells(start_row=ligne_remarques + 1, start_column=1,
                        end_row=ligne_remarques + 4, end_column=len(JOURS_SEMAINE) + 1)
    feuille.freeze_panes = feuille.cell(row=DISPOSITION["premiere_ligne_grille"], column=2)


def importer_recueil(projet, chemin):
    """
    Relit un classeur de recueil rempli et met à jour disponibilités, affinités et remarques.

    Le rapprochement se fait sur le nom de l'onglet, comparé sans accents ni casse aux AESH du
    projet ; ce qui ne correspond à personne est signalé plutôt qu'ignoré silencieusement.
    """
    from .pronote import compacter
    classeur = load_workbook(chemin, data_only=True)
    population = projet.population()
    par_nom = {compacter(a["nom_complet"]): a for a in population["aesh"]}
    h_min, h_max = projet.etat.get("plage") or (8, 18)
    nb_creneaux = (h_max - h_min) * 60 // PAS_MINUTES
    d = DISPOSITION

    rapport = {"reconnus": [], "inconnus": [], "vides": [], "affinites": 0}
    for nom_onglet in classeur.sheetnames:
        compact = compacter(nom_onglet)
        if "MODE D EMPLOI" in compact:
            continue
        personne = par_nom.get(compact)
        if not personne:
            proches = [n for n in par_nom if compact[:8] and compact[:8] in n]
            personne = par_nom[proches[0]] if len(proches) == 1 else None
        if not personne:
            rapport["inconnus"].append(nom_onglet)
            continue
        feuille = classeur[nom_onglet]
        grille, coches = [], 0
        for j in range(len(JOURS_SEMAINE)):
            ligne_dispo = []
            for s in range(nb_creneaux):
                valeur = feuille.cell(row=d["premiere_ligne_grille"] + s,
                                      column=d["premiere_colonne_jour"] + j).value
                coche = bool(str(valeur).strip()) if valeur is not None else False
                ligne_dispo.append(coche)
                coches += coche
            grille.append(ligne_dispo)
        if not coches:
            rapport["vides"].append(personne["nom_complet"])
            continue
        projet.definir_disponibilites(personne["id"], grille)

        depart = d["premiere_ligne_grille"] + nb_creneaux + 1 + d["lignes_avant_affinites"] + 3
        affinites = {}
        for i, famille in enumerate(FAMILLES):
            valeur = feuille.cell(row=depart + i, column=2).value
            try:
                note = int(float(str(valeur).replace(",", ".")))
            except (TypeError, ValueError):
                continue
            if 1 <= note <= 5:
                affinites[famille] = note
        if affinites:
            projet.etat.setdefault("affinites", {})[personne["id"]] = affinites
            rapport["affinites"] += len(affinites)
        rapport["reconnus"].append({"nom": personne["nom_complet"],
                                    "heures": round(coches * PAS_MINUTES / 60, 2),
                                    "affinites": len(affinites)})
    classeur.close()
    projet.etat["resultat"] = None
    return rapport


# ───────────────────────────── Emplois du temps des AESH ─────────────────────────────

# Palette pastel : une couleur par élève, assez claire pour rester lisible en texte noir et
# distinguable en impression noir et blanc par sa densité. Au-delà, les couleurs se répètent.
PALETTE = ["FFE0B2", "C8E6C9", "BBDEFB", "F8BBD0", "D1C4E9", "FFF9C4", "B2DFDB", "FFCCBC",
           "CFD8DC", "DCEDC8", "B3E5FC", "E1BEE7", "FFCDD2", "C5CAE9", "D7CCC8", "B2EBF2",
           "FFECB3", "E6EE9C", "F0F4C3", "D0D9FF"]


def couleurs_eleves(resultat):
    """{nom d'élève: couleur}, dans l'ordre d'apparition pour que la légende suive le tableau."""
    noms = sorted({a["eleve_nom"] for a in resultat["affectations"]})
    return {nom: PALETTE[i % len(PALETTE)] for i, nom in enumerate(noms)}


def _grilles_aesh(projet, resultat):
    """{id_aesh: {(parite, jour, creneau): [affectations]}}."""
    par_aesh = {}
    for a in resultat["affectations"]:
        par_aesh.setdefault(a["aesh"], {}).setdefault((a["parite"], a["jour"], a["creneau"]), []).append(a)
    return par_aesh


def _contenu(affectations, avec_matiere=True):
    """Texte d'une cellule et signature servant à fusionner les créneaux identiques consécutifs."""
    if not affectations:
        return "", "", []
    tries = sorted(affectations, key=lambda a: a["eleve_nom"])
    morceaux = []
    for a in tries:
        ligne = a["eleve_nom"]
        if avec_matiere:
            ligne += "\n" + a["matiere"]
            if a.get("salle"):
                ligne += "\n" + a["salle"]
        morceaux.append(ligne)
    signature = "|".join(f"{a['eleve']}~{a['id_cours']}" for a in tries)
    return "\n— — —\n".join(morceaux), signature, [a["eleve_nom"] for a in tries]


def _blocs(grille, parite, jour, nb_creneaux):
    """
    Découpe une colonne (un jour, une parité) en blocs de créneaux consécutifs identiques.

    C'est ce qui rend l'emploi du temps lisible : un cours de deux heures devient une cellule
    unique, comme dans ProNote, au lieu de quatre lignes répétant la même chose.
    Retourne [(premier créneau, hauteur, texte, noms des élèves, signature)].
    """
    blocs, s = [], 0
    while s < nb_creneaux:
        texte, signature, noms = _contenu(grille.get((parite, jour, s), []))
        if not signature:
            s += 1
            continue
        fin = s + 1
        while fin < nb_creneaux and _contenu(grille.get((parite, jour, fin), []))[1] == signature:
            fin += 1
        blocs.append((s, fin - s, texte, noms, signature))
        s = fin
    return blocs


def blocs_jour(grille, jour, nb_creneaux):
    """
    Blocs d'une journée, en fusionnant les semaines A et B quand elles portent le même cours.

    Un cours hebdomadaire occupe les deux semaines à l'identique : l'afficher deux fois côte à côte
    double la largeur sans rien apprendre. On ne sépare donc les demi-colonnes que là où les deux
    semaines diffèrent réellement — exactement la lecture d'un emploi du temps ProNote.

    Retourne [(premier créneau, hauteur, largeur, colonne, texte, noms)] où « colonne » vaut 0 pour
    la semaine A, 1 pour la semaine B, et « largeur » 2 quand le bloc couvre les deux.
    """
    blocs_a = {b[0]: b for b in _blocs(grille, "A", jour, nb_creneaux)}
    blocs_b = {b[0]: b for b in _blocs(grille, "B", jour, nb_creneaux)}
    sortie, fusionnes = [], set()
    for depart, (_, hauteur, texte, noms, signature) in sorted(blocs_a.items()):
        jumeau = blocs_b.get(depart)
        if jumeau and jumeau[1] == hauteur and jumeau[4] == signature:
            sortie.append((depart, hauteur, 2, 0, texte, noms))
            fusionnes.add(depart)
        else:
            sortie.append((depart, hauteur, 1, 0, texte, noms))
    for depart, (_, hauteur, texte, noms, _) in sorted(blocs_b.items()):
        if depart not in fusionnes:
            sortie.append((depart, hauteur, 1, 1, texte, noms))
    return sorted(sortie)


def _fond_html(noms, couleurs):
    """Fond d'une cellule : uni pour un élève, bandes obliques quand plusieurs se partagent le créneau."""
    teintes = [f"#{couleurs.get(n, 'E8EAED')}" for n in dict.fromkeys(noms)]
    if len(teintes) == 1:
        return f"background:{teintes[0]}"
    largeur = 14
    arrets = "".join(f"{t} {i * largeur}px {(i + 1) * largeur}px," for i, t in enumerate(teintes))
    return f"background:repeating-linear-gradient(135deg,{arrets.rstrip(',')})"


def emplois_du_temps_html(projet, resultat):
    h_min, h_max = projet.etat.get("plage") or (7, 18)
    nb_creneaux = (h_max - h_min) * 60 // PAS_MINUTES
    par_aesh = _grilles_aesh(projet, resultat)
    infos_aesh = {a["id"]: a for a in resultat["aesh"]}
    couleurs = couleurs_eleves(resultat)
    synthese = resultat["synthese"]

    style = """body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:22px;color:#1f2933;font-size:13px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:16px;margin:30px 0 2px;border-top:2px solid #999;padding-top:10px}
.sub{color:#5b6570;font-style:italic;margin:2px 0 10px}
table{border-collapse:collapse;margin:6px 0;table-layout:fixed;width:100%}
td,th{border:1px solid #9aa0a6;padding:3px 4px;vertical-align:middle;white-space:pre-line;
      font-size:10.5px;text-align:center;overflow:hidden}
th{background:#e4e7ea;font-size:11px}th.ab{background:#eef0f2;font-weight:normal;font-style:italic;font-size:9px}
td.h{background:#f2f4f6;font-weight:600;width:74px;font-size:10px}
.legende{margin:10px 0 4px;display:flex;flex-wrap:wrap;gap:5px}
.legende span{border:1px solid #9aa0a6;border-radius:3px;padding:2px 8px;font-size:11px}
@media print{h2{page-break-before:always}h2:first-of-type{page-break-before:auto}}"""

    parties = [f"<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
               f"<title>Emplois du temps AESH</title><style>{style}</style></head><body>",
               f"<h1>Emplois du temps des AESH — {html.escape(projet.etat.get('etablissement') or '')}</h1>",
               f"<p class='sub'>Calculé le {html.escape(str(resultat.get('calcule_le', '')).replace('T', ' '))} · "
               f"couverture {synthese['taux_global']} % ({synthese['heures_couvertes']} h sur "
               f"{synthese['heures_notifiees']} h notifiées) · élève le moins bien servi : "
               f"{synthese['taux_minimal']} %</p>",
               "<div class='legende'>" + "".join(
                   f"<span style='background:#{c}'>{html.escape(n)}</span>"
                   for n, c in couleurs.items()) + "</div>"]

    for id_aesh, grille in sorted(par_aesh.items(), key=lambda kv: infos_aesh.get(kv[0], {}).get("nom", "")):
        infos = infos_aesh.get(id_aesh, {})
        parties.append(f"<h2>{html.escape(infos.get('nom', id_aesh))}</h2>"
                       f"<p class='sub'>{infos.get('heures_affectees', 0)} h affectées sur "
                       f"{infos.get('quotite', 0):g} h de quotité · {infos.get('nb_eleves', 0)} élève(s) suivis</p>")
        blocs = {jour: blocs_jour(grille, jour, nb_creneaux) for jour in range(len(JOURS_SEMAINE))}
        occupees = set()          # (ligne, jour, colonne) couvertes par un bloc commencé plus haut
        depart_de = {}
        for jour, liste in blocs.items():
            for premier, hauteur, largeur, colonne, texte, noms in liste:
                depart_de[(premier, jour, colonne)] = (hauteur, largeur, texte, noms)
                for ligne in range(premier, premier + hauteur):
                    for k in range(largeur):
                        if (ligne, jour, colonne + k) != (premier, jour, colonne):
                            occupees.add((ligne, jour, colonne + k))
        largeur_colonne = round(88 / (len(JOURS_SEMAINE) * 2), 3)
        parties.append("<table><colgroup><col style='width:74px'>"
                       + f"<col style='width:{largeur_colonne}%'>" * (len(JOURS_SEMAINE) * 2)
                       + "</colgroup><tr><th rowspan='2'>Horaires</th>"
                       + "".join(f"<th colspan='2'>{j}</th>" for j in JOURS_SEMAINE) + "</tr><tr>"
                       + "".join("<th class='ab'>sem. A</th><th class='ab'>sem. B</th>"
                                 for _ in JOURS_SEMAINE) + "</tr>")
        for s in range(nb_creneaux):
            parties.append(f"<tr><td class='h'>{_libelle_creneau(h_min, s)}</td>")
            for jour in range(len(JOURS_SEMAINE)):
                for colonne in (0, 1):
                    if (s, jour, colonne) in occupees:
                        continue
                    bloc = depart_de.get((s, jour, colonne))
                    if not bloc:
                        parties.append("<td></td>")
                        continue
                    hauteur, largeur, texte, noms = bloc
                    attributs = (f" rowspan='{hauteur}'" if hauteur > 1 else "") \
                                + (f" colspan='{largeur}'" if largeur > 1 else "")
                    parties.append(f"<td{attributs} style=\"{_fond_html(noms, couleurs)}\">"
                                   f"{html.escape(texte)}</td>")
            parties.append("</tr>")
        parties.append("</table>")
    parties.append("</body></html>")

    chemin = _dossier_sortie(projet) / f"EDT_AESH_{_horodatage()}.html"
    chemin.write_text("".join(parties), encoding="utf-8")
    return chemin


def emplois_du_temps_xlsx(projet, resultat):
    h_min, h_max = projet.etat.get("plage") or (7, 18)
    nb_creneaux = (h_max - h_min) * 60 // PAS_MINUTES
    par_aesh = _grilles_aesh(projet, resultat)
    infos_aesh = {a["id"]: a for a in resultat["aesh"]}
    couleurs = couleurs_eleves(resultat)

    classeur = Workbook()
    synthese = classeur.active
    synthese.title = "Synthèse"
    synthese.append(["Élève", "Aide", "Heures notifiées", "Heures couvertes", "Taux", "Nb AESH", "AESH"])
    for cellule in synthese[1]:
        cellule.font, cellule.fill = Font(bold=True), _ENTETE
    for bilan in resultat["eleves"]:
        ligne = [bilan["nom"], bilan["type_aide"], bilan["heures_notifiees"], bilan["heures_couvertes"],
                 "" if bilan["taux"] is None else bilan["taux"] / 100,
                 bilan["nb_aesh"], ", ".join(bilan["aesh"])]
        synthese.append(ligne)
        teinte = couleurs.get(bilan["nom"])
        if teinte:
            synthese.cell(row=synthese.max_row, column=1).fill = PatternFill("solid", fgColor=teinte)
    for ligne in synthese.iter_rows(min_row=2, min_col=5, max_col=5):
        ligne[0].number_format = "0 %"
    for colonne, largeur in zip("ABCDEFG", (28, 6, 16, 16, 8, 8, 52)):
        synthese.column_dimensions[colonne].width = largeur
    synthese.freeze_panes = "A2"

    for id_aesh, grille in sorted(par_aesh.items(), key=lambda kv: infos_aesh.get(kv[0], {}).get("nom", "")):
        infos = infos_aesh.get(id_aesh, {})
        feuille = classeur.create_sheet(_titre_onglet(infos.get("nom", id_aesh), classeur.sheetnames))
        feuille.cell(row=1, column=1, value=infos.get("nom", id_aesh)).font = Font(bold=True, size=13)
        feuille.cell(row=2, column=1,
                     value=f"{infos.get('heures_affectees', 0)} h affectées sur "
                           f"{infos.get('quotite', 0):g} h de quotité · "
                           f"{infos.get('nb_eleves', 0)} élève(s) suivis").font = Font(italic=True, size=9)
        feuille.cell(row=4, column=1, value="Horaires").font = Font(bold=True)
        feuille.column_dimensions["A"].width = 14
        colonnes = []
        for jour, nom_jour in enumerate(JOURS_SEMAINE):
            for parite in ("A", "B"):
                colonne = 2 + len(colonnes)
                colonnes.append((jour, parite, colonne))
                feuille.column_dimensions[get_column_letter(colonne)].width = 20
                cellule = feuille.cell(row=4, column=colonne, value=f"{nom_jour}\nsem. {parite}")
                cellule.font, cellule.fill = Font(bold=True, size=9), _ENTETE
                cellule.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for s in range(nb_creneaux):
            cellule = feuille.cell(row=5 + s, column=1, value=_libelle_creneau(h_min, s))
            cellule.font, cellule.fill = Font(size=9), _GRIS
            cellule.border = _BORDURE
            for _, _, colonne in colonnes:
                feuille.cell(row=5 + s, column=colonne).border = _BORDURE
        for jour in range(len(JOURS_SEMAINE)):
            for premier, hauteur, largeur, colonne, texte, noms in blocs_jour(grille, jour, nb_creneaux):
                depart = 2 + jour * 2 + colonne
                case = feuille.cell(row=5 + premier, column=depart, value=texte)
                case.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
                case.font = Font(size=8)
                case.border = _BORDURE
                # Excel ne sait pas faire de bandes : plusieurs élèves sur le même créneau prennent
                # la couleur du premier, et leurs noms restent tous écrits dans la cellule.
                case.fill = PatternFill("solid", fgColor=couleurs.get(noms[0], "D9E8FA"))
                if hauteur > 1 or largeur > 1:
                    feuille.merge_cells(start_row=5 + premier, start_column=depart,
                                        end_row=5 + premier + hauteur - 1,
                                        end_column=depart + largeur - 1)
        feuille.freeze_panes = "B5"
        feuille.sheet_view.showGridLines = False

    legende = classeur.create_sheet("Légende")
    legende.column_dimensions["A"].width = 34
    legende.cell(row=1, column=1, value="Couleur par élève").font = Font(bold=True, size=12)
    for i, (nom, teinte) in enumerate(couleurs.items(), start=3):
        cellule = legende.cell(row=i, column=1, value=nom)
        cellule.fill, cellule.border = PatternFill("solid", fgColor=teinte), _BORDURE

    chemin = _dossier_sortie(projet) / f"EDT_AESH_{_horodatage()}.xlsx"
    classeur.save(chemin)
    return chemin
