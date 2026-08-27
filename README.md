# Export_ics2sheet — Emplois du temps des élèves notifiés (suivi AESH)

**Exports ProNote (`.ics`) + fichier de notifications (`.ods`) → Google Sheets**

Génère, pour chaque élève listé dans le fichier de notifications (`Notif_*.ods`, onglet `Besoins_élèves`),
un emploi du temps hebdomadaire au format ProNote (grille par heure, cellule divisée en cas de demi-heure)
à partir des exports ProNote `.ics`, puis crée un Google Sheet : onglet **Récap** + un onglet par élève.

Finalité : fournir à la coordination AESH les emplois du temps des élèves accompagnés, qui servent de base
à la construction des emplois du temps des AESH.

| Document | Contenu |
|---|---|
| 📘 [PROCEDURE.md](PROCEDURE.md) | Procédure pas à pas : installation, préparation d'une année scolaire, génération, contrôles, dépannage |
| 🔑 [GUIDE_OAUTH2.md](GUIDE_OAUTH2.md) | Création du client OAuth2 dans Google Cloud (à faire une seule fois) |

## ⚠️ Données personnelles

Les fichiers d'entrée (exports ProNote, fichier de notifications) et les fichiers de sortie contiennent des données
personnelles d'élèves mineurs (identité, date de naissance, classe, besoins liés au handicap).
**Ils ne doivent jamais être versés dans ce dépôt.** Le [`.gitignore`](.gitignore) exclut les dossiers d'année
(`AAAA-AAAA/`), les `*.ics`, `*.ods`, `sorties/`, les archives, le journal de travail et les identifiants Google.
Le dépôt ne contient que le code et la documentation. Les Google Sheets générés sont créés dans le Drive du compte
qui s'authentifie : partager uniquement avec les personnes habilitées.

## Arborescence

```
Export_ics2sheet/
├── generer_edt.py              # script principal (lecture ODS + ICS, appariement, grille, HTML, Google Sheets)
├── auth_google.py              # (ré)authentification Google, à lancer dans un terminal
├── requirements.txt            # dépendances Python (versions figées)
├── README.md · PROCEDURE.md · GUIDE_OAUTH2.md
├── ics_to_sheets.py            # ancien script 2025-2026, conservé pour référence (remplacé par generer_edt.py)
│
│   ── hors git (données locales, voir .gitignore) ──
├── credentials_oauth.json      # client OAuth2 Google (ne pas partager)
├── token.json                  # jeton utilisateur, créé par auth_google.py (ne pas partager)
├── venv/                       # environnement virtuel Python
├── <AAAA-AAAA>/                # un dossier par année scolaire, ex. 2026-2027/
│   ├── Notif_*.ods             #   notifications : onglet Besoins_élèves = élèves à traiter
│   ├── <exports ProNote>/      #   Calendrier_NOM_Prenom_JJMMAAAA.ics (sous-dossiers acceptés)
│   └── sorties/                #   aperçu HTML, CSV d'appariement, URL du Google Sheet
├── archive_<AAAA-AAAA>/        # snapshots figés des années précédentes
└── NOTES_REPRISE_*.md          # journal de travail
```

## Installation

```bash
git clone git@github.com:patrick-reybaud/Export_ics2sheet.git
cd Export_ics2sheet
python3 -m venv venv                 # Python 3.11 recommandé
source venv/bin/activate
pip install -r requirements.txt
```

Puis créer le client OAuth2 Google et déposer `credentials_oauth.json` à la racine : voir [GUIDE_OAUTH2.md](GUIDE_OAUTH2.md).

## Utilisation

```bash
source venv/bin/activate

python auth_google.py                    # 1re fois / jeton périmé : ouvre le navigateur, écrit token.json
python generer_edt.py                    # aperçu local seulement → <année>/sorties/*.html + *_appariement.csv
python generer_edt.py --google           # + création du Google Sheet dans le Drive du compte authentifié
python generer_edt.py --google --partager prenom.nom@ac-academie.fr   # + partage en écriture (option répétable)
python generer_edt.py --annee 2027-2028  # autre dossier d'année (défaut : ANNEE_DEFAUT dans generer_edt.py)
python generer_edt.py --nom "EDT_test"   # nom du classeur / des fichiers de sortie (défaut : EDT_Eleves_AESH_<année>_<horodatage>)
```

Le script lit le fichier `.ods` du dossier d'année (le dernier par ordre alphabétique s'il y en a plusieurs) et tous
les `.ics` qu'il contient (sous-dossiers compris). La procédure complète est dans [PROCEDURE.md](PROCEDURE.md).

## Ce que fait le script

1. **Élèves à traiter** : onglet `Besoins_élèves` de l'ODS (nom, date de naissance, niveau, classe = colonne
   *REMARQUES*, type d'aide I/M/CO, heures, dates de notification, besoins).
2. **Appariement** avec les ICS : clé = date de naissance (présente dans le nom de fichier) + similarité du nom
   (tolère les fautes de frappe, ex. `DUPOND`/`DUPONT`) ; gère les noms composés (`Calendrier_MARTIN_DURAND_Camille_…`,
   le prénom est le dernier segment). Les élèves sans ICS sont signalés en rouge dans le Récap. L'export peut couvrir
   tout l'établissement : seuls les élèves de l'ODS sont traités.
3. **Grille** : lecture des événements de catégorie `Cours*` (les journées entières — vacances, fériés — alimentent
   le calendrier du Récap ; sorties, punitions, etc. sont ignorées), résolution interne 30 min, rendu par heure.
   Une heure est divisée en deux lignes uniquement si, pour au moins un jour, les deux demi-heures diffèrent
   (comme ProNote). Les cellules identiques consécutives sont fusionnées en un bloc.
   Cellule = matière / professeur / salle (groupe). Plage : 7h → 19h, étendue automatiquement (jusqu'à 24h)
   pour les élèves ayant des services du soir (restauration).
4. **Semaines A/B** : si les exports couvrent plusieurs semaines, l'alternance est détectée par créneau
   (cours différents entre semaines paires/impaires) et affichée « Sem. A : … / Sem. B : … » sur fond jaune.
   L'étiquette A/B suit `SEMAINE_A_REFERENCE` (n° ISO d'une semaine A officielle) dans `generer_edt.py` ;
   à défaut les semaines ISO impaires sont « A ». **L'ICS ProNote ne contient pas l'information A/B.**
   Avec un export d'une seule semaine, la grille est celle de cette semaine (pas d'alternance possible).
5. **Sorties locales** (toujours) : `<année>/sorties/<nom>.html` (aperçu fidèle) et `<nom>_appariement.csv`.
6. **Google Sheet** (`--google`) : classeur `EDT_Eleves_AESH_<année>_<horodatage>`, onglet Récap + un onglet par élève,
   ~6 appels API au total (pas de problème de quota). L'URL est écrite dans `<nom>_google_url.txt`.

## Authentification Google

- Client OAuth « application de bureau » : `credentials_oauth.json` (projet Google Cloud, voir [GUIDE_OAUTH2.md](GUIDE_OAUTH2.md)).
- Scopes : `spreadsheets` + `drive.file` (le script ne voit que les classeurs qu'il a créés).
- Tant que l'appli est en statut « Test », le *refresh token* expire au bout de **7 jours** : relancer
  `python auth_google.py` quand `generer_edt.py --google` demande une ré-authentification.
- Le classeur est créé dans le Drive du compte qui s'authentifie ; utiliser `--partager` pour le donner à quelqu'un d'autre.

## Paramètres modifiables (`generer_edt.py`, en tête de fichier)

| Paramètre | Rôle | Défaut |
|---|---|---|
| `ANNEE_DEFAUT` | dossier d'année utilisé sans `--annee` | `"2026-2027"` |
| `ONGLET_ELEVES` | onglet de l'ODS listant les élèves | `"Besoins_élèves"` |
| `JOURS` | jours affichés (ajouter `"Samedi"` si besoin) | Lundi → Vendredi |
| `HEURE_MIN_DEFAUT` / `HEURE_MAX_DEFAUT` | plage horaire de base (étendue automatiquement) | 7 / 19 |
| `PAS_MINUTES` | résolution interne | 30 |
| `SEMAINE_A_REFERENCE` | n° ISO d'une semaine « A » officielle | `None` (impaires = A) |
| `SEUIL_RELATIF` | multi-semaines : part des semaines où un cours doit apparaître pour être retenu | 0.5 |
| `COULEUR_*`, `LARGEUR_COL_*` | mise en forme du Google Sheet | — |

## Dépendances

Versions figées dans `requirements.txt` (icalendar, gspread 5.12, google-auth, google-auth-oauthlib, pytz).
La lecture de l'ODS se fait sans dépendance externe (XML de `content.xml`).
L'ancien script `ics_to_sheets.py` utilise `worksheet.update(range, values)` dont l'ordre des arguments change en
gspread ≥ 6 : ne pas monter de version sans l'adapter.
