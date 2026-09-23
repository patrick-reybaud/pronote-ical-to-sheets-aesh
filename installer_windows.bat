@echo off
REM Installation des dependances, a faire une seule fois par poste.
cd /d "%~dp0"
echo Installation des composants necessaires...
where py >nul 2>nul && (py -3 -m pip install -r requirements.txt & goto :fin)
where python >nul 2>nul && (python -m pip install -r requirements.txt & goto :fin)
echo.
echo Python n'a pas ete trouve sur ce poste.
echo Installez Python 3.11 depuis https://www.python.org/downloads/
echo en cochant « Add python.exe to PATH », puis relancez ce fichier.
:fin
echo.
echo Termine. Vous pouvez maintenant double-cliquer sur demarrer_windows.bat
pause
