# -*- mode: python ; coding: utf-8 -*-
"""
Recette PyInstaller de l'application « PIAL — Affectation des AESH ».

    pyinstaller empaqueter/pial_aesh.spec

Produit un exécutable autonome : ni Python ni dépendance à installer sur le poste de destination.
PyInstaller ne sait pas produire un exécutable Windows depuis macOS ou Linux ; la compilation doit
avoir lieu sur le système visé. C'est le rôle de .github/workflows/application-windows.yml.
"""

from pathlib import Path
from PyInstaller.utils.hooks import collect_all

RACINE = Path(SPECPATH).parent

# OR-Tools embarque des bibliothèques natives et des fichiers de données que l'analyse statique
# ne voit pas : on les prend en bloc, faute de quoi l'exécutable démarre puis échoue au calcul.
donnees_ortools, binaires_ortools, imports_ortools = collect_all("ortools")

a = Analysis(
    [str(RACINE / "app.py")],
    pathex=[str(RACINE)],
    binaries=binaires_ortools,
    datas=[(str(RACINE / "pial_aesh" / "static"), "pial_aesh/static"),
           (str(RACINE / "GUIDE_APPLICATION.md"), ".")] + donnees_ortools,
    hiddenimports=["pial_aesh.serveur", "pial_aesh.projet", "pial_aesh.export",
                   "pial_aesh.affectation", "pial_aesh.pronote", "pial_aesh.pial",
                   "pial_aesh.matieres", "pial_aesh.tableur"] + imports_ortools,
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy.distutils", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="PIAL-Affectation-AESH",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    # Fenêtre console volontairement conservée : elle affiche l'adresse de l'interface et sert de
    # bouton d'arrêt (la fermer arrête l'application), ce que le guide explique à l'utilisatrice.
    console=True,
    disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)
