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
| **Dossier de travail** | `PIAL-AESH/` dans votre dossier personnel — `C:\Users\<vous>\PIAL-AESH` sous Windows, `/Users/<vous>/PIAL-AESH` sur Mac. Le bouton **Ouvrir le dossier de travail**, sur l'écran « Projet », vous y emmène directement. |
| **Tout le travail d'un projet** | `…/<projet>/`**`projet.json`** |
| Fichiers importés (recopiés) | `…/<projet>/sources/` — le fichier PIAL, et les `.ics` dans `sources/ics/` |
| Emplois du temps et archives produits | `…/<projet>/sorties/` |
| **Journal de l'application** | `PIAL-AESH/journal.log` — à joindre en cas de problème |

**`projet.json` contient absolument tout le travail** : établissement retenu, semaines types, plage
horaire, efforts par matière, affinités, disponibilités des AESH, matières retirées, règles de
mutualisation, incompatibilités entre élèves, pondérations, appariements forcés, cours confiés à la
main et dernier résultat calculé. C'est un fichier texte lisible, que l'on peut ouvrir, sauvegarder
ou versionner.

### Déplacer un projet d'un poste à l'autre

Sur l'écran **Projet**, le bouton **Exporter…** produit une archive `.zip`, avec deux choix :

| | Contenu | Poids mesuré |
|---|---|---|
| **Tout** *(recommandé)* | `projet.json`, fichier PIAL **et** exports ProNote | **≈ 9 Mo** pour 1 920 emplois du temps — les `.ics` se compressent à 96 % |
| **Réglages seuls** | `projet.json` + le fichier PIAL | ≈ 250 Ko, mais les `.ics` seront à redéposer |

Sur l'autre poste, déposez l'archive dans la zone **Importer un projet** du même écran. Avec
l'export léger, il reste à redéposer les `.ics` à l'étape « Import » : **tout le reste du travail est
conservé**, y compris les appariements forcés et le dernier calcul.

Certains navigateurs — Safari en particulier — décompressent les archives dès le téléchargement :
vous obtenez alors un **dossier** et non un `.zip`. Ce n'est pas un problème, **déposez le dossier
tel quel**, l'import accepte les deux.

Si le projet existe déjà sous ce nom, une copie numérotée est créée — rien n'est jamais écrasé.

Copier le dossier du projet à la main fonctionne tout aussi bien.

---

## Les neuf étapes

### 1 · Projet
Créer un projet par établissement et par année, par exemple `Calanques-2 2026-2027`.
La liste des projets existants indique pour chacun ce qu'il contient — fichier PIAL, nombre
d'emplois du temps, semaines types, AESH renseignés, dernier calcul — et permet de l'ouvrir ou de le
le **retirer** : il n'est pas effacé mais déplacé, horodaté, dans le sous-dossier `.corbeille` de
`PIAL-AESH`, d'où vous pouvez le ressortir à la main.

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
Même principe, côté accompagnants : de 1 à 5, l'aisance dans chaque famille de matières. **0 est un
refus** : l'accompagnant ne sera jamais placé sur cette matière, quelles que soient les circonstances.

Un bloc **AESH habituel de chaque élève** répond à la question telle qu'elle se pose sur le terrain :
un élève, son accompagnant. On désigne l'AESH dans la liste, et le calcul le **privilégie**
d'emblée — une colonne « Force » permet de passer à **imposer** si ce doit être garanti. Un seul AESH
souhaité par élève : en désigner un autre remplace le précédent.

Les **interdictions** et les préférences plus fines se règlent dans le tableau croisé de l'écran
« Pondérations », qui reste la vue complète.

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

### 6 ter · Stages, journées d'intégration & CCF

**Ce que ProNote exporte vraiment.** Vérifié sur 1 120 fichiers et 153 771 événements :

| | Dans l'export ? | Comment |
|---|---|---|
| Stage / PFMP | **non** | aucune occurrence — seule trace : l'élève n'a aucun cours |
| CCF | **non** | aucune occurrence |
| Journée d'intégration | **oui** | libellé `JOURNEE D'INTEGRATION`, catégorie `Cours - Exceptionnel` |
| Sortie pédagogique | **oui** | catégorie `Sorties Pédagogiques` |
| Dispense (présence facultative) | **oui** | libellé `DISPENSE - Présence Facultative : …` |

Le bouton **Proposer d'après les exports ProNote** exploite ces signatures : il propose les journées
d'intégration et les sorties pédagogiques telles qu'elles sont écrites, et signale les **absences
longues** — un élève sans aucun cours pendant une ou plusieurs semaines entières alors que les
autres en ont — qui sont l'indice d'un stage. Rien n'est appliqué d'office : ce sont des
propositions, à confirmer et à nommer.

Les **dispenses** sont traitées automatiquement : un cours en présence facultative ne crée aucun
besoin d'accompagnement et ne consomme donc pas d'heures.

Le reste — stages et CCF — se déclare ici : nom, type, dates, élèves concernés.

Pendant un **stage** ou une **journée d'intégration**, les élèves concernés ne sont pas accompagnés,
et leurs AESH sont **redistribués sur les autres élèves** : chaque période reçoit sa propre
affectation, calculée sur le calendrier réel de la période et non sur les semaines types.

Un **CCF** fonctionne à l'inverse : les élèves concernés doivent être accompagnés sur toute la durée
de l'épreuve. C'est une règle dure ; si elle ne peut pas être tenue, le calcul le dit au lieu de
l'ignorer.

Chaque période se calcule séparément, et son résultat apparaît **sous l'emploi du temps de chaque
AESH** dans l'export. Si des élèves n'ont aucun cours sur les semaines de la période, l'application
le signale : c'est souvent le signe que l'export ProNote ne couvre pas ces semaines-là.

### 7 · Pondérations & règles
L'écran montre **toutes les règles**.

Les **règles dures** ne sont jamais violées : disponibilité, présence de l'élève, non-ubiquité,
quotités, accompagnement exclusif, mutualisation dans le même cours seulement, incompatibilités entre
élèves, interdictions et affectations imposées.

Trois réglages se font ici. La **pause méridienne** : chaque AESH doit disposer, **chaque jour
travaillé**, d'au moins une heure libre d'affilée entre 11 h et 14 h. C'est une règle dure, la durée
et la fenêtre sont modifiables, et `0 minute` la désactive. Sur un établissement réel elle coûte
environ 2 points de couverture — le prix d'une pause qui existe vraiment.

La **mutualisation** : au plus *N* élèves par AESH sur un même créneau.
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
Le calcul cherche la meilleure combinaison et **s'arrête quand il n'améliore plus** — pas au bout
d'un temps fixé d'avance, qui ne voudrait rien dire pour vous. Trois niveaux d'exigence règlent
seulement la patience : combien de temps sans le moindre progrès avant de considérer que le calcul a
donné ce qu'il avait.

Le résultat indique combien d'améliorations ont été trouvées et pourquoi la recherche s'est arrêtée
— optimum atteint, plus d'amélioration, ou temps maximal. Une solution rendue respecte **toujours**
toutes les règles dures ; chercher plus longtemps ne fait qu'affiner la qualité.

### 9 · Emplois du temps

Trois vues sur le même travail : **Élèves**, **AESH**, **Synthèse & exports**. L'écran est accessible
dès que les semaines types sont choisies — on peut corriger un emploi du temps avant même le premier
calcul.

Dans les deux grilles, les créneaux consécutifs identiques sont **fusionnés en un seul bloc**, comme
dans ProNote. Et lorsqu'un cours a lieu **toutes les semaines**, la cellule couvre les deux
demi-colonnes « sem. A » et « sem. B » : elles ne se séparent que là où les deux semaines diffèrent
réellement. C'est exactement le découpage des exports — ce qu'on voit à l'écran est ce qu'on
imprimera.

#### Vue « Élèves » — celle où l'on agit

Un élève à la fois, sa semaine entière sous les yeux. Chaque cours porte **la couleur de son
accompagnant**, rappelée en légende ; en gris clair les cours à accompagner que personne ne prend, en
gris plus pâle ceux qu'on a retirés de l'accompagnement, avec leur motif (dispense ProNote, famille
de matières décochée, effort mis à 0).

**Cliquez sur un cours** : un volet s'ouvre, avec deux choses.

*Qui l'accompagne.* Le menu propose les AESH **disponibles sur toute la durée du cours**, non
interdits pour cet élève et qui ne refusent pas la matière — les trois mêmes conditions que le
calcul, pour qu'on ne propose jamais une affectation qu'il déclarerait ensuite impossible. « libre »
signifie que l'AESH n'a rien à ce moment-là, « occupé » qu'il faudra déplacer ce qu'il y fait. On
peut aussi choisir **personne**, pour assumer un cours sans accompagnement et que le calcul cesse d'y
consacrer des heures utiles ailleurs.

> **Choisir quelqu'un vaut verrou.** C'est une règle dure : au recalcul, tout le reste se réorganise
> autour, ou le calcul annonce qu'il n'y arrive pas. Pour figer une affectation que le calcul a
> trouvée lui-même, il suffit de la choisir à nouveau dans le menu — elle porte alors un cadenas.
> Les boutons **Verrouiller tout ce qu'il a obtenu** et **Libérer ses verrous** font la même chose
> pour l'élève entier.

*Le cours lui-même.* Jour, heure de début, durée, matière, salle : tout se corrige. On peut aussi
**supprimer** un cours ou en **ajouter** un que ProNote ne connaît pas, sur la semaine A, la B ou les
deux. Utile quand un élève change de groupe, quand un cours a été déplacé, ou quand l'export est
simplement en retard sur la réalité.

Ces corrections **vivent dans le projet, à côté de ProNote** : elles ne modifient aucun fichier
importé et se réappliquent toutes seules après un nouvel import. Un cours corrigé est signalé dans la
grille, et le bouton **Revenir à ProNote** annule la correction. Si la correction plaçait l'élève à
deux endroits en même temps, elle est refusée en nommant le cours qui gêne : un emploi du temps
impossible ne se rattrape pas au calcul suivant.

Les corrections valent partout : dans le calcul, dans les exports, et pendant les périodes de stage
ou de CCF.

#### Vue « AESH » — lecture seule

La semaine de chaque accompagnant, **une couleur par élève suivi** ; un créneau partagé par deux
élèves apparaît en bandes obliques. Quotité, heures affectées, disponibilités déclarées et nombre
d'élèves sont rappelés en haut.

Volontairement non modifiable : on n'affecte pas un élève depuis la grille de son accompagnant sans
voir le reste de sa journée à lui. Tout se fait côté élève.

#### Vue « Synthèse & exports »

Le bilan chiffré, les exports, et le tableau **Ajuster les affectations** — la même chose que la
grille, mais en liste : pratique pour balayer tous les cours d'un coup, notamment ceux que personne
n'accompagne. Filtrez par élève, ou n'affichez que les cours non accompagnés, ou ceux pour lesquels
un AESH est libre — ceux qui se permutent sans rien déranger.

Un bandeau apparaît dès qu'un verrou ou une correction rend le dernier calcul dépassé, avec le bouton
pour le relancer. Et si le calcul n'a pas pu honorer un verrou — l'AESH n'est plus disponible, le
cours a disparu de l'emploi du temps — il le dit au lieu de l'ignorer en silence.

#### Le bilan

Quatre exports, en `.xlsx` et en `.html` imprimable :

| | Une feuille par | Couleur | Gris |
|---|---|---|---|
| **Emplois du temps des AESH** | accompagnant | par élève suivi | — |
| **Emplois du temps des élèves** | élève | par accompagnant | cours sans accompagnement |

Chaque classeur porte une feuille **Synthèse** et une feuille **Légende**. Dans les deux cas, les
créneaux consécutifs identiques sont fusionnés et les semaines A et B réunies quand le cours a lieu
toutes les semaines.

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
| L'import d'un dossier d'exports s'interrompt | Redéposez simplement le dossier : les fichiers déjà importés ne sont pas repris en double, l'import poursuit là où il s'était arrêté. Le détail est dans `PIAL-AESH/journal.log`. |
| « Load failed » pendant un import | Le navigateur avait invalidé les fichiers déposés. Corrigé depuis la version 1.4.2 : le contenu est lu dès le dépôt. Mettez l'application à jour. |

---

## En cas de problème : le journal

Tout ce que fait l'application est écrit dans **`PIAL-AESH/journal.log`** (dans votre dossier
personnel), en plus de la fenêtre noire. Le fichier est borné à 2 Mo et conserve l'exemplaire
précédent. Si quelque chose se passe mal, c'est ce fichier qu'il faut joindre : il contient l'heure,
l'opération en cours et le détail de l'erreur, alors que la fenêtre noire disparaît dès qu'on la ferme.

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
