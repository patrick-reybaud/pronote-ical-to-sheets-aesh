# Procédure — génération des emplois du temps des élèves notifiés (suivi AESH)

À qui s'adresse ce guide : la personne qui lance le script à chaque rentrée ou à chaque mise à jour des
exports ProNote. Comptez ~15 minutes une fois les fichiers d'entrée en main (plus l'installation initiale).

```
 Fichier de notifications (.ods)      Exports ProNote (.ics, 1 fichier / élève)
 onglet Besoins_élèves                Calendrier_NOM_Prenom_JJMMAAAA.ics
            │                                        │
            └──────────────┬─────────────────────────┘
                           ▼
                  python generer_edt.py            (1) appariement élève ↔ ICS
                           │                       (2) grille hebdomadaire par élève
            ┌──────────────┴──────────────┐
            ▼                             ▼
  <année>/sorties/*.html         --google → Google Sheet (Récap + 1 onglet / élève)
  <année>/sorties/*_appariement.csv        --partager → partage en écriture
```

---

## 1. Installation initiale (une seule fois par poste)

### 1.1 Récupérer le code

```bash
git clone git@github.com:patrick-reybaud/pronote-ical-to-sheets-aesh.git
cd pronote-ical-to-sheets-aesh
```

### 1.2 Environnement Python

```bash
python3 -m venv venv              # Python 3.11 recommandé (python3 --version)
source venv/bin/activate
pip install -r requirements.txt
```

### 1.3 Identifiants Google (client OAuth2)

Suivre [GUIDE_OAUTH2.md](GUIDE_OAUTH2.md) : création d'un projet Google Cloud, activation des API Sheets + Drive,
écran de consentement, client « Application de bureau ». À la fin, le fichier téléchargé doit être renommé
**`credentials_oauth.json`** et placé à la racine du projet (à côté de `generer_edt.py`).

Si un `credentials_oauth.json` existe déjà (poste précédent, sauvegarde), il suffit de le copier : il n'est pas
lié à une année scolaire.

### 1.4 Première authentification

```bash
python auth_google.py
```

- Le navigateur s'ouvre : se connecter avec **le compte Google dont le Drive recevra les classeurs**.
- Google affiche « Cette application n'est pas validée » → **Paramètres avancés** → **Accéder à … (non sécurisé)** → autoriser.
- Le script écrit `token.json` et vérifie l'accès à l'API : le message `✓ Accès API OK` confirme que tout est prêt.

> `credentials_oauth.json` et `token.json` donnent accès au compte Google : ne jamais les envoyer par mail ni les
> versionner (ils sont exclus par `.gitignore`).

---

## 2. Préparer une année scolaire

### 2.1 Créer le dossier d'année

```bash
mkdir 2026-2027          # format AAAA-AAAA, à la racine du projet
```

Ce dossier est ignoré par git (il contiendra des données personnelles).

### 2.2 Déposer le fichier de notifications (`.ods`)

Copier le fichier de notifications (ex. `Notif_<établissement>_<mois>.ods`) dans le dossier d'année.
Le script utilise l'onglet **`Besoins_élèves`** (nom paramétrable : `ONGLET_ELEVES`). Colonnes attendues
(reconnues par leur intitulé, l'ordre est libre, majuscules/accents indifférents) :

| Intitulé contenant… | Contenu | Obligatoire |
|---|---|---|
| `NOM` et `PRÉNOM` | Nom et prénom de l'élève (`NOM Prénom`) | oui |
| `DATE` et `NAISSANCE` | Date de naissance, `JJ/MM/AAAA` — **clé d'appariement avec les ICS** | oui |
| `NIVEAU` | Niveau (2nde, 1re…) | non |
| `TYPE` | Type d'aide (I / M / CO) | non |
| `HEURES` | Quotité horaire notifiée | non |
| `DATE DÉBUT` / `DATE FIN` | Dates de la notification | non |
| `REMARQUES` | **Classe de l'année en cours** (convention du fichier) | non |
| `BESOINS` | Besoins de l'élève (texte libre) | non |

Les lignes dont le nom est vide sont ignorées. S'il y a plusieurs `.ods` dans le dossier, le script prend le
dernier par ordre alphabétique et l'indique (`⚠ Plusieurs .ods trouvés`) : ne garder qu'un seul fichier pour éviter
toute ambiguïté.

### 2.3 Déposer les exports ProNote (`.ics`)

- Un fichier par élève, nommé par ProNote **`Calendrier_NOM_Prenom_JJMMAAAA.ics`** (`JJMMAAAA` = date de naissance).
  Conserver les noms générés par ProNote : les noms composés avec `_` sont gérés (le prénom est le dernier segment).
- Les déposer dans un sous-dossier du dossier d'année, ex. `2026-2027/EDT_élèves_2026_2027/` (les sous-dossiers
  sont parcourus récursivement).
- L'export de **tout l'établissement** est accepté : seuls les élèves présents dans l'ODS sont traités. Les fichiers
  dont le nom ne suit pas la convention sont comptés comme « non reconnus » dans la console.
- **Période d'export : au moins 4 semaines consécutives de cours normaux** (2 semaines A + 2 semaines B), en
  **évitant la semaine de rentrée** — ex. S37 → S40 (07/09 → 02/10/2026). ProNote exporte chaque cours comme un
  événement daté (pas de récurrence) : le script ne peut afficher que ce qui a été exporté. Un export sur **une seule
  semaine** donne l'emploi du temps de cette semaine-là, colonnes datées, sans A/B — et si c'est la semaine de rentrée,
  le lundi est vide et les classes qui rentrent plus tard n'ont aucun cours. Avec plusieurs semaines, l'alternance
  **A/B** est détectée automatiquement (cours présent dans ≥ 50 % des semaines de sa parité).
- L'export iCal par élève est réalisé côté établissement dans ProNote (profil administration / vie scolaire).
  *À compléter si besoin : chemin de menu exact utilisé dans votre établissement.*

### 2.4 Ajuster les paramètres (si nécessaire)

En tête de `generer_edt.py` :

- `ANNEE_DEFAUT` : mettre l'année en cours pour éviter de taper `--annee` à chaque fois.
- `SEMAINE_A_REFERENCE` : numéro ISO d'une semaine officiellement « A » dans l'établissement (ex. `36`). Sans cette
  valeur, les semaines ISO impaires sont étiquetées « A » — l'alternance est correcte mais l'étiquette peut être inversée.
- `JOURS` : ajouter `"Samedi"` si des cours ont lieu le samedi (sinon ils sont comptés « hors jours affichés »).

---

## 3. Générer les emplois du temps

### 3.1 Aperçu local (sans rien envoyer à Google)

```bash
source venv/bin/activate
python generer_edt.py --annee 2026-2027
```

Lire la console :

```
📋 Notifications : Notif_….ods (onglet 'Besoins_élèves')
   24 élève(s) à traiter
📁 2026-2027/EDT_élèves_2026_2027 : 753 fichier(s) ICS
🔗 Appariement élèves ↔ fichiers ICS
  ✓ NOM Prénom        12/05/2009 → Calendrier_NOM_Prenom_12052009.ics   28 cours  (date de naissance + nom)
  ✗ NOM Prénom        01/01/2010 → —                                      0 cours  (aucun fichier ICS correspondant)
🕒 Grille 7h → 19h (étendue jusqu'à 24h pour les élèves concernés)
📅 Semaine(s) couverte(s) par les exports : S37 (07/09 → 13/09/2026), S38 (14/09 → 20/09/2026), S39 (…), S40 (…)
   Alternance A/B : semaine A de référence = ISO 35 (impaires = A, par défaut)
   (ou « ⚠ Une seule semaine exportée : pas de détection d'alternance A/B possible » si l'export ne couvre qu'une semaine)
💾 Aperçu local : 2026-2027/sorties/EDT_Eleves_AESH_2026-2027_<horodatage>.html
💾 Appariement : 2026-2027/sorties/EDT_Eleves_AESH_2026-2027_<horodatage>_appariement.csv
```

Signification de la colonne « explication » de l'appariement :

| Explication | Sens | Action |
|---|---|---|
| `date de naissance + nom` | appariement sûr | — |
| `… (orthographe différente)` | même date de naissance, nom proche mais pas identique | vérifier que c'est bien le même élève ; corriger l'orthographe dans l'ODS |
| `même date de naissance mais nom trop différent (…)` | homonyme de date probable | vérifier, corriger le nom dans l'ODS ou demander l'export |
| `nom seul — DATE DE NAISSANCE DIFFÉRENTE (…) à vérifier` | nom identique, date différente | **vérifier la date de naissance** dans l'ODS ou dans ProNote |
| `aucun fichier ICS correspondant` | pas d'export pour cet élève | demander l'export ProNote (élève non encore inscrit ?) |

### 3.2 Contrôler les sorties

1. Ouvrir le `.html` dans un navigateur : c'est un rendu fidèle de ce qui sera envoyé dans Google Sheets
   (Récap en tête, puis un onglet par élève). Vérifier quelques élèves : blocs de cours, demi-heures, services du soir.
2. Ouvrir le `_appariement.csv` (séparateur `;`) : une ligne par élève de l'ODS avec le fichier ICS retenu
   (`AUCUN` si non trouvé) et l'explication.
3. Un élève apparié à **0 cours** signifie que son export est vide (classe qui n'a pas encore cours cette semaine).

Corriger l'ODS ou compléter les exports, puis relancer l'aperçu jusqu'à ce que l'appariement soit satisfaisant.
Chaque lancement crée de nouveaux fichiers horodatés dans `sorties/` ; les anciens peuvent être supprimés.

### 3.3 Créer le Google Sheet

```bash
python generer_edt.py --annee 2026-2027 --google
# avec partage en écriture (option répétable) :
python generer_edt.py --annee 2026-2027 --google --partager prenom.nom@ac-academie.fr --partager autre@exemple.fr
# avec un nom de classeur explicite :
python generer_edt.py --annee 2026-2027 --google --nom "EDT_Eleves_AESH_2026-2027_rentree"
```

- Si le jeton est périmé, le script tente de le rafraîchir puis, à défaut, rouvre le navigateur (même écran qu'en 1.4).
  Vous pouvez aussi lancer `python auth_google.py` avant.
- Le classeur est créé dans le Drive du compte authentifié (`EDT_Eleves_AESH_<année>_<horodatage>` par défaut).
- L'URL s'affiche en fin d'exécution et est enregistrée dans `sorties/<nom>_google_url.txt`.
- Les personnes indiquées par `--partager` reçoivent une notification Google avec un accès en écriture.

### 3.4 Vérifier dans Google Sheets

- Onglet **Récap** : une ligne par élève de l'ODS ; les lignes **rouges** = élèves sans emploi du temps.
  En bas, le calendrier ProNote des journées entières (fériés, vacances) si présent dans les exports.
- Onglets élèves : titre = `NOM Prénom — classe — aide humaine : <type> <heures> h`, sous-titre = date de naissance,
  dates de notification, besoins, fichier source, date de génération et légende de lecture.
- Export **multi-semaines** : chaque jour est divisé en deux demi-colonnes **« sem. A | sem. B »** (sous-en-tête).
  Une cellule sur toute la largeur du jour = cours identique toutes les semaines ; deux cellules
  côte à côte = cours différent en semaine A (gauche) et en semaine B (droite). Toutes les cellules sont bleues ; le texte des demi-cellules A/B est en
  police 8 (7 si nécessaire) : « matière » puis « prof · salle (groupe) ».
- Export d'**une seule semaine** : une colonne par jour, colonnes datées, pas de demi-colonnes A/B.
- Les lignes d'en-tête (4 en multi-semaines, 3 sinon) sont figées ; les colonnes ne le sont pas (limitation Google
  avec le titre fusionné).

---

## 4. Mises à jour en cours d'année

Le script **crée un nouveau classeur à chaque exécution** ; il ne met pas à jour un classeur existant.

1. Remplacer / compléter les exports ProNote dans le dossier d'année (supprimer les anciens `.ics` s'ils sont remplacés
   par un export plus complet).
2. Mettre à jour l'ODS si la liste des élèves a changé.
3. Relancer l'aperçu (3.1 – 3.2) puis l'export Google (3.3).
4. Prévenir les destinataires du nouveau lien ; supprimer ou archiver l'ancien classeur dans le Drive si besoin.

---

## 5. Dépannage

| Symptôme | Cause | Solution |
|---|---|---|
| `❌ credentials_oauth.json introuvable` | client OAuth absent de la racine | suivre [GUIDE_OAUTH2.md](GUIDE_OAUTH2.md) ou copier le fichier existant |
| `Jeton impossible à rafraîchir … → nouvelle authentification` ou `invalid_grant` | appli OAuth en statut « Test » : le jeton expire après 7 jours | se ré-authentifier (navigateur) ; voir GUIDE_OAUTH2 pour passer l'appli en production et supprimer cette limite |
| Le navigateur ne s'ouvre pas | environnement sans navigateur par défaut | copier l'URL affichée dans la console et l'ouvrir manuellement |
| `❌ Aucun fichier .ods` / `.ics` | fichiers absents ou mauvais dossier | vérifier `--annee` et le contenu du dossier d'année |
| `Colonnes NOM/Date naissance introuvables` | première ligne de l'onglet ≠ en-têtes attendus | vérifier le nom de l'onglet (`Besoins_élèves`) et les intitulés de colonnes (§ 2.2) |
| Élève `✗` dans la console | date de naissance ou nom incohérents entre l'ODS et le nom du fichier ICS, ou export manquant | voir tableau § 3.1 |
| `… nom(s) non reconnus` | fichiers `.ics` ne suivant pas `Calendrier_NOM_Prenom_JJMMAAAA.ics` | renommer selon la convention |
| `⚠ Une seule semaine exportée` | export ProNote sur une seule semaine | normal ; refaire un export sur ≥ 4 semaines hors rentrée (§ 2.3) pour obtenir la semaine type et l'alternance A/B |
| Étiquettes A/B inversées | calendrier A/B de l'établissement non aligné sur la parité ISO | renseigner `SEMAINE_A_REFERENCE` (§ 2.4) |
| `⚠ N cours hors jours affichés` dans le sous-titre | cours le samedi (ou dimanche) | ajouter `"Samedi"` à `JOURS` |
| Erreur Google `429` / quota | trop d'appels API (rare : ~6 appels par exécution) | attendre une minute et relancer |
| `ModuleNotFoundError` | venv non activé ou dépendances non installées | `source venv/bin/activate` puis `pip install -r requirements.txt` |

---

## 6. Fin d'année : archiver

1. Déplacer le dossier d'année dans un dossier d'archive : `mv 2026-2027 archive_2026-2027` (reste hors git).
2. Créer le dossier de l'année suivante (§ 2) et mettre à jour `ANNEE_DEFAUT`.
3. Les identifiants Google (`credentials_oauth.json`, `token.json`) et le `venv/` ne changent pas.

---

## 7. Check-list rapide (rentrée)

- [ ] `source venv/bin/activate`
- [ ] `credentials_oauth.json` présent ; `python auth_google.py` → `✓ Accès API OK`
- [ ] Dossier `AAAA-AAAA/` créé, `ANNEE_DEFAUT` à jour
- [ ] ODS déposé, onglet `Besoins_élèves`, dates de naissance au format `JJ/MM/AAAA`
- [ ] Exports `.ics` déposés (≥ 4 semaines consécutives hors semaine de rentrée), `SEMAINE_A_REFERENCE` renseigné si connu
- [ ] `python generer_edt.py` → tous les élèves `✓` (ou absences justifiées), aperçu HTML contrôlé
- [ ] `python generer_edt.py --google --partager …` → URL notée, classeur vérifié, destinataires prévenus
