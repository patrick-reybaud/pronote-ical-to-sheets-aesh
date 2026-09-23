#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tableur.py — lecture tolérante d'un classeur .ods ou .xlsx.

L'import doit encaisser ce que produisent réellement les outils académiques : en-têtes sur plusieurs
lignes, cellules fusionnées, colonnes renommées d'une année sur l'autre, onglets au nom approchant,
lignes vides intercalées. D'où :

  · lire_classeur()  → {nom d'onglet: [[cellules]]}, quel que soit le format
  · trouver_onglet() → retrouve un onglet par mots-clés, pas par égalité stricte
  · Entetes          → retrouve une colonne par mots-clés, et dit ce qu'elle n'a pas trouvé

Aucune exception n'est laissée remonter brute : les problèmes sont accumulés et rendus lisibles.
"""

import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS_TABLE = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
NS_TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
MAX_REPETITION = 60          # ODS encode les colonnes vides par répétition : on borne
MAX_LIGNES_VIDES = 50        # au-delà, on considère l'onglet terminé


def normaliser(texte):
    """Majuscules sans accents ni ponctuation — pour comparer des libellés écrits à la main."""
    import unicodedata
    texte = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9 ]", " ", re.sub(r"\s+", " ", texte.upper())).strip()


def compacter(texte):
    return re.sub(r"\s+", " ", normaliser(texte))


# ───────────────────────────── Lecture des formats ─────────────────────────────

def _lire_ods(chemin):
    racine = ET.fromstring(zipfile.ZipFile(chemin).read("content.xml"))
    onglets = {}
    for table in racine.iter(f"{{{NS_TABLE}}}table"):
        nom = table.get(f"{{{NS_TABLE}}}name") or f"Onglet {len(onglets) + 1}"
        lignes, vides = [], 0
        for ligne in table.iter(f"{{{NS_TABLE}}}table-row"):
            repet_ligne = min(int(ligne.get(f"{{{NS_TABLE}}}number-rows-repeated", "1")), MAX_LIGNES_VIDES)
            cellules = []
            for cellule in ligne:
                if cellule.tag not in (f"{{{NS_TABLE}}}table-cell", f"{{{NS_TABLE}}}covered-table-cell"):
                    continue
                n = min(int(cellule.get(f"{{{NS_TABLE}}}number-columns-repeated", "1")), MAX_REPETITION)
                texte = "\n".join("".join(p.itertext()) for p in cellule.iter(f"{{{NS_TEXT}}}p")).strip()
                cellules.extend([texte] * n)
            while cellules and cellules[-1] == "":
                cellules.pop()
            if not cellules:
                vides += repet_ligne
                if vides > MAX_LIGNES_VIDES and lignes:
                    break
                continue
            vides = 0
            lignes.extend([list(cellules)] * repet_ligne)
        onglets[nom] = lignes
    return onglets


def _lire_xlsx(chemin):
    import openpyxl
    classeur = openpyxl.load_workbook(chemin, data_only=True, read_only=True)
    onglets = {}
    for feuille in classeur.worksheets:
        lignes, vides = [], 0
        for ligne in feuille.iter_rows(values_only=True):
            cellules = ["" if v is None else (f"{v:g}" if isinstance(v, float) and v.is_integer() else str(v))
                        for v in ligne]
            while cellules and cellules[-1] == "":
                cellules.pop()
            if not cellules:
                vides += 1
                if vides > MAX_LIGNES_VIDES and lignes:
                    break
                continue
            vides = 0
            lignes.append(cellules)
        onglets[feuille.title] = lignes
    classeur.close()
    return onglets


def lire_classeur(chemin):
    """{nom d'onglet: [[cellules texte]]}. Lève ValueError avec un message lisible si illisible."""
    chemin = Path(chemin)
    if not chemin.exists():
        raise ValueError(f"Fichier introuvable : {chemin}")
    suffixe = chemin.suffix.lower()
    try:
        if suffixe == ".ods":
            return _lire_ods(chemin)
        if suffixe in (".xlsx", ".xlsm"):
            return _lire_xlsx(chemin)
    except zipfile.BadZipFile:
        raise ValueError(f"« {chemin.name} » n'est pas un classeur valide (fichier corrompu ou format inattendu).")
    except Exception as e:
        raise ValueError(f"Lecture de « {chemin.name} » impossible : {e.__class__.__name__} — {e}")
    raise ValueError(f"Format non pris en charge : « {chemin.suffix} ». "
                     f"Attendu : .ods (LibreOffice) ou .xlsx (Excel).")


# ───────────────────────────── Repérage tolérant ─────────────────────────────

def trouver_onglet(onglets, *motifs, obligatoire=True):
    """
    Nom de l'onglet dont le titre contient tous les motifs (comparaison sans accents ni casse).
    Essaie d'abord la correspondance exacte, puis partielle.
    """
    cibles = [compacter(m) for m in motifs]
    for nom in onglets:
        if compacter(nom) in cibles:
            return nom
    for nom in onglets:
        compact = compacter(nom)
        if any(cible in compact or compact in cible for cible in cibles):
            return nom
    if obligatoire:
        raise ValueError(f"Onglet {' / '.join(motifs)!r} introuvable. Onglets présents : {', '.join(onglets)}")
    return None


class Entetes:
    """
    Retrouve les colonnes d'un tableau par mots-clés, et garde trace de ce qui manque.

    L'en-tête peut être sur une ligne quelconque des premières : on retient celle qui reconnaît
    le plus de colonnes, ce qui absorbe les titres, logos et lignes de commentaire en tête.
    """

    def __init__(self, lignes, colonnes_attendues, lignes_a_tester=6):
        self.manquantes = []
        meilleur = (-1, 0, [])
        for i, ligne in enumerate(lignes[:lignes_a_tester]):
            compacts = [compacter(c) for c in ligne]
            score = sum(1 for motifs in colonnes_attendues.values()
                        if self._chercher(compacts, motifs) is not None)
            if score > meilleur[1]:
                meilleur = (i, score, compacts)
        self.ligne_entete, _, compacts = meilleur
        self.index = {}
        for cle, motifs in colonnes_attendues.items():
            trouve = self._chercher(compacts, motifs)
            if trouve is None:
                self.manquantes.append(cle)
            self.index[cle] = trouve
        self.donnees = lignes[self.ligne_entete + 1:] if self.ligne_entete >= 0 else []
        self.libelles = lignes[self.ligne_entete] if self.ligne_entete >= 0 else []

    @staticmethod
    def _chercher(compacts, motifs):
        for variantes in motifs:
            mots = [compacter(m) for m in (variantes if isinstance(variantes, (list, tuple)) else [variantes])]
            for i, entete in enumerate(compacts):
                if entete and all(mot in entete for mot in mots):
                    return i
        return None

    def valeur(self, ligne, cle):
        i = self.index.get(cle)
        if i is None or i >= len(ligne):
            return ""
        return str(ligne[i]).strip()
