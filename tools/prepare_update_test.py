"""Prépare une copie isolée v0.0.0, équipée du mécanisme de mise à jour.
Usage : python tools/prepare_update_test.py /chemin/vers/Dominis-test
Ne copie jamais la base de données personnelle et n'écrit jamais dans le dépôt.
"""
import argparse
from pathlib import Path
import shutil


def prepare(destination):
    root = Path(__file__).resolve().parents[1]
    source = root / 'Dominis'
    destination = Path(destination).expanduser().resolve()
    if destination == root or root in destination.parents:
        raise ValueError('Choisissez un dossier de test en dehors du dépôt.')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Le dossier de test doit être vide : aucun fichier existant ne sera remplacé.')
    text = (source / 'Dominis.py').read_text(encoding='utf-8')
    current = "APP_VERSION = 'v0.0.1'"
    if text.count(current) != 1:
        raise ValueError('Cet outil prépare uniquement le test v0.0.0 → v0.0.1.')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'Dominis.py').write_text(text.replace(current, "APP_VERSION = 'v0.0.0'", 1), encoding='utf-8')
    for name in ('Lancer_Dominis.command', 'Lancer_Dominis.bat'):
        shutil.copy2(source / name, destination / name)
    print('Copie de test v0.0.0 prête : ' + str(destination))
    print('Aucune base personnelle copiée. Créez des données fictives avant le test.')
    print('La proposition apparaîtra après publication de la Release v0.0.1 avec Dominis.py en pièce jointe.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination')
    args = parser.parse_args()
    try: prepare(args.destination)
    except (ValueError, OSError) as e: parser.exit(1, str(e) + '\n')
