@echo off
REM Lancement de l'application « PIAL — Affectation des AESH » sous Windows, depuis le code source.
REM Double-cliquez sur ce fichier : l'application s'ouvre dans sa propre fenetre.
REM On prefere pythonw, qui ne laisse pas de fenetre noire derriere lui.
cd /d "%~dp0"
where pyw >nul 2>nul && (start "" pyw -3 app.py & goto :fin)
where pythonw >nul 2>nul && (start "" pythonw app.py & goto :fin)
where py >nul 2>nul && (py -3 app.py & goto :fin)
where python >nul 2>nul && (python app.py & goto :fin)
echo.
echo Python n'a pas ete trouve sur ce poste.
echo Installez Python 3.11 depuis https://www.python.org/downloads/
echo en cochant « Add python.exe to PATH », puis relancez ce fichier.
pause
:fin
