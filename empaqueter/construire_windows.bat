@echo off
REM Compilation de l'executable Windows. A lancer SUR UN POSTE WINDOWS, depuis le dossier du projet.
REM Resultat : dist\PIAL-Affectation-AESH.exe
cd /d "%~dp0\.."
echo === Installation des dependances ===
py -3 -m pip install --upgrade pip
py -3 -m pip install -r requirements.txt pyinstaller
echo.
echo === Compilation (plusieurs minutes) ===
py -3 -m PyInstaller --clean --noconfirm empaqueter\pial_aesh.spec
echo.
if exist dist\PIAL-Affectation-AESH.exe (
  echo === Termine : dist\PIAL-Affectation-AESH.exe ===
) else (
  echo === ECHEC : l'executable n'a pas ete produit, voir les messages ci-dessus ===
)
pause
