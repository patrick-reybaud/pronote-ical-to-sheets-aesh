#!/bin/bash
# Lancement de l'application « PIAL — Affectation des AESH » sous macOS.
# Double-cliquez sur ce fichier ; laissez la fenêtre Terminal ouverte pendant l'utilisation.
cd "$(dirname "$0")" || exit 1
if [ -x "./venv/bin/python" ]; then
  exec ./venv/bin/python app.py
elif command -v python3 >/dev/null; then
  exec python3 app.py
else
  echo "Python 3 est introuvable. Installez-le depuis https://www.python.org/downloads/"
  read -r -p "Appuyez sur Entrée pour fermer."
fi
