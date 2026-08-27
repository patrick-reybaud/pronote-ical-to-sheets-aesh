#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auth_google.py — (Ré)authentification Google pour generer_edt.py.

À lancer dans un terminal (un navigateur s'ouvre) :
    source venv/bin/activate
    python auth_google.py

Le script tente d'abord de rafraîchir token.json ; s'il est absent ou périmé, il ouvre le navigateur,
puis vérifie l'accès à l'API Google Sheets. Rien n'est créé dans le Drive.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generer_edt import authentifier_google, FICHIER_TOKEN, FICHIER_CREDENTIALS  # noqa: E402


def main():
    print("=" * 60)
    print("Authentification Google — generer_edt.py")
    print("=" * 60)
    print(f"Identifiants client : {FICHIER_CREDENTIALS.name} {'✓' if FICHIER_CREDENTIALS.exists() else '✗ MANQUANT'}")
    print(f"Jeton utilisateur   : {FICHIER_TOKEN.name} {'présent' if FICHIER_TOKEN.exists() else 'absent → authentification dans le navigateur'}")
    print()
    creds = authentifier_google()
    print(f"✓ Jeton valide, expire à {creds.expiry} (UTC) ; rafraîchi automatiquement ensuite.")
    print("   Test d'accès à l'API Google Sheets…")
    import gspread
    client = gspread.authorize(creds)
    client.openall()  # liste (éventuellement vide) des classeurs créés par l'appli — vérifie l'accès sans rien créer
    print("✓ Accès API OK. Vous pouvez lancer :  python generer_edt.py --google")


if __name__ == "__main__":
    main()
