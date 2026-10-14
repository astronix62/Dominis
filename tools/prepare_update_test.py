"""Crée l'application corrigée en v0.0.0, sans données personnelles.
Sans argument : ~/Dominis-test/Dominis. Un chemin explicite désigne le dossier final.
--check-release vérifie AVANT création que GitHub distribue exactement le code local.
Ne publie rien et ne remplace jamais un dossier non vide.
"""
import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
APP_FILES = ('Dominis.py', 'Lancer_Dominis.command', 'Lancer_Dominis.bat', 'Dominis.jpg')


def default_destination():
    return Path.home() / 'Dominis-test' / 'Dominis'


def load_application(source):
    # L'import de Dominis ne lance ni serveur, ni connexion, ni ouverture de base.
    spec = importlib.util.spec_from_file_location('dominis_release_check', source / 'Dominis.py')
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    return app


def verify_release(app, raw, version):
    """Même transport TLS et mêmes validations que l'application, plus égalité exacte."""
    data = json.loads(app.github_bytes(app.RELEASES_API, 1024 * 1024, 'application/vnd.github+json'))
    release = app.release_info(data)
    if release['version'] != version:
        raise ValueError(f"La dernière Release est {release['version']}, mais le code local est {version}. "
                         'Publiez le bon tag stable et définissez-le comme dernière Release.')
    expected_digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
    if release['size'] != len(raw) or (release['digest'] and release['digest'].lower() != expected_digest):
        raise ValueError(f'Le fichier Dominis.py publié dans {version} diffère du fichier corrigé local. '
                         'Remplacez la pièce jointe de la Release par le Dominis.py local (pas la copie v0.0.0). '
                         'Une pull request ne met pas à jour les pièces jointes des Releases.')
    # Même en l'absence d'empreinte GitHub, contrôler les octets réellement téléchargés.
    downloaded = app.github_bytes(release['url'], app.MAX_UPDATE_BYTES, 'application/octet-stream')
    app.validate_update_source(downloaded, version)
    if downloaded != raw:
        raise ValueError('Le téléchargement GitHub ne correspond pas exactement au fichier local. Test annulé.')
    print(f'Release {version} vérifiée : téléchargement HTTPS, code et empreinte identiques au fichier local.')


def prepare(destination=None, check_release=False):
    source = ROOT / 'Dominis'
    destination = Path(destination if destination is not None else default_destination()).expanduser().resolve()
    if destination == ROOT or ROOT in destination.parents:
        raise ValueError('Choisissez un dossier de test en dehors du dépôt.')
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError('Le dossier de test doit être vide : aucun fichier existant ne sera remplacé.')
    # Vérifier tous les fichiers avant de créer quoi que ce soit. Ne jamais copier
    # tout le dossier source : il contient potentiellement data.db et des sauvegardes.
    for name in APP_FILES:
        if not (source / name).is_file():
            raise ValueError('Fichier nécessaire introuvable : ' + name)
    raw = (source / 'Dominis.py').read_bytes()
    versions = re.findall(rb"^APP_VERSION = '(v\d+\.\d+\.\d+)'\r?$", raw, re.MULTILINE)
    if len(versions) != 1:
        raise ValueError('Déclaration APP_VERSION introuvable ou ambiguë.')
    version = versions[0].decode('ascii')
    app = load_application(source)
    app.validate_update_source(raw, version)
    if app.version_tuple(version) <= (0, 0, 0):
        raise ValueError('La version source doit être supérieure à v0.0.0 pour tester une mise à jour.')
    if check_release:
        verify_release(app, raw, version)
    current = f"APP_VERSION = '{version}'".encode('ascii')
    # Remplacement ancré : seuls les octets de la déclaration de version changent.
    test_raw = re.sub(rb"(?m)^" + re.escape(current) + rb"(?=\r?$)", b"APP_VERSION = 'v0.0.0'", raw, count=1)
    app.validate_update_source(test_raw, 'v0.0.0')
    destination.mkdir(parents=True, exist_ok=True)
    for name in APP_FILES:
        content = test_raw if name == 'Dominis.py' else (source / name).read_bytes()
        # 'xb' protège aussi contre un fichier ajouté après la vérification initiale.
        with (destination / name).open('xb') as output:
            output.write(content)
        shutil.copymode(source / name, destination / name)
    print('Copie de test v0.0.0 prête : ' + str(destination))
    print('Application et lanceurs à jour. Seule la déclaration APP_VERSION du script a changé.')
    print('Aucune base personnelle, sauvegarde ou .venv copié. Une base vide sera créée au premier lancement.')
    if not check_release:
        print(f'ATTENTION : Release non vérifiée. Avant le test, joignez le Dominis.py corrigé {version} à la Release {version}.')
        print('Utilisez --check-release avec une nouvelle destination vide pour contrôler le fichier réellement publié.')
    print('Fermez toute autre instance Dominis avant de lancer la copie (même port par défaut).')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', nargs='?', help='Dossier final vide (défaut : ~/Dominis-test/Dominis)')
    parser.add_argument('--check-release', action='store_true', help='Exiger une Release identique au code local avant création')
    args = parser.parse_args()
    try: prepare(args.destination, check_release=args.check_release)
    except (ValueError, OSError, SyntaxError) as e: parser.exit(1, str(e) + '\n')
