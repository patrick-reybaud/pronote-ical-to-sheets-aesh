#!/bin/bash
# Lancement de l'application « PIAL — Affectation des AESH » sous macOS, depuis le code source.
# Double-cliquez sur ce fichier : l'application s'ouvre dans sa propre fenêtre. Le Terminal reste
# ouvert derrière — il sert seulement à lancer, et affiche le journal en cas de souci.
cd "$(dirname "$0")" || exit 1
if [ -x "./venv/bin/python" ]; then
  exec ./venv/bin/python app.py
elif command -v python3 >/dev/null; then
  exec python3 app.py
else
  echo "Python 3 est introuvable. Installez-le depuis https://www.python.org/downloads/"
  read -r -p "Appuyez sur Entrée pour fermer."
fi
