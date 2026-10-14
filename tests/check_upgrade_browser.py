"""Test navigateur facultatif : vraie installation v0.0.0 → v0.0.2 et reconnexion.
Seules les réponses GitHub sont simulées. Copie du programme et base temporaires.
Nécessite Playwright ; CHROMIUM_PATH permet de choisir le navigateur.
"""
import asyncio
import re
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from playwright.async_api import async_playwright

APP = Path(__file__).resolve().parents[1] / 'Dominis' / 'Dominis.py'


async def main():
    with tempfile.TemporaryDirectory(prefix='Dominis browser upgrade ') as temp:
        folder = Path(temp)
        fixture = '''
def github_bytes(url, limit, accept):
    if url == RELEASES_API: return (ROOT / 'release.json').read_bytes()
    return (ROOT / 'release-payload.bin').read_bytes()
'''
        source = APP.read_text(encoding="utf-8").replace("if __name__=='__main__':", fixture + "\nif __name__=='__main__':")
        # Aligner le test navigateur sur la version préparée dans ce dépôt.
        source = re.sub(r"^APP_VERSION = 'v\d+\.\d+\.\d+'$", "APP_VERSION = 'v0.0.2'", source, count=1, flags=re.MULTILINE)
        raw = source.encode()
        (folder / 'release-payload.bin').write_bytes(raw)
        (folder / 'Dominis.py').write_text(source.replace("APP_VERSION = 'v0.0.2'", "APP_VERSION = 'v0.0.0'", 1), encoding="utf-8", newline="\n")
        (folder / 'release.json').write_text(json.dumps({'tag_name': 'v0.0.2', 'draft': False, 'prerelease': False,
            'assets': [{'name': 'Dominis.py', 'state': 'uploaded', 'size': len(raw),
                        'browser_download_url': 'https://github.com/astronix62/Dominis/releases/download/v0.0.2/Dominis.py',
                        'digest': 'sha256:' + hashlib.sha256(raw).hexdigest()}]}))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        with open(folder / 'run.log', 'w') as log:
            proc = subprocess.Popen([sys.executable, str(folder / 'Dominis.py'), '--demo', '--no-browser', '--port', str(port)], stdout=log, stderr=log)
            try:
                async with async_playwright() as p:
                    opts = {'headless': True, 'args': ['--no-sandbox', '--disable-dev-shm-usage']}
                    if os.environ.get('CHROMIUM_PATH'): opts['executable_path'] = os.environ['CHROMIUM_PATH']
                    browser = await p.chromium.launch(**opts)
                    page = await browser.new_page(viewport={'width': 1440, 'height': 1000})
                    errors = []; page.on('pageerror', lambda err: errors.append(str(err)))
                    for attempt in range(50):
                        try:
                            await page.goto(url, timeout=2000); break
                        except Exception: await asyncio.sleep(.1)
                    else: raise AssertionError('Serveur non démarré')
                    await page.get_by_role('dialog', name='Mise à jour disponible', exact=True).wait_for()
                    await page.get_by_text('Version installée : v0.0.0', exact=True).wait_for()
                    # État qui devra être préservé à l’identique, avant de demander l’installation.
                    before = await page.evaluate('({scis:S.scis,records:S.records,settings:S.settings})')
                    Path('.cache').mkdir(exist_ok=True)
                    await page.screenshot(path='.cache/real-update-v000-to-v002.png', full_page=True)
                    await page.get_by_role('button', name='Mettre à jour', exact=True).click()
                    await page.locator('#update-progress').wait_for()
                    # La page doit se recharger toute seule, avec le nouveau jeton de session.
                    await page.get_by_text('Mise à jour réussie. Dominis v0.0.2 a redémarré automatiquement.', exact=True).wait_for(timeout=30000)
                    await page.get_by_role('heading', name='Votre patrimoine, en perspective.').wait_for()
                    assert await page.evaluate('S.app_version') == 'v0.0.2'
                    after = await page.evaluate('({scis:S.scis,records:S.records,settings:S.settings})')
                    assert after == before
                    assert (folder / 'Dominis.py').read_bytes() == raw
                    assert len(list(folder.glob('*.py'))) == 1
                    await page.screenshot(path='.cache/real-update-success.png', full_page=True)
                    await page.locator('#sidebar [data-action="quit"]').click()
                    await page.locator('#confirm-quit').click()
                    assert await asyncio.to_thread(proc.wait, timeout=10) == 0
                    assert not errors, errors
                    await browser.close()
            finally:
                if proc.poll() is None:
                    # Groupe de test limité : signaler le superviseur en cas d'échec seulement.
                    proc.terminate(); proc.wait(timeout=5)
        print('Navigateur E2E OK : proposition v0.0.2, installation réelle, redémarrage et rechargement automatiques, données conservées.')


if __name__ == '__main__': asyncio.run(main())
