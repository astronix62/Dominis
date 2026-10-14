@echo off
setlocal
title Dominis - Gestion patrimoniale
cd /d "%~dp0"
echo.
echo   DOMINIS - Votre patrimoine, en toute clarte.
echo.
set "PY=py -3"
%PY% -c "import sys; assert sys.version_info >= (3,10)" >nul 2>&1
if errorlevel 1 (
    set "PY=python"
)
%PY% -c "import sys; assert sys.version_info >= (3,10)" >nul 2>&1
if errorlevel 1 (
    echo Python 3.10 ou plus recent est necessaire.
    echo Installez de preference Python 3.12 ou 3.13 depuis https://www.python.org/downloads/
    echo Cochez Add Python to PATH, puis relancez ce fichier.
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    echo Preparation de l'environnement local...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo Impossible de creer l'environnement. Verifiez les droits du dossier.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" -c "import webview" >nul 2>&1
if errorlevel 1 (
    echo Installation initiale de la fenetre native. Connexion Internet requise.
    ".venv\Scripts\python.exe" -m pip install "pywebview>=5.4,<7"
    if errorlevel 1 (
        echo La fenetre native n'a pas pu etre installee.
        echo Dominis fonctionnera dans votre navigateur, sans cette dependance.
    )
)
".venv\Scripts\python.exe" Dominis.py --desktop
if errorlevel 1 (
    echo.
    echo Dominis s'est arrete avec une erreur. Consultez le message ci-dessus.
    pause
    exit /b 1
)
endlocal
exit /b 0
