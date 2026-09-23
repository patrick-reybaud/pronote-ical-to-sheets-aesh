#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — lanceur de l'application « PIAL — Affectation des AESH ».

    python app.py

L'application est un logiciel de bureau. Elle s'ouvre dans **une seule fenêtre** : le moteur de
rendu du système y affiche l'interface, et le petit serveur qui la fait vivre tourne à l'intérieur
du même programme, sans fenêtre noire à côté. Il n'écoute que sur cette machine (127.0.0.1) et
aucune donnée ne quitte le poste. Fermer la fenêtre arrête tout.

Le même fichier fonctionne sur Windows (moteur Edge WebView2) et sur macOS (WebKit).

Options :
    --port 8765         port d'écoute (un autre est choisi automatiquement s'il est occupé)
    --navigateur        ouvrir dans le navigateur par défaut au lieu de la fenêtre
    --sans-interface    ne rien ouvrir du tout (test automatisé) — alias : --sans-navigateur
"""

import argparse
import ctypes
import logging
import logging.handlers
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PORT_DEFAUT = 8765
TAILLE_JOURNAL = 2 * 1024 * 1024      # 2 Mo, deux fichiers conservés
TITRE = "PIAL — Affectation des AESH"


def console():
    """
    Flux de sortie utilisable, ou None.

    Empaquetée en fenêtre, l'application n'a plus de console : `sys.stdout` peut être absent, et le
    moindre `print` ferait alors échouer le démarrage sans que personne ne sache pourquoi.
    """
    flux = sys.stdout
    try:
        flux.write("")
        flux.flush()
    except Exception:
        return None
    return flux


def alerte(message):
    """
    Signale un échec de démarrage à l'utilisateur, même sans console.

    C'est la contrepartie de la fenêtre unique : plus rien ne s'affiche nulle part si le démarrage
    échoue. On montre donc une boîte de dialogue du système, et on rappelle où se trouve le journal.
    """
    logging.getLogger("pial").error(message)
    flux = console()
    if flux:
        print(message, file=flux)
    try:
        if sys.platform.startswith("win"):
            ctypes.windll.user32.MessageBoxW(None, message, TITRE, 0x10)
        elif sys.platform == "darwin":
            subprocess.run(["osascript", "-e",
                            f'display alert "{TITRE}" message "{message}" as critical'], check=False)
    except Exception:
        pass


def installer_journal(dossier):
    """
    Écrit tout ce que fait l'application dans un fichier.

    Sans cela, un incident survenu chez l'utilisatrice ne laisse aucune trace : la fenêtre est
    fermée, et il ne reste rien à examiner. Le fichier est borné et tourne sur deux exemplaires.
    """
    dossier.mkdir(parents=True, exist_ok=True)
    fichier = dossier / "journal.log"
    rotation = logging.handlers.RotatingFileHandler(
        fichier, maxBytes=TAILLE_JOURNAL, backupCount=1, encoding="utf-8")
    rotation.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
                                            "%d/%m %H:%M:%S"))
    racine = logging.getLogger()
    racine.setLevel(logging.INFO)
    racine.addHandler(rotation)
    flux = console()
    if flux:
        racine.addHandler(logging.StreamHandler(flux))
    return fichier


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


def demarrer_serveur(application, port):
    """Lance le serveur dans un fil d'exécution et rend la main dès qu'il répond."""
    def servir():
        try:
            # Le serveur intégré de Flask est un serveur de développement : il lâche des connexions
            # lors d'envois volumineux et répétés, ce qui interrompait l'import d'un dossier
            # d'exports ProNote à un endroit variable. Waitress est un serveur WSGI complet, en
            # Python pur, qui tient la charge et fonctionne aussi bien sous Windows.
            from waitress import serve
            serve(application, host="127.0.0.1", port=port, threads=8,
                  channel_timeout=1800,          # un import ou un calcul peut durer longtemps
                  max_request_body_size=2 * 1024 ** 3,
                  ident="PIAL-AESH", clear_untrusted_proxy_headers=True)
        except ImportError:
            logging.getLogger("pial").warning(
                "waitress absent — repli sur le serveur de développement, moins robuste "
                "lors de l'import de nombreux fichiers")
            application.run(host="127.0.0.1", port=port, debug=False, threaded=True)

    threading.Thread(target=servir, daemon=True, name="serveur").start()
    # La fenêtre ne doit pas s'ouvrir sur une page d'erreur parce que le serveur n'est pas encore
    # prêt : on attend qu'il accepte une connexion, ce qui prend une fraction de seconde.
    for _ in range(200):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.05)
    return False


def ouvrir_fenetre(adresse, dossier_travail):
    """
    Affiche l'interface dans une fenêtre du système. Retourne False si ce n'est pas possible.

    Sur Windows le moteur est celui d'Edge (WebView2), présent d'origine sur Windows 11 et installé
    par Edge sur Windows 10 ; sur macOS c'est WebKit. Si le moteur manque, on ne bloque pas
    l'utilisatrice : on repasse par le navigateur, qui fonctionne partout.
    """
    try:
        import webview
    except ImportError:
        logging.getLogger("pial").info("pywebview absent — ouverture dans le navigateur")
        return False
    try:
        # Sans cela, les exports ne s'enregistreraient pas : le téléchargement est refusé par
        # défaut dans une fenêtre applicative.
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.create_window(TITRE, adresse, width=1440, height=920, min_size=(1024, 680))
        webview.start(private_mode=False, storage_path=str(dossier_travail / ".fenetre"))
        return True
    except Exception as e:
        logging.getLogger("pial").warning("fenêtre impossible (%s) — ouverture dans le navigateur", e)
        return False


def main():
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--port", type=int, default=PORT_DEFAUT)
    analyseur.add_argument("--navigateur", action="store_true",
                           help="ouvrir dans le navigateur par défaut plutôt que dans la fenêtre")
    analyseur.add_argument("--sans-interface", "--sans-navigateur", action="store_true",
                           dest="sans_interface", help="ne rien ouvrir (test automatisé)")
    arguments = analyseur.parse_args()

    try:
        from pial_aesh.serveur import application
        from pial_aesh.projet import DOSSIER_PROJETS
    except ImportError as e:
        alerte(f"Dépendance manquante : {e.name or e}.\n"
               f"Installez-les avec :\n    {sys.executable} -m pip install -r requirements.txt")
        raise SystemExit(1)

    port = port_libre(arguments.port)
    adresse = f"http://127.0.0.1:{port}/"
    journal = installer_journal(DOSSIER_PROJETS)

    flux = console()
    if flux:
        print("=" * 66, file=flux)
        print(f"  {TITRE}", file=flux)
        print("=" * 66, file=flux)
        print(f"  Interface   : {adresse}", file=flux)
        print(f"  Projets     : {DOSSIER_PROJETS}", file=flux)
        print(f"  Journal     : {journal}", file=flux)
        print("=" * 66, file=flux)
    logging.getLogger("pial").info("démarrage sur %s", adresse)

    if not demarrer_serveur(application, port):
        alerte(f"Le serveur interne n'a pas démarré sur le port {port}.\n"
               f"Détails dans le journal : {journal}")
        raise SystemExit(1)

    if arguments.sans_interface:
        attendre()
    elif arguments.navigateur or not ouvrir_fenetre(adresse, DOSSIER_PROJETS):
        webbrowser.open(adresse)
        if flux:
            print("  Pour quitter : fermez cette fenêtre, ou Ctrl+C", file=flux)
        attendre()
    logging.getLogger("pial").info("arrêt de l'application")


def attendre():
    """Maintient l'application en vie quand aucune fenêtre ne le fait à notre place."""
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        flux = console()
        if flux:
            print("\nArrêt de l'application.", file=flux)


if __name__ == "__main__":
    main()
