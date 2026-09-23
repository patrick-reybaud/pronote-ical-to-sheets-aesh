#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — lanceur de l'application « PIAL — Affectation des AESH ».

    python app.py

L'application est un logiciel de bureau : elle démarre un petit serveur qui n'écoute que sur cette
machine (127.0.0.1) et ouvre son interface dans le navigateur par défaut. Aucune donnée ne quitte le
poste. Le même fichier fonctionne sur Windows et sur macOS.

Options :
    --port 8765        port d'écoute (un autre est choisi automatiquement s'il est occupé)
    --sans-navigateur  ne pas ouvrir le navigateur (utile pour un test automatisé)
"""

import argparse
import socket
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PORT_DEFAUT = 8765


def port_libre(souhaite, essais=20):
    """Premier port disponible à partir de celui demandé — évite l'échec si l'appli tourne déjà."""
    for port in range(souhaite, souhaite + essais):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit(f"Aucun port libre entre {souhaite} et {souhaite + essais}.")


def main():
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--port", type=int, default=PORT_DEFAUT)
    analyseur.add_argument("--sans-navigateur", action="store_true")
    arguments = analyseur.parse_args()

    try:
        from pial_aesh.serveur import application
        from pial_aesh.projet import DOSSIER_PROJETS
    except ImportError as e:
        raise SystemExit(
            f"Dépendance manquante : {e.name or e}.\n"
            f"Installez-les avec :\n    {sys.executable} -m pip install -r requirements.txt")

    port = port_libre(arguments.port)
    adresse = f"http://127.0.0.1:{port}/"
    DOSSIER_PROJETS.mkdir(parents=True, exist_ok=True)

    print("=" * 66)
    print("  PIAL — Affectation des AESH")
    print("=" * 66)
    print(f"  Interface   : {adresse}")
    print(f"  Projets     : {DOSSIER_PROJETS}")
    print("  Pour quitter: fermez cette fenêtre, ou Ctrl+C")
    print("=" * 66)

    if not arguments.sans_navigateur:
        threading.Timer(1.0, lambda: webbrowser.open(adresse)).start()
    try:
        application.run(host="127.0.0.1", port=port, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\nArrêt de l'application.")


if __name__ == "__main__":
    main()
