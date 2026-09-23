# PIAL — Affectation des AESH · guide de l'application

Application de bureau qui part des données réelles du PIAL et produit les emplois du temps des AESH.
Elle fonctionne **entièrement sur le poste** : aucune donnée d'élève ne sort de l'ordinateur.

---

## Démarrer

### Windows — poste de l'utilisatrice finale

**Rien à installer.** Téléchargez l'exécutable depuis la page des versions :

> **[PIAL-Affectation-AESH.exe](https://github.com/patrick-reybaud/pronote-ical-to-sheets-aesh/releases/latest)** (57 Mo)

Placez-le où vous voulez et **double-cliquez dessus**. Une fenêtre noire s'ouvre — c'est
l'application qui tourne, laissez-la ouverte — et l'interface s'ouvre dans le navigateur. Pour
quitter : fermez la fenêtre noire.

Au premier lancement, Windows peut afficher un avertissement SmartScreen parce que le fichier n'est
pas signé électroniquement : **« Informations complémentaires »** puis **« Exécuter quand même »**.
C'est normal pour un logiciel diffusé sans certificat d'éditeur ; le fichier est compilé
automatiquement à partir du code de ce dépôt, sur une machine GitHub, et son empreinte est
vérifiable dans le journal de compilation.

*Autre méthode, si vous préférez travailler depuis le code source* : installer Python 3.11 en
cochant « Add python.exe to PATH », lancer une fois `installer_windows.bat`, puis
`demarrer_windows.bat` à chaque utilisation.

### macOS — poste de test

```bash
cd pronote-ical-to-sheets-aesh
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Ou double-cliquer sur `demarrer_mac.command`.

L'interface s'ouvre sur `http://127.0.0.1:8765/`. Si ce port est occupé, l'application en choisit un
autre et l'affiche dans la fenêtre.

---

## Où sont les données

| Quoi | Où |
|---|---|
| Projets, imports, résultats, exports | `Documents/PIAL-AESH/<nom du projet>/` (Windows et Mac) |
| Fichiers importés (recopiés) | `…/<projet>/sources/` |
| Emplois du temps produits | `…/<projet>/sorties/` |
| Tout l'état du travail | `…/<projet>/projet.json` |

Un projet est autonome : le copier suffit à le transporter d'un poste à l'autre.

---

## Les neuf étapes

### 1 · Projet
Créer un projet par établissement et par année, par exemple `Calanques-2 2026-2027`.
La liste des projets existants indique pour chacun ce qu'il contient — fichier PIAL, nombre
d'emplois du temps, semaines types, AESH renseignés, dernier calcul — et permet de l'ouvrir ou de le
**supprimer définitivement** (avec confirmation : les fichiers importés et les sorties sont effacés).

### 2 · Import des données
Deux dépôts, par glisser-déposer ou en cliquant :

- **Fichier de gestion du PIAL** (`.ods` ou `.xlsx`) — les élèves notifiés et les moyens AESH.
- **Exports ProNote** (`.ics`) — un fichier par élève. On peut déposer **le dossier entier** ;
  les sous-dossiers sont parcourus. Plusieurs exports successifs se complètent : quand un élève est
  présent dans deux exports, **le plus complet est conservé**.

Tout ce qui n'a pas pu être lu comme prévu est affiché : colonnes non reconnues, dates illisibles,
courriels invalides, écarts entre quotités EPP et SCO, fichiers au nom non reconnu.

### 3 · Établissement
Le tableau donne, pour chaque établissement, ses élèves notifiés et ses AESH. Tout le travail qui
suit ne porte que sur l'établissement choisi ; on peut en changer sans rien perdre.

### 4 · Semaines types
**C'est l'étape qui évite les approximations.** Un export ProNote décrit un *calendrier*, pas un
emploi du temps. Plutôt que de deviner une périodicité, on choisit **deux semaines de référence
consécutives** :

- un cours présent dans **les deux** semaines a lieu **toutes les semaines** ;
- un cours présent dans **une seule** a lieu **une semaine sur deux**.

L'application propose les deux semaines consécutives où **le plus d'élèves ont cours** — et non les
plus fournies en séances : une semaine très chargée où deux élèves sont en stage les laisserait sans
emploi du temps. Un élève qui n'a malgré tout aucun cours ces deux semaines-là (stage, arrivée
tardive) n'est pas abandonné : ses propres semaines les plus fournies prennent le relais, l'alternance
restant alignée sur celle de l'établissement. Le repli est affiché.

**Quelle semaine est « A » ?** L'export ProNote ne le dit pas : c'est une convention propre à
l'établissement. L'application appelle « A » la première des deux semaines choisies. Si l'étiquette
est inversée par rapport au calendrier officiel, le bouton **Inverser A et B** la remet à l'endroit —
l'alternance, elle, est juste dans les deux cas. On règle aussi ici la **plage horaire** : les créneaux
qui en sortent ne seront jamais couverts, et l'application dit combien cela représente.

#### Quand un élève n'a pas d'emploi du temps

L'écran « Semaines types » nomme les élèves concernés et dit ce qui a été trouvé, puis propose
**Associer…**. Une fenêtre liste alors les fichiers ProNote les plus proches, ceux qui portent la
**même date de naissance** en tête, avec un filtre par nom. Choisir un fichier force l'association
définitivement (elle est marquée 🔒 et reste modifiable).

C'est le recours pour les erreurs de saisie : une date de naissance fautive d'un côté ou de l'autre
suffit à empêcher le rapprochement automatique alors que le nom correspond parfaitement. Le volet
**Détail de l'appariement** montre les 25 élèves triés du plus douteux au plus sûr — un appariement
à moins de 100 % mérite un coup d'œil, un appariement « sur le nom seul » encore plus.

### 5 · Élèves & efforts
Une note de **0 à 5 par matière** : l'effort que cette matière demande à cet élève, 5 signifiant
« accompagnement indispensable ». Une case **vide vaut neutre** — elle ne dit pas « aucun besoin »,
elle dit « rien de particulier ». **0 retire la matière** de l'accompagnement pour cet élève.

Arts appliqués, EPS et Chef-d'œuvre valent **1 par défaut** (affiché en grisé) : l'accompagnement y
est rarement décisif. Écrasez la valeur si ce n'est pas le cas.

En haut de l'écran, décocher une famille la **retire de l'accompagnement pour tous les élèves** : ces
heures sortent du besoin à couvrir et ne comptent donc plus comme un manque. Le tableau perd aussitôt
la colonne correspondante — il ne reste que des matières réellement accompagnées.

Les libellés ProNote qu'aucune règle ne reconnaît (« Réservation de salle », « Journée d'intégration »,
« Évaluations nationales »…) ne sont pas des cours : ils sont **écartés d'office** et listés en bas
d'écran, où l'on peut en rattacher un à une vraie famille s'il s'agissait bien d'un cours.

La colonne **Notifié** est modifiable : c'est le recours quand le fichier PIAL laisse une quotité à
zéro alors que l'élève a bien des droits.

### 6 · AESH & affinités
Même principe, côté accompagnants : de 1 à 5, l'aisance dans chaque famille de matières.

Les **disponibilités** se renseignent de deux façons :

- **directement** : cliquer ou faire glisser sur la grille, qui s'enregistre toute seule ;
- **par le classeur de recueil** : le bouton produit un `.xlsx` avec un onglet par AESH. Il circule
  comme on veut — courriel, Drive partagé, Google Sheets — et se redépose ici une fois rempli.
  Disponibilités, affinités et remarques sont relues d'un coup.

### 6 bis · Mutualisation
Mutualiser, c'est confier deux élèves au même AESH sur un même créneau — possible seulement s'ils
suivent **exactement le même cours** (même identifiant ProNote, pas seulement la même matière). C'est
le principal levier quand les heures manquent : une heure mutualisée sert deux élèves en n'en
consommant qu'une.

L'écran donne deux tableaux. Le premier fixe la **règle par élève** : par défaut l'aide individuelle
est exclusive et l'aide mutualisée ne l'est pas, mais on peut trancher autrement — un élève en aide
mutualisée qui ne supporte pas le partage (« jamais mutualisé »), ou un élève en aide individuelle
qui peut très bien être accompagné avec un camarade du même cours (« mutualisation autorisée »).

Le second liste les **couples d'élèves qui partagent réellement des cours**, avec le volume horaire
en commun — c'est là que se voient les gains possibles. Chaque couple peut être marqué
« incompatibles » (deux élèves qu'on ne peut pas regrouper) ou « à regrouper » (à privilégier).

### 7 · Pondérations & règles
L'écran montre **toutes les règles**.

Les **règles dures** ne sont jamais violées : disponibilité, présence de l'élève, non-ubiquité,
quotités, accompagnement exclusif, mutualisation dans le même cours seulement, incompatibilités entre
élèves, interdictions et affectations imposées.

Deux plafonds se règlent ici. La **mutualisation** : au plus *N* élèves par AESH sur un même créneau.
La **continuité** : au plus *N* AESH différents auprès d'un même élève — une règle dure, parce que
« pas plus de trois personnes autour de cet enfant » est une exigence, pas une préférence à pondérer.
Mesuré sur un établissement réel : plafond 2 → 87 % de couverture, plafond 3 → 92 %, sans plafond
→ 93 % mais jusqu'à 7 accompagnants pour un même élève.

**Un cours n'est jamais morcelé.** Un cours commencé est mené à son terme par la même personne : on
n'accompagne pas un élève deux heures d'un TP qui en dure cinq pour le laisser seul ensuite. C'est
pourquoi l'unité d'affectation est le cours entier, et non la demi-heure.

Les **objectifs pondérés** se règlent au curseur. Ils s'arbitrent les uns contre les autres :
monter l'équité répartit mieux le manque mais fait baisser la couverture totale ; monter la
continuité réduit le nombre d'accompagnants par élève. Il n'y a pas de réglage optimal, seulement
des choix — c'est pourquoi ils sont tous exposés.

Le **tableau croisé élèves ✕ AESH** permet d'agir binôme par binôme : `interdire` exclut totalement,
`imposer` garantit au moins un créneau ensemble, `favoriser` et `éviter` pèsent sans contraindre.

### 8 · Calcul
Le calcul explore les combinaisons et retient la meilleure selon les règles. Il s'arrête au temps
imparti en rendant la meilleure solution trouvée : allonger le temps améliore la qualité, **sans
jamais violer une règle dure**. 30 secondes suffisent pour travailler, 5 minutes pour un résultat
final.

### 9 · Emplois du temps
Chaque élève a **sa couleur**, rappelée en légende ; un créneau partagé par deux élèves apparaît en
bandes obliques. Les créneaux consécutifs identiques sont **fusionnés en un seul bloc**, comme dans
ProNote, au lieu de répéter la même chose toutes les demi-heures.

Couverture globale, taux de l'élève le moins bien servi, bilan par élève et par AESH, et surtout
**les heures non couvertes avec leur cause** : aucun AESH disponible sur le créneau, quotités
épuisées, ou interdiction saisie. Export en `.xlsx` (une feuille par AESH plus une synthèse) et en
`.html` imprimable.

---

## Ce qu'il faut savoir sur les données

**L'export ProNote doit couvrir tous les élèves notifiés.** C'est le point de vigilance principal :
un export partiel produit des élèves sans emploi du temps, qui ne peuvent recevoir aucune
affectation. L'application le signale dès l'étape 4, mais elle ne peut pas inventer les données
manquantes. Vérifier dans ProNote que la sélection d'élèves de l'export couvre bien la liste notifiée.

**Les heures se comptent sur deux semaines.** Une semaine A plus une semaine B : c'est la seule unité
dans laquelle un cours hebdomadaire et un cours de quinzaine se comparent sans approximation. Les
affichages sont ramenés en heures par semaine.

**La mutualisation ne consomme qu'une fois le service.** Un AESH qui suit deux élèves d'un même cours
sur le même créneau utilise une demi-heure de sa quotité, pas deux. La colonne « heures-élèves » de
l'export montre l'écart, c'est-à-dire ce que la mutualisation fait gagner.

---

## En cas de souci

| Symptôme | Cause probable |
|---|---|
| « Aucun onglet d'élèves notifiés trouvé » | Ce n'est pas le fichier PIAL, ou ses onglets ont été renommés. L'application liste les onglets qu'elle a vus. |
| Beaucoup d'élèves sans emploi du temps | L'export ProNote ne couvre pas tous les élèves notifiés (voir ci-dessus). |
| « Aucune solution ne respecte toutes les règles » | Une interdiction ou une affectation imposée rend le problème insoluble. Desserrer, puis relancer. |
| Le calcul ne progresse plus | Normal : il rend la meilleure solution trouvée. Allonger le temps si besoin. |
| Le port 8765 est occupé | L'application en prend un autre et l'affiche au démarrage. |

---

## Mettre à jour l'application

Chaque nouvelle version est publiée sur la
[page des versions](https://github.com/patrick-reybaud/pronote-ical-to-sheets-aesh/releases).
Remplacez simplement l'ancien `.exe` par le nouveau : **vos projets ne sont pas touchés**, ils
vivent dans `Documents/PIAL-AESH/` et sont indépendants du programme.

---

## Ce que l'application ne fait pas

Elle ne décide pas à la place de la coordination : elle propose une affectation cohérente avec les
règles données, montre ce qu'elle n'a pas pu satisfaire et pourquoi, et laisse corriger puis
recalculer. Les arbitrages — qui accompagne qui, ce qui compte le plus quand tout ne peut pas être
satisfait — restent des décisions humaines, et l'écran « Pondérations » est fait pour les rendre
explicites plutôt que de les enfouir dans le code.
