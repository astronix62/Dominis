#!/bin/bash
# Lanceur macOS. Ne ferme que son propre onglet Terminal, après une sortie normale.
cd "$(dirname "$0")" || exit 1
printf '\n  AURÉA — Votre patrimoine, en toute clarté.\n\n'
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
.venv/bin/python aurea.py --desktop
RESULT=$?
if [ "$RESULT" -ne 0 ]; then
    read -r -p 'Auréa a rencontré une erreur. Consultez le message ci-dessus. Entrée pour fermer.'
    exit "$RESULT"
fi
# Le processus Python est maintenant arrêté et les données ont été validées.
# Ne jamais quitter Terminal dans son ensemble : d'autres onglets peuvent servir.
if [ "${TERM_PROGRAM:-}" = "Apple_Terminal" ] && [ -t 0 ]; then
    AUREA_TTY=$(tty)
    /usr/bin/osascript - "$AUREA_TTY" <<'APPLESCRIPT' >/dev/null 2>&1 &
on run argv
    set targetTTY to item 1 of argv
    delay 0.5
    tell application "Terminal"
        repeat with w in windows
            repeat with t in tabs of w
                if tty of t is targetTTY then
                    close t
                    return
                end if
            end repeat
        end repeat
    end tell
end run
APPLESCRIPT
fi
exit 0
