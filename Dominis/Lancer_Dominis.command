#!/bin/bash
# Lanceur macOS : ferme uniquement sa fenêtre Terminal dédiée, après une sortie normale.
cd "$(dirname "$0")" || exit 1
printf '\n  DOMINIS — Votre patrimoine, en toute clarté.\n\n'
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; assert sys.version_info >= (3,10)' >/dev/null 2>&1; then
    echo 'Python 3.10+ est nécessaire (Python 3.12 ou 3.13 recommandé).'
    echo 'Installez-le depuis https://www.python.org/downloads/macos/ puis relancez.'
    read -r -p 'Appuyez sur Entrée pour fermer.'
    exit 1
fi
if [ ! -x '.venv/bin/python' ]; then
    echo "Préparation de l'environnement local…"
    python3 -m venv .venv || { read -r -p 'Échec de la création. Appuyez sur Entrée.'; exit 1; }
fi
if ! .venv/bin/python -c 'import webview' >/dev/null 2>&1; then
    echo 'Installation initiale de la fenêtre native (connexion Internet requise).'
    .venv/bin/python -m pip install 'pywebview>=5.4,<7' || echo 'Installation impossible. Ouverture de secours dans le navigateur.'
fi
.venv/bin/python Dominis.py --desktop
RESULT=$?
if [ "$RESULT" -ne 0 ]; then
    read -r -p 'Dominis a rencontré une erreur. Consultez le message ci-dessus. Entrée pour fermer.'
    exit "$RESULT"
fi
# Python est arrêté : les écritures ont été validées avant de fermer l'interface.
# Terminal ne gère pas de façon fiable « close tab ». On ferme la fenêtre qui
# contient notre TTY, seulement si elle n'héberge aucun autre onglet.
# Ne jamais utiliser « front window » ou « quit Terminal » : la sélection peut changer.
if [ "${TERM_PROGRAM:-}" = "Apple_Terminal" ] && [ -t 0 ]; then
    DOMINIS_TTY=$(tty)
    # Le délai laisse le lanceur sortir ; nohup protège l'assistant à sa fermeture.
    nohup /usr/bin/osascript - "$DOMINIS_TTY" <<'APPLESCRIPT' >/dev/null 2>&1 &
on run argv
    set targetTTY to item 1 of argv
    delay 1
    tell application "Terminal"
        repeat with w in windows
            repeat with t in tabs of w
                if tty of t is targetTTY then
                    if (count of tabs of w) is 1 then
                        close w
                    end if
                    return
                end if
            end repeat
        end repeat
    end tell
end run
APPLESCRIPT
fi
exit 0
