# pronote-ical-to-sheets-aesh

**Suivi AESH — exports ProNote iCal (`.ics`) + fichier de notifications (`.ods`) → Google Sheets**

**L'application [PIAL — Affectation des AESH](GUIDE_APPLICATION.md) (`app.py`) est le point d'entrée
recommandé** : elle couvre toute la chaîne, de l'import des fichiers à la publication des emplois du
temps des AESH, sans rien installer sous Windows.

Les scripts historiques restent disponibles : **[1]** les emplois du temps des élèves notifiés
(`generer_edt.py`), puis **[2]** le recueil et l'affectation en ligne de commande (`aesh.py`).

| Document | Contenu |
|---|---|
| 🖥️ [GUIDE_APPLICATION.md](GUIDE_APPLICATION.md) | **Application « PIAL — Affectation des AESH »** : installation, les neuf étapes, dépannage — [télécharger l'exécutable Windows](https://github.com/patrick-reybaud/pronote-ical-to-sheets-aesh/releases/latest) |
| 📘 [PROCEDURE.md](PROCEDURE.md) | Procédure pas à pas : installation, préparation d'une année scolaire, génération, contrôles, dépannage |
| 🔑 [GUIDE_OAUTH2.md](GUIDE_OAUTH2.md) | Création du client OAuth2 dans Google Cloud (à faire une seule fois) |

## À quoi sert ce programme ?

Dans un établissement scolaire, les élèves en situation de handicap qui bénéficient d'une **notification d'aide
humaine** (MDPH) sont accompagnés par des **AESH** (accompagnants d'élèves en situation de handicap). La personne qui
coordonne les AESH (coordonnateur·rice de PIAL, référent·e handicap, direction…) doit construire l'emploi du temps de
chaque AESH à partir des emplois du temps des élèves accompagnés, en tenant compte du volume d'heures notifié et du
type d'aide (individuelle, mutualisée ou collective).

Le problème : ProNote fournit ces emplois du temps **un par un**, sous forme d'export iCal par élève, dans un format
« calendrier » peu lisible et difficile à partager ; les recopier à la main pour 20 à 30 élèves à chaque rentrée — et à
chaque changement d'emploi du temps — est long et source d'erreurs.

Ce programme automatise toute la chaîne :

1. il lit la **liste des élèves notifiés** dans le fichier de suivi `.ods` (identité, classe, type d'aide, quotité
   horaire, dates de notification, besoins) ;
2. il retrouve, pour chacun, son **export ProNote `.ics`** — même au milieu d'un export de tout l'établissement —
   en s'appuyant sur la date de naissance et le nom (tolérant aux fautes de frappe) ;
3. il reconstruit un **emploi du temps hebdomadaire lisible**, dans la même présentation que ProNote (grille horaire,
   demi-heures, semaines A/B), avec matière, professeur et salle ;
4. il publie le tout dans **un Google Sheet partageable** : un onglet **Récap** (quels élèves ont un emploi du temps,
   lesquels n'en ont pas, quotités, besoins, calendrier des vacances) et **un onglet par élève**.

Résultat : en quelques minutes, la coordination AESH dispose d'un document unique, à jour et partageable avec
l'équipe, pour construire puis ajuster les emplois du temps des accompagnants.

La **chaîne 2** (`aesh.py`) part de là : elle recueille les disponibilités et les affinités de chaque AESH dans un
classeur partagé, puis — c'est l'objectif — calcule l'affectation des AESH aux élèves créneau par créneau et publie
un emploi du temps par AESH. Elle est en cours de construction : voir « Chaîne 2 » plus bas pour ce qui fonctionne
aujourd'hui.

## ⚠️ Données personnelles

Les fichiers d'entrée (exports ProNote, fichier de notifications) et les fichiers de sortie contiennent des données
personnelles d'élèves mineurs (identité, date de naissance, classe, besoins liés au handicap).
**Ils ne doivent jamais être versés dans ce dépôt.** Le [`.gitignore`](.gitignore) exclut les dossiers d'année
(`AAAA-AAAA/`), les `*.ics`, `*.ods`, `sorties/`, les archives, le journal de travail et les identifiants Google.
Le dépôt ne contient que le code et la documentation. Les Google Sheets générés sont créés dans le Drive du compte
qui s'authentifie : partager uniquement avec les personnes habilitées.

## Arborescence

```
pronote-ical-to-sheets-aesh/
├── noyau.py                    # briques communes : ODS, ICS, grille horaire, rendu HTML, Google Sheets
├── generer_edt.py              # chaîne 1 — emplois du temps des élèves notifiés
├── aesh.py                     # chaîne 2 — affectation des AESH (sous-commandes, voir plus bas)
├── aesh_saisie.py              #   ├ classeur de recueil des disponibilités et affinités des AESH
├── aesh_besoins.py             #   └ classeur des difficultés des élèves par matière
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
│   ├── Notif_*.ods             #   notifications : onglets Besoins_élèves et Moyens_AESH_terrain
│   ├── <exports ProNote>/      #   Calendrier_NOM_Prenom_JJMMAAAA.ics (sous-dossiers acceptés)
│   ├── aesh/                   #   fichiers de travail de la chaîne AESH, relisibles et corrigeables
│   │   ├── matieres.csv        #     libellés ProNote → familles de matières
│   │   ├── aesh.csv            #     liste des AESH, quotités, courriels
│   │   ├── classeur_*.json     #     repères de mise en page des classeurs Google (lus par « collecte »)
│   │   ├── dispos.json         #     disponibilités et affinités collectées
│   │   └── difficultes.json    #     difficultés des élèves collectées
│   └── sorties/                #   aperçus HTML, CSV d'appariement, URL des Google Sheets
├── archive_<AAAA-AAAA>/        # snapshots figés des années précédentes
└── NOTES_REPRISE_*.md          # journal de travail
```

## Installation

```bash
git clone git@github.com:patrick-reybaud/pronote-ical-to-sheets-aesh.git
cd pronote-ical-to-sheets-aesh
python3 -m venv venv                 # Python 3.11 recommandé
source venv/bin/activate
pip install -r requirements.txt
```

Puis créer le client OAuth2 Google et déposer `credentials_oauth.json` à la racine : voir [GUIDE_OAUTH2.md](GUIDE_OAUTH2.md).

## Chaîne 1 — emplois du temps des élèves (`generer_edt.py`)

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
4. **Semaines A/B** : la périodicité de chaque cours est **lue, pas devinée**. Le champ `UID` de l'ICS porte
   l'identifiant interne du cours ProNote (`Cours-<id>-<n° séance>-…`) et toutes les occurrences d'un même cours
   partagent cet identifiant. Un cours présent dans toutes les semaines exportées est hebdomadaire ; un cours
   présent dans les seules semaines d'une parité a lieu une semaine sur deux. Aucun vote majoritaire, aucun seuil,
   aucun rapprochement de libellés — deux cours de même matière, même professeur et même salle mais de
   périodicités différentes sont distingués. Tout cours dont la périodicité ne rentre dans aucun de ces deux cas
   (séance annulée, cours commencé en cours d'année, rotation sur plus de deux semaines) est **signalé** au lieu
   d'être rangé arbitrairement. Chaque jour est alors divisé en deux demi-colonnes
   « sem. A | sem. B » : un cours identique toutes les semaines occupe les deux (cellule large), un cours différent
   selon la semaine est affiché côte à côte (deux cellules, A à gauche, B à droite). Toutes les cellules sont bleues.
   L'étiquette A/B suit `SEMAINE_A_REFERENCE` (n° ISO d'une semaine A officielle) dans `generer_edt.py` ;
   à défaut les semaines ISO impaires sont « A ». **L'ICS ProNote ne contient pas l'information A/B.**
   Avec un export d'une seule semaine, la grille est celle de cette semaine (pas d'alternance possible).
5. **Sorties locales** (toujours) : `<année>/sorties/<nom>.html` (aperçu fidèle) et `<nom>_appariement.csv`.
6. **Google Sheet** (`--google`) : classeur `EDT_Eleves_AESH_<année>_<horodatage>`, onglet Récap + un onglet par élève,
   ~6 appels API au total (pas de problème de quota). L'URL est écrite dans `<nom>_google_url.txt`.

## Chaîne 2 — affectation des AESH (`aesh.py`)

Les emplois du temps élèves ci-dessus servent de point de départ : il faut ensuite savoir **quand chaque AESH est
disponible**, puis **qui accompagne qui**. C'est le rôle de `aesh.py`, organisé en sous-commandes qui s'enchaînent.

```bash
source venv/bin/activate

python aesh.py matieres    # 1. référentiel : les libellés ProNote → familles de matières
python aesh.py liste       # 2. liste des AESH, importée du fichier de notifications
python aesh.py saisie      # 3. classeur de recueil des disponibilités (aperçu local)
python aesh.py saisie --google --partager-aesh --echeance "vendredi 2 octobre"
python aesh.py besoins --google    # 4. difficultés des élèves par matière (coordination seule)
python aesh.py collecte            # 5. relire les deux classeurs remplis
```

### 1. `matieres` — référentiel des matières

Les exports ProNote contiennent des dizaines de libellés hétérogènes (`MATHS,PHYSIQ.-CHIMIE`, `TP CUI SEP`,
`AE REST LYCEE`…). Pour que « difficulté ressentie par l'élève » et « aisance de l'AESH » se rencontrent, ils sont
regroupés en **familles** (Français, Maths, TP Cuisine / Pâtisserie…).

La commande relève tous les libellés des ICS, les classe automatiquement et écrit `<année>/aesh/matieres.csv`.
**Vos corrections dans ce fichier sont conservées** : une nouvelle exécution ne touche qu'aux libellés nouveaux, et
signale ceux qu'elle n'a pas su classer. Les familles sont définies par `FAMILLES` et les règles de classement par
`REGLES_FAMILLE`, en tête de `aesh.py`.

### 2. `liste` — liste des AESH

Lit l'onglet `Moyens_AESH_terrain` du `.ods` et en extrait les AESH de l'établissement (`--etablissement`, par défaut
`HOTELIER` ; `--etablissement ""` pour tout le PIAL) dans `<année>/aesh/aesh.csv`.

La quotité retenue est la **Quotité SCO** (temps devant élèves) ; à défaut la quotité *AESH Co* (dispositif collectif,
ULIS), puis *EPP*. Les colonnes `actif` et `quotite_retenue` sont faites pour être ajustées à la main et sont
conservées d'une exécution à l'autre. La commande signale les anomalies du fichier source plutôt que de les
propager : quotités EPP ≠ SCO, colonne courriel contenant autre chose qu'une adresse, quotité absente.

### 3. `saisie` — recueil des disponibilités et des affinités

Crée un classeur Google partageable : un onglet **Mode d'emploi**, un onglet **Liste des AESH**, puis **un onglet
par AESH**.

L'onglet **Liste des AESH** est le poste de pilotage : quotité réellement disponible, courriel, départ
(`Actif` = non) et arrivée en cours d'année (lignes vides en bas) se corrigent là, sans ouvrir de tableur local.
Les colonnes venant du fichier académique (établissement, quotités EPP / SCO / AESH Co) restent verrouillées et
servent de repère. Après un ajout, relancer `aesh.py saisie` crée l'onglet de la nouvelle personne.

Chaque onglet AESH comporte trois blocs.

| Bloc | Contenu | Saisie |
|---|---|---|
| 1 · Disponibilités | grille Lundi→Vendredi en demi-heures | une **case à cocher** par créneau ; totaux par jour et bilan hebdomadaire calculés en direct, comparés à la quotité |
| 2 · Affinités | une ligne par famille de matières | liste déroulante **1 à 5** — *vide = neutre, ne pénalise pas* |
| 3 · Remarques | texte libre | déplacements, temps cantine, contraintes |

**Tout l'onglet est verrouillé** sauf ces trois zones : les formules et la mise en page ne peuvent pas être effacées
par mégarde. ⚠️ Dans un classeur commun, les zones ouvertes le sont pour tous les éditeurs du fichier : la protection
empêche de casser la grille, pas de saisir dans l'onglet d'un collègue. Un cloisonnement strict imposerait un
classeur par AESH.

La grille couvre **7h → 19h** par défaut (`PLAGE_SAISIE_DEFAUT`, modifiable par `--plage 7-24`). La commande indique
quelle part des demi-heures de cours des élèves notifiés cette plage couvre, et liste ce qui tombe dehors — au lycée
hôtelier, les services de restauration du soir.

### 4. `besoins` — difficultés des élèves par matière

Un **classeur séparé**, une ligne par élève notifié et une colonne par famille de matières, en notes de 1 à 5
(vide = neutre, 5 = accompagnement indispensable). C'est le pendant des affinités AESH : le calcul croisera les
deux sur la même famille.

⚠️ **Séparé volontairement** du classeur des AESH : il porte des informations liées au handicap et ne doit être
partagé qu'avec la coordination, jamais avec l'ensemble des accompagnants. Les colonnes d'identité et le texte
d'origine de la colonne `Besoins` sont verrouillés.

Les cases sont **pré-remplies** quand le texte libre de `Besoins` cite explicitement une matière (`LV`, `HG`,
`Sciences`, `gestion`…), avec la note 4, et le texte d'origine reste affiché à côté pour vérification. Le
rapprochement est volontairement prudent : ce qui est ambigu reste vide.

### 5. `collecte` — relire les réponses

Relit les deux classeurs et écrit `dispos.json` (disponibilités, affinités, remarques, liste des AESH) et
`difficultes.json`. Les repères de mise en page sont lus dans les fichiers `classeur_*.json` écrits à la
création : la mise en page n'est donc décrite qu'à un seul endroit.

La commande confronte les heures cochées à la quotité de chaque AESH et signale : rien de coché, dépassement,
heures manquantes, élèves sans aucun besoin noté, et AESH ajoutés dans l'onglet « Liste des AESH » (pour lesquels
il faut relancer `saisie` afin de créer leur onglet).

## Authentification Google

- Client OAuth « application de bureau » : `credentials_oauth.json` (projet Google Cloud, voir [GUIDE_OAUTH2.md](GUIDE_OAUTH2.md)).
- Scopes : `spreadsheets` + `drive.file` (le script ne voit que les classeurs qu'il a créés).
- Tant que l'appli est en statut « Test », le *refresh token* expire au bout de **7 jours** : relancer
  `python auth_google.py` quand `generer_edt.py --google` demande une ré-authentification.
- Le classeur est créé dans le Drive du compte qui s'authentifie ; utiliser `--partager` pour le donner à quelqu'un d'autre.

## Paramètres modifiables (en tête de `noyau.py`, sauf mention contraire)

| Paramètre | Rôle | Défaut |
|---|---|---|
| `ANNEE_DEFAUT` | dossier d'année utilisé sans `--annee` (dans `generer_edt.py` et `aesh.py`) | `"2026-2027"` |
| `ONGLET_ELEVES` | onglet de l'ODS listant les élèves (`generer_edt.py`) | `"Besoins_élèves"` |
| `ONGLET_AESH`, `ETABLISSEMENT_DEFAUT`, `PLAGE_SAISIE_DEFAUT`, `FAMILLES`, `REGLES_FAMILLE` | chaîne AESH (`aesh.py`) | voir le fichier |
| `JOURS` | jours affichés (ajouter `"Samedi"` si besoin) | Lundi → Vendredi |
| `HEURE_MIN_DEFAUT` / `HEURE_MAX_DEFAUT` | plage horaire de base (étendue automatiquement) | 7 / 19 |
| `PAS_MINUTES` | résolution interne | 30 |
| `SEMAINE_A_REFERENCE` | n° ISO d'une semaine « A » officielle | `None` (impaires = A) |
| `HAUTEUR_DEMI_LIGNE` | hauteur (px) d'une demi-ligne de la grille (1 h = 2 demi-lignes) | 28 |
| `LARGEUR_DEMI_COL_JOUR` | largeur (px) d'une demi-colonne « sem. A » / « sem. B » (multi-semaines) | 135 |
| `TAILLE_POLICE_ALT` | taille de police des demi-cellules A/B (réduite de 1 si le texte ne tient pas) | 8 |
| `COULEUR_*`, `LARGEUR_COL_*` | mise en forme du Google Sheet | — |

## Piège connu : formules et locale du classeur

Contrairement à ce que laisse entendre la documentation de l'API, une formule écrite via `formulaValue` est
analysée **selon la locale du classeur**. Les noms de fonctions anglais passent partout (`SUM`, `COUNTIF`, `IF`,
`SUMIF`), mais le **séparateur d'arguments** doit suivre la locale :

```
fr_FR :  =COUNTIF(A1:A4,TRUE)  → #ERROR!        =COUNTIF(A1:A4;TRUE)  → 2
```

Il en va de même des littéraux décimaux (`24,5` et non `24.5`). La locale est donc **imposée à la création**
(`LOCALE_CLASSEUR` dans `noyau.py`) et le séparateur en découle (`SEP_FORMULE`, utilisé par `nombre_formule()`).
Deuxième piège du même ordre : une valeur numérique écrite en texte est ignorée par `SUMIF` — les quotités sont
écrites en `numberValue`.

## Dépendances

Versions figées dans `requirements.txt` (icalendar, gspread 5.12, google-auth, google-auth-oauthlib, pytz).
La lecture de l'ODS se fait sans dépendance externe (XML de `content.xml`).
L'ancien script `ics_to_sheets.py` utilise `worksheet.update(range, values)` dont l'ordre des arguments change en
gspread ≥ 6 : ne pas monter de version sans l'adapter.

## Licence

Ce programme est distribué sous licence [MIT](LICENSE) : libre d'utilisation, de modification et de redistribution,
y compris dans un autre établissement, à condition de conserver la mention de copyright. Il est fourni sans garantie.

La licence couvre **le code et la documentation uniquement** ; elle ne s'applique à aucune donnée d'élève, qui reste
soumise au RGPD et ne doit jamais être publiée (voir la section « Données personnelles » ci-dessus).
