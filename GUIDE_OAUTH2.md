# Guide de configuration OAuth2 (Google Sheets / Drive)

Ce guide explique comment créer les identifiants OAuth2 nécessaires pour que `generer_edt.py` crée les classeurs
dans **votre** Drive Google. À faire **une seule fois** ; le fichier obtenu (`credentials_oauth.json`) est réutilisable
d'une année sur l'autre.

## Pourquoi OAuth2 ?

OAuth2 permet au script d'utiliser **votre** compte Google et **votre** quota Drive (au lieu du quota limité d'un
compte de service). Le Google Sheet créé apparaît directement dans votre Drive, et vous pouvez le partager.

Le script demande deux autorisations (scopes) : `spreadsheets` (créer/écrire des classeurs) et `drive.file`
(accès limité aux fichiers qu'il a lui-même créés).

## 📋 Étapes de configuration

### Étape 1 : Accéder à Google Cloud Console

1. Allez sur [Google Cloud Console](https://console.cloud.google.com/)
2. Connectez-vous avec le compte Google qui recevra les classeurs
3. Sélectionnez un projet existant ou créez-en un nouveau (ex. « Export EDT AESH »)

### Étape 2 : Activer les API nécessaires

1. Menu (☰) → **« API et services »** → **« Bibliothèque »**
2. Recherchez **« Google Sheets API »** → **« Activer »**
3. Revenez à la bibliothèque et répétez pour **« Google Drive API »**

### Étape 3 : Configurer l'écran de consentement OAuth

1. **« API et services »** → **« Écran de consentement OAuth »**
2. Type d'utilisateur : **« Externe »** → **« Créer »**
3. Renseignez les champs **obligatoires** :
   - **Nom de l'application** : « Export EDT AESH » (ou autre)
   - **E-mail d'assistance utilisateur** et **e-mail du développeur** : votre adresse
4. **« Enregistrer et continuer »**
5. **« Champs d'application »** : rien à ajouter → **« Enregistrer et continuer »**
6. **« Utilisateurs de test »** : **« + Ajouter des utilisateurs »** → votre adresse Google → **« Enregistrer et continuer »**
7. **« Retour au tableau de bord »**

> ℹ️ **Statut « Test » et expiration à 7 jours.** Tant que l'application est en statut « Test », Google fait expirer
> le jeton de rafraîchissement au bout de **7 jours** : il faut alors relancer `python auth_google.py` (navigateur).
> Pour supprimer cette limite : sur l'écran de consentement, cliquez sur **« Publier l'application »** (statut
> « En production »). L'application reste « non validée » par Google — l'écran d'avertissement à la connexion
> subsiste (voir « Première utilisation ») — mais le jeton ne périme plus au bout de 7 jours.

### Étape 4 : Créer les identifiants OAuth 2.0

1. **« API et services »** → **« Identifiants »**
2. **« + Créer des identifiants »** → **« ID client OAuth »**
3. **Type d'application** : **« Application de bureau »**
4. Nom : « Client Desktop Export EDT » (ou autre) → **« Créer »**
5. Une fenêtre affiche vos identifiants → **« OK »**

### Étape 5 : Télécharger le fichier JSON

1. Dans la liste **« ID client OAuth 2.0 »**, repérez le client créé
2. Cliquez sur l'icône **téléchargement** (⬇️) à droite
3. **Renommez** le fichier téléchargé en **`credentials_oauth.json`**
4. **Placez-le à la racine du projet** (le dossier qui contient `generer_edt.py`)

## ✅ Vérification

La racine du projet doit contenir :

```
pronote-ical-to-sheets-aesh/
├── credentials_oauth.json  ← nouveau fichier (hors git)
├── generer_edt.py
├── auth_google.py
├── requirements.txt
└── …
```

## 🚀 Première utilisation

```bash
source venv/bin/activate
python auth_google.py
```

1. Un navigateur s'ouvre automatiquement (sinon : copier l'URL affichée dans le terminal).
2. Connectez-vous avec votre compte Google (celui ajouté en utilisateur de test).
3. Google avertit que l'application n'est pas validée : **« Paramètres avancés »** → **« Accéder à … (non sécurisé) »**.
4. Autorisez l'accès à Google Sheets et Drive.
5. Le script écrit `token.json`, vérifie l'accès à l'API et affiche `✓ Accès API OK`.

**Utilisations suivantes** : `generer_edt.py --google` réutilise `token.json` et le rafraîchit automatiquement ;
pas besoin de se reconnecter, sauf expiration (statut « Test », voir ci-dessus).

## 🔒 Sécurité

- ⚠️ **Ne partagez JAMAIS** `credentials_oauth.json` ni `token.json` : ils donnent accès à votre compte Google.
- Ils sont ignorés par git (voir `.gitignore`) et ne doivent jamais apparaître dans le dépôt.
- Pour révoquer l'accès : [myaccount.google.com/permissions](https://myaccount.google.com/permissions) → retirer l'application,
  puis supprimer `token.json`.

## 🆘 Dépannage

| Message | Cause | Solution |
|---|---|---|
| « Access blocked: This app's request is invalid » | écran de consentement non configuré | Étape 3 |
| « The app is blocked » / « Accès bloqué : … n'a pas terminé la validation » | votre adresse n'est pas utilisateur de test | Étape 3, point 6 |
| « invalid_grant », « Token has been expired or revoked » | jeton périmé (7 jours en statut Test) ou révoqué | supprimer `token.json` et relancer `python auth_google.py` |
| Le navigateur ne s'ouvre pas | pas de navigateur par défaut | ouvrir manuellement l'URL affichée |
| « credentials_oauth.json introuvable » | fichier absent ou mal nommé | Étape 5 |

---

**Vous êtes prêt !** Suivez ensuite [PROCEDURE.md](PROCEDURE.md) pour préparer l'année et générer les emplois du temps.
