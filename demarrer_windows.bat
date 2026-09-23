@echo off
REM Lancement de l'application « PIAL — Affectation des AESH » sous Windows.
REM Double-cliquez sur ce fichier. Une fenetre noire s'ouvre : laissez-la ouverte
REM tant que vous utilisez l'application, elle la fait tourner.
cd /d "%~dp0"
echo Demarrage de l'application...
where py >nul 2>nul && (py -3 app.py & goto :fin)
where python >nul 2>nul && (python app.py & goto :fin)
echo.
echo Python n'a pas ete trouve sur ce poste.
echo Installez Python 3.11 depuis https://www.python.org/downloads/
echo en cochant « Add python.exe to PATH », puis relancez ce fichier.
pause
:fin
