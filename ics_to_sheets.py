#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script pour exporter des calendriers ICS vers Google Sheets
Crée un onglet par élève avec une grille horaire Lundi-Jeudi × 7h-19h
"""

import os
import re
import time
from datetime import datetime, timedelta
from collections import defaultdict
import pytz
from icalendar import Calendar
import gspread
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


# Configuration
JOURS_SEMAINE = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi']
CRENEAUX_HORAIRES = [
    '7-8 heures', '8-9 heures', '9-10 heures', '10-11 heures',
    '11-12 heures', '12-13 heures', '13-14 heures', '14-15 heures',
    '15-16 heures', '16-17 heures', '17-18 heures', '18-19 heures'
]

# Mapping jour de semaine (0=Lundi, 6=Dimanche)
JOUR_MAPPING = {0: 'Lundi', 1: 'Mardi', 2: 'Mercredi', 3: 'Jeudi', 4: 'Vendredi', 5: 'Samedi', 6: 'Dimanche'}


def extraire_nom_eleve(nom_fichier):
    """
    Extrait le nom et prénom de l'élève depuis le nom du fichier
    Format: Calendrier_NOM_Prenom_DDMMYYYY.ics
    """
    match = re.match(r'Calendrier_([^_]+)_([^_]+)_\d+\.ics', nom_fichier)
    if match:
        nom = match.group(1)
        prenom = match.group(2)
        return f"{nom} {prenom}"
    return nom_fichier.replace('.ics', '')


def get_heure_creneau(heure):
    """
    Retourne l'index du créneau horaire pour une heure donnée
    Retourne None si l'heure est en dehors des créneaux (avant 7h ou après 19h)
    """
    if heure < 7 or heure >= 19:
        return None
    return heure - 7


def get_numero_semaine(date):
    """
    Retourne un identifiant unique pour la semaine (année + numéro de semaine)
    """
    return f"{date.year}-W{date.isocalendar()[1]:02d}"


def parser_fichier_ics(chemin_fichier, debug=False):
    """
    Parse un fichier ICS et retourne les événements de cours récurrents par créneau
    Détecte les alternances semaine A/B
    """
    with open(chemin_fichier, 'rb') as f:
        cal = Calendar.from_ical(f.read())
    
    # Timezone Paris
    tz_paris = pytz.timezone('Europe/Paris')
    
    # Dictionnaire pour compter les occurrences de cours par créneau et type de semaine
    # Structure: {jour: {creneau: {'A': {cours: count}, 'B': {cours: count}}}}
    compteur_creneaux = {
        jour: {
            i: {'A': defaultdict(int), 'B': defaultdict(int)} 
            for i in range(len(CRENEAUX_HORAIRES))
        } 
        for jour in JOURS_SEMAINE
    }
    
    # Compteur pour debug
    cours_count = 0
    
    for component in cal.walk():
        if component.name == "VEVENT":
            cours_count += 1
            
            # Extraire les informations
            summary = str(component.get('summary', ''))
            location = str(component.get('location', '')) if component.get('location') else ''
            dtstart = component.get('dtstart').dt
            dtend = component.get('dtend').dt
            
            # Convertir en timezone Paris si nécessaire
            if isinstance(dtstart, datetime):
                if dtstart.tzinfo is None:
                    dtstart = pytz.utc.localize(dtstart)
                dtstart = dtstart.astimezone(tz_paris)
                
                if dtend.tzinfo is None:
                    dtend = pytz.utc.localize(dtend)
                dtend = dtend.astimezone(tz_paris)
                
                # Récupérer le jour de la semaine
                jour_semaine = dtstart.weekday()
                nom_jour = JOUR_MAPPING.get(jour_semaine)
                
                # Filtrer uniquement les jours de la semaine configurés
                if nom_jour not in JOURS_SEMAINE:
                    continue
                
                # Déterminer le type de semaine (A = impaire, B = paire)
                numero_semaine = dtstart.isocalendar()[1]
                type_semaine = 'A' if numero_semaine % 2 == 1 else 'B'
                
                # Calculer les créneaux horaires couverts
                heure_debut = dtstart.hour
                heure_fin = dtend.hour
                
                # Si le cours se termine à une heure pile (minutes = 0), on ne prend pas ce créneau
                if dtend.minute == 0:
                    heure_fin -= 1
                
                # Debug: afficher quelques exemples
                if debug and cours_count <= 3:
                    print(f"  DEBUG - Cours: {summary[:30]}")
                    print(f"         Date: {dtstart.strftime('%Y-%m-%d %H:%M')} → {dtend.strftime('%H:%M')}")
                    print(f"         Jour: {nom_jour}, Semaine: {type_semaine}")
                    print(f"         Heures: {heure_debut}h → {heure_fin}h")
                
                # Compter les occurrences du cours dans tous les créneaux concernés
                for heure in range(heure_debut, heure_fin + 1):
                    creneau_idx = get_heure_creneau(heure)
                    if creneau_idx is not None:
                        # Nettoyer et formatter l'information du cours
                        info_cours = summary.strip()
                        # Ajouter la salle si elle existe
                        if location:
                            info_cours += f" - {location}"
                        
                        # Incrémenter le compteur pour ce cours dans ce créneau et type de semaine
                        compteur_creneaux[nom_jour][creneau_idx][type_semaine][info_cours] += 1
    
    # Debug
    if debug:
        print(f"  DEBUG - Total événements traités: {cours_count}")
    
    # Créer la grille finale avec détection d'alternance A/B
    # Structure: {jour: {creneau: {'cours_A': str, 'cours_B': str, 'alternance': bool}}}
    grille_finale = {jour: {i: None for i in range(len(CRENEAUX_HORAIRES))} for jour in JOURS_SEMAINE}
    
    SEUIL_MIN = 5  # Nombre minimum d'occurrences pour considérer un cours comme régulier
    
    for jour in JOURS_SEMAINE:
        for creneau_idx in range(len(CRENEAUX_HORAIRES)):
            cours_A_dict = compteur_creneaux[jour][creneau_idx]['A']
            cours_B_dict = compteur_creneaux[jour][creneau_idx]['B']
            
            # Trouver le cours le plus fréquent en semaine A
            cours_A = None
            occurrences_A = 0
            if cours_A_dict:
                cours_A, occurrences_A = max(cours_A_dict.items(), key=lambda x: x[1])
                if occurrences_A < SEUIL_MIN:
                    cours_A = None
            
            # Trouver le cours le plus fréquent en semaine B
            cours_B = None
            occurrences_B = 0
            if cours_B_dict:
                cours_B, occurrences_B = max(cours_B_dict.items(), key=lambda x: x[1])
                if occurrences_B < SEUIL_MIN:
                    cours_B = None
            
            # Déterminer s'il y a alternance
            if cours_A and cours_B and cours_A != cours_B:
                # Alternance détectée
                grille_finale[jour][creneau_idx] = {
                    'cours_A': cours_A,
                    'cours_B': cours_B,
                    'alternance': True
                }
                if debug:
                    print(f"  DEBUG - {jour} {CRENEAUX_HORAIRES[creneau_idx]}: ALTERNANCE")
                    print(f"         Sem. A: {cours_A[:40]} ({occurrences_A} fois)")
                    print(f"         Sem. B: {cours_B[:40]} ({occurrences_B} fois)")
            elif cours_A:
                # Seul le cours de semaine A existe (ou les deux sont identiques)
                grille_finale[jour][creneau_idx] = {
                    'cours_A': cours_A,
                    'cours_B': None,
                    'alternance': False
                }
                if debug and occurrences_A > 1:
                    print(f"  DEBUG - {jour} {CRENEAUX_HORAIRES[creneau_idx]}: {cours_A[:40]} ({occurrences_A} fois)")
            elif cours_B:
                # Seul le cours de semaine B existe
                grille_finale[jour][creneau_idx] = {
                    'cours_A': cours_B,
                    'cours_B': None,
                    'alternance': False
                }
                if debug and occurrences_B > 1:
                    print(f"  DEBUG - {jour} {CRENEAUX_HORAIRES[creneau_idx]}: {cours_B[:40]} ({occurrences_B} fois)")
    
    return grille_finale


def authentifier_google():
    """
    Authentifie l'utilisateur avec OAuth2 et retourne les credentials
    """
    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive.file'
    ]
    
    creds = None
    # Le fichier token.json stocke les tokens d'accès et de rafraîchissement
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # Si aucun credentials valide n'existe, demander à l'utilisateur de se connecter
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("🔄 Rafraîchissement du token d'authentification...")
            creds.refresh(Request())
        else:
            if not os.path.exists('credentials_oauth.json'):
                print("❌ Erreur : Le fichier 'credentials_oauth.json' n'a pas été trouvé.")
                print("   Veuillez suivre les instructions dans README.md pour configurer OAuth2.")
                return None
            
            print("🔐 Ouverture du navigateur pour l'authentification Google...")
            print("   Veuillez vous connecter avec votre compte Google.")
            flow = InstalledAppFlow.from_client_secrets_file('credentials_oauth.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Sauvegarder les credentials pour la prochaine fois
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
        print("✓ Authentification réussie !")
    
    return creds


def creer_google_sheet(nom_sheet):
    """
    Crée un nouveau Google Sheet et retourne l'objet spreadsheet
    """
    try:
        # Authentifier l'utilisateur
        creds = authentifier_google()
        if not creds:
            return None
        
        # Créer le client gspread
        client = gspread.authorize(creds)
        
        # Créer un nouveau spreadsheet
        spreadsheet = client.create(nom_sheet)
        
        print(f"✓ Google Sheet créé : {nom_sheet}")
        print(f"  URL : {spreadsheet.url}")
        
        return spreadsheet
    except Exception as e:
        print(f"❌ Erreur lors de la création du Google Sheet : {e}")
        return None


def remplir_onglet_eleve(worksheet, grille_cours):
    """
    Remplit un onglet avec la grille horaire d'un élève en utilisant batch update
    Gère les cellules divisées pour les alternances semaine A/B
    """
    # Analyser la grille pour déterminer quels créneaux ont des alternances
    creneaux_avec_alternance = []
    for creneau_idx in range(len(CRENEAUX_HORAIRES)):
        a_alternance = False
        for jour in JOURS_SEMAINE:
            info = grille_cours[jour][creneau_idx]
            if info and info.get('alternance', False):
                a_alternance = True
                break
        creneaux_avec_alternance.append(a_alternance)
    
    # Construire les données ligne par ligne
    data = []
    requests = []
    
    # Ligne 1 : en-têtes
    data.append(['Horaires'] + JOURS_SEMAINE)
    current_row = 1  # Index de la ligne actuelle (0-based)
    
    # Pour chaque créneau horaire
    for creneau_idx, creneau in enumerate(CRENEAUX_HORAIRES):
        if creneaux_avec_alternance[creneau_idx]:
            # Ce créneau a au moins une alternance - utiliser 2 lignes
            row_A = [creneau]  # Ligne pour semaine A
            row_B = ['']  # Ligne pour semaine B (horaire vide car fusionné)
            
            # Pour chaque jour
            for jour in JOURS_SEMAINE:
                info = grille_cours[jour][creneau_idx]
                
                if info and info.get('alternance', False):
                    # Alternance : diviser la cellule
                    cours_A = info['cours_A'] + ' (sem. A)'
                    cours_B = info['cours_B'] + ' (sem. B)'
                    row_A.append(cours_A)
                    row_B.append(cours_B)
                elif info and info['cours_A']:
                    # Pas d'alternance : fusionner sur les 2 lignes
                    row_A.append(info['cours_A'])
                    row_B.append('')  # Sera fusionné
                else:
                    # Pas de cours
                    row_A.append('')
                    row_B.append('')
            
            data.append(row_A)
            data.append(row_B)
            
            # Fusionner la cellule des horaires (colonne 0) sur 2 lignes
            requests.append({
                'mergeCells': {
                    'range': {
                        'sheetId': worksheet.id,
                        'startRowIndex': current_row,
                        'endRowIndex': current_row + 2,
                        'startColumnIndex': 0,
                        'endColumnIndex': 1
                    },
                    'mergeType': 'MERGE_ALL'
                }
            })
            
            # Fusionner les cellules des jours qui n'ont pas d'alternance
            for col_idx, jour in enumerate(JOURS_SEMAINE, start=1):
                info = grille_cours[jour][creneau_idx]
                if not (info and info.get('alternance', False)):
                    # Fusionner cette cellule sur les 2 lignes
                    requests.append({
                        'mergeCells': {
                            'range': {
                                'sheetId': worksheet.id,
                                'startRowIndex': current_row,
                                'endRowIndex': current_row + 2,
                                'startColumnIndex': col_idx,
                                'endColumnIndex': col_idx + 1
                            },
                            'mergeType': 'MERGE_ALL'
                        }
                    })
            
            # Ajouter une bordure horizontale entre les deux lignes pour les cellules avec alternance
            for col_idx, jour in enumerate(JOURS_SEMAINE, start=1):
                info = grille_cours[jour][creneau_idx]
                if info and info.get('alternance', False):
                    requests.append({
                        'updateBorders': {
                            'range': {
                                'sheetId': worksheet.id,
                                'startRowIndex': current_row,
                                'endRowIndex': current_row + 1,
                                'startColumnIndex': col_idx,
                                'endColumnIndex': col_idx + 1
                            },
                            'bottom': {
                                'style': 'SOLID',
                                'width': 1,
                                'color': {'red': 0.5, 'green': 0.5, 'blue': 0.5}
                            }
                        }
                    })
            
            current_row += 2
        else:
            # Créneau normal - utiliser 1 ligne
            row = [creneau]
            
            for jour in JOURS_SEMAINE:
                info = grille_cours[jour][creneau_idx]
                if info and info['cours_A']:
                    row.append(info['cours_A'])
                else:
                    row.append('')
            
            data.append(row)
            current_row += 1
    
    # Mettre à jour toutes les données
    end_col_letter = chr(65 + len(JOURS_SEMAINE))  # A=65, donc F=70
    range_str = f'A1:{end_col_letter}{len(data)}'
    worksheet.update(range_str, data, value_input_option='RAW')
    
    # Ajouter les requêtes de formatage de base
    base_requests = [
        # Formater les en-têtes (ligne 1)
        {
            'repeatCell': {
                'range': {
                    'sheetId': worksheet.id,
                    'startRowIndex': 0,
                    'endRowIndex': 1,
                    'startColumnIndex': 0,
                    'endColumnIndex': len(JOURS_SEMAINE) + 1
                },
                'cell': {
                    'userEnteredFormat': {
                        'textFormat': {'bold': True},
                        'horizontalAlignment': 'CENTER',
                        'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9}
                    }
                },
                'fields': 'userEnteredFormat(textFormat,horizontalAlignment,backgroundColor)'
            }
        },
        # Formater la colonne des horaires (colonne A)
        {
            'repeatCell': {
                'range': {
                    'sheetId': worksheet.id,
                    'startRowIndex': 1,
                    'endRowIndex': len(data),
                    'startColumnIndex': 0,
                    'endColumnIndex': 1
                },
                'cell': {
                    'userEnteredFormat': {
                        'textFormat': {'bold': True},
                        'horizontalAlignment': 'CENTER',
                        'verticalAlignment': 'MIDDLE'
                    }
                },
                'fields': 'userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment)'
            }
        },
        # Activer le retour à la ligne pour toutes les cellules
        {
            'repeatCell': {
                'range': {
                    'sheetId': worksheet.id,
                    'startRowIndex': 0,
                    'endRowIndex': len(data),
                    'startColumnIndex': 0,
                    'endColumnIndex': len(JOURS_SEMAINE) + 1
                },
                'cell': {
                    'userEnteredFormat': {
                        'wrapStrategy': 'WRAP',
                        'verticalAlignment': 'MIDDLE'
                    }
                },
                'fields': 'userEnteredFormat(wrapStrategy,verticalAlignment)'
            }
        },
        # Ajuster la largeur de la colonne A (Horaires)
        {
            'updateDimensionProperties': {
                'range': {
                    'sheetId': worksheet.id,
                    'dimension': 'COLUMNS',
                    'startIndex': 0,
                    'endIndex': 1
                },
                'properties': {
                    'pixelSize': 150
                },
                'fields': 'pixelSize'
            }
        },
        # Ajuster la largeur des colonnes des jours
        {
            'updateDimensionProperties': {
                'range': {
                    'sheetId': worksheet.id,
                    'dimension': 'COLUMNS',
                    'startIndex': 1,
                    'endIndex': len(JOURS_SEMAINE) + 1
                },
                'properties': {
                    'pixelSize': 250
                },
                'fields': 'pixelSize'
            }
        }
    ]
    
    # Combiner toutes les requêtes
    all_requests = base_requests + requests
    
    # Exécuter toutes les requêtes en une seule batch update
    worksheet.spreadsheet.batch_update({'requests': all_requests})


def main():
    """
    Fonction principale
    """
    print("=" * 60)
    print("Export de calendriers ICS vers Google Sheets")
    print("=" * 60)
    print()
    
    # Récupérer tous les fichiers .ics dans le répertoire courant
    fichiers_ics = [f for f in os.listdir('.') if f.endswith('.ics')]
    
    if not fichiers_ics:
        print("❌ Aucun fichier .ics trouvé dans le répertoire courant.")
        return
    
    print(f"📁 {len(fichiers_ics)} fichier(s) .ics trouvé(s)")
    print()
    
    # Créer un nom pour le Google Sheet avec timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nom_sheet = f"Calendriers_Eleves_{timestamp}"
    
    # Créer le Google Sheet
    spreadsheet = creer_google_sheet(nom_sheet)
    
    if not spreadsheet:
        return
    
    print()
    print("📊 Traitement des fichiers...")
    print()
    
    # Supprimer la feuille par défaut créée automatiquement
    try:
        default_sheet = spreadsheet.sheet1
        spreadsheet.del_worksheet(default_sheet)
    except:
        pass
    
    # Traiter chaque fichier ICS avec gestion intelligente du quota API
    # Quota Google: 60 requêtes/minute. Chaque élève = ~3 requêtes
    # On traite 18 élèves (54 requêtes), pause 60s, puis les 9 restants
    BATCH_SIZE = 18  # Nombre d'élèves à traiter avant une pause
    
    for idx, fichier in enumerate(fichiers_ics, 1):
        nom_eleve = extraire_nom_eleve(fichier)
        print(f"[{idx}/{len(fichiers_ics)}] Traitement de {nom_eleve}...")
        
        # Mode debug pour le premier fichier uniquement
        debug_mode = (idx == 1)
        
        try:
            # Parser le fichier ICS
            grille_cours = parser_fichier_ics(fichier, debug=debug_mode)
            
            # Créer un nouvel onglet pour cet élève
            # Maximum: 1 en-tête + 12 créneaux × 2 lignes = 25 lignes
            worksheet = spreadsheet.add_worksheet(title=nom_eleve, rows=30, cols=6)
            
            # Remplir l'onglet
            remplir_onglet_eleve(worksheet, grille_cours)
            
            if not debug_mode:
                print("  ✓")
            else:
                print("  ✓ (avec debug)")
            
            # Pause intelligente pour respecter le quota API
            if idx % BATCH_SIZE == 0 and idx < len(fichiers_ics):
                print()
                print(f"⏸️  Pause de 60 secondes pour respecter le quota API Google...")
                print(f"   ({idx}/{len(fichiers_ics)} élèves traités, {len(fichiers_ics) - idx} restants)")
                time.sleep(60)
                print("✓ Reprise du traitement...")
                print()
                
        except Exception as e:
            print(f"❌ Erreur : {e}")
    
    print()
    print("=" * 60)
    print("✓ Export terminé avec succès !")
    print(f"📊 Accédez à votre Google Sheet ici :")
    print(f"   {spreadsheet.url}")
    print("=" * 60)


if __name__ == "__main__":
    main()
